# Day 17：CI／CD 與 OIDC 部署操作手冊

## 1. 檢查與身分邊界

`.github/workflows/ci.yml` 在 PR／push 執行，亦可供部署 workflow 重用。Python 3.11 安裝 `.[dev,warehouse,dashboard]`，執行 Ruff format／lint、套件的 strict mypy、251 項離線 unit tests，以及整體 80％、ingestion 90％、raw loader 85％的 coverage 門檻。歷史驗證 scripts 與 DAG 採 lint／測試，不宣稱它們已全數通過 strict mypy。

Airflow 以獨立的 `apache/airflow:3.3.2-python3.11` 容器真正匯入 DAG，檢查兩條 31-task 流程的 Pool、gate → publish 與跨月串行相依，不執行 task。UI unit tests 的 BigQuery Client 使用測試替身，禁止真實 query，不依賴 ADC。Docker job 建置 Lambda `linux/amd64` image，非法事件只驗證 handler 載入，不呼叫外部服務。

Terraform 1.16.2／AWS provider 6.64.0 的 lock file 包含 macOS ARM 與 Linux AMD64 checksum。CI 分別執行兩組 fmt、`init -backend=false -lockfile=readonly`、validate，不讀取 state，也不登入 AWS。

## 2. Bootstrap 與 OIDC trust

以既有 AWS 短期登入或授權 profile 執行 bootstrap，先查帳號是否已有 GitHub provider。已有 provider 時設定 `existing_github_oidc_provider_arn`，或先匯入既有 provider；不建立重複資源。全新環境仍須先建立 state bucket 並遷移 bootstrap state，見 [Terraform 管理](../infrastructure/aws/README.md)。

此 repository 的實際 OIDC 設定可用下列命令唯讀查核：

```bash
gh api repos/sunhua12/000-trade-analytics/actions/oidc/customization/sub
```

本次為 immutable subject，bootstrap 使用：

```hcl
github_repository = "sunhua12/000-trade-analytics"
github_oidc_subject_prefix = "repo:sunhua12@102355763/000-trade-analytics@1349279018"
github_deploy_branches = ["feature/ci-oidc-deployment"]
raw_bucket_name = "trade-analytics-prod-816079797958-ap-northeast-1-an"
```

以上設定保存於未追蹤的 `infrastructure/aws/bootstrap/day17.auto.tfvars`。Trust 以 `StringEquals` 限定上述 branch 型 `sub` 及 `aud=sts.amazonaws.com`。其他 repository、PR merge ref、任意分支均不匹配。GitHub 的新 repository 可能使用含 immutable IDs 的 subject，必須查實際值，不能僅以名稱推測。[官方 OIDC 說明](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)。

```bash
AWS_PROFILE=hua terraform -chdir=infrastructure/aws/bootstrap plan -out=oidc.tfplan
AWS_PROFILE=hua terraform -chdir=infrastructure/aws/bootstrap show oidc.tfplan
AWS_PROFILE=hua terraform -chdir=infrastructure/aws/bootstrap apply oidc.tfplan
AWS_PROFILE=hua terraform -chdir=infrastructure/aws/bootstrap plan -detailed-exitcode
```

部署角色與 execution role 分離，日常角色只推送指定 ECR、更新指定 Lambda code、讀取既有 application 資源，以及讀寫 application state／lockfile。不能修改部署角色自己、bootstrap state、raw 物件、IAM 或告警。`iam:PassRole` 限定 execution role 與 `iam:PassedToService=lambda.amazonaws.com`。ECR authorization token、DescribeLogGroups／DescribeAlarms 因 API 存取形式需 wildcard Resource，其他操作限制專案 ARN。

## 3. GitHub 設定與部署

| 設定 | 用途 |
|---|---|
| `AWS_DEPLOY_REF` variable | 精確受信任 ref，本次為 `refs/heads/feature/ci-oidc-deployment` |
| `AWS_AUTO_DEPLOY_ENABLED` variable | 只有明確設為 `true` 才讓 feature 分支 push 自動部署；驗收後設為 `false` |
| `AWS_DEPLOY_ROLE_ARN` variable | `trade-analytics-github-deploy` 角色 ARN |
| `AWS_REGION`／`AWS_ACCOUNT_ID` variables | 目標 Region 與帳號檢查 |
| `ECR_REPOSITORY`／`LAMBDA_FUNCTION` variables | 指定 ingestion 資源 |
| `TF_STATE_BUCKET` variable | 既有 application remote state bucket |
| `AWS_APPLICATION_TFVARS_JSON` secret | 保存現行 application 設定，參考 JSON 範本；不含 AWS 靜態 credential |

本次驗收暫時將 `AWS_AUTO_DEPLOY_ENABLED=true`，feature 分支指定檔案的 push 會先執行完整 CI，再執行真實部署；驗收後設回 `false`，一般 PR 不部署。關閉後，部署 workflow 的共用檢查與部署 job 一起略過，一般 PR／push 的獨立 CI 仍完整執行。另提供 `workflow_dispatch`，`apply=false` 只推送 image 並檢查 plan，`apply=true` 才 apply。GitHub 手動 dispatch 通常需要 workflow 已存在於預設分支，PR 合併後可用 Actions UI 或 `gh workflow run deploy-aws.yml --ref <受信任分支> -f apply=true`。

部署步驟如下：

1. 同一提交通過完整 CI；OIDC job 再取得最多 1 小時臨時憑證，確認 AWS 帳號。
2. 建置並推送以 Git SHA 標記的 `linux/amd64` image，查 ECR digest。
3. 連上獨立 application state key，使用保留的現行設定與不可變 `image_uri` 產生 saved plan。
4. `scripts/check_deploy_plan.py` 僅允許 `aws_lambda_function.ingestion` 的 image 更新與必要 computed 欄位；新建、替換、刪除、其他設定變更均失敗。
5. 同一 job apply 該 saved plan，等待 Lambda 更新，核對 resolved digest，再執行 plan，要求 exit code 0。
6. 保存去敏摘要與 verification artifact，保留 7 天；不上傳完整 plan／state。Git SHA、digest 與 run URL 另記入執行紀錄。

同環境 `concurrency` 序列化，`cancel-in-progress=false` 保護正在進行的 apply；S3 backend `use_lockfile=true` 保護 state 寫入。鎖定原理及權限見 [官方 S3 backend 文件](https://developer.hashicorp.com/terraform/language/backend/s3)。

合併到 `main` 後，須由 bootstrap 管理者將 trust branch 與 `AWS_DEPLOY_REF` 一起改為 `main`，重新檢視 plan／apply；不能僅改 GitHub variable 就宣稱 main 已授權。本次不自動合併 PR。

## 4. 失敗處置與回復

- CI 失敗：查看失敗 job，修正後產生新提交；`needs: checks` 會阻擋部署。
- OIDC 失敗：先核對實際 subject prefix、branch、aud、角色 ARN；不以加入任意 `sub` wildcard 解決。
- Terraform AccessDenied：依具體 API 與 ARN 評估必要讀取權限，由 bootstrap 修改受限政策；不改用 administrator 或本機身分冒充 OIDC run。
- Plan guard 失敗：保存去敏摘要，修正 application 設定／drift；若需改基礎設施，另以管理者身分執行已檢視的 IaC plan。
- Apply 結果不明：先查 workflow log、Lambda update state、resolved digest 與 remote state；不盲目換 digest、force-unlock 或重複 apply。
- 回復：從記錄選定仍保留於 ECR 的舊 digest，先以管理者身分或受控 workflow 設為 `image_uri`，產生 image-only plan，核對後 apply，再查 digest 與無 drift。回復步驟已定義，本日不宣稱完成真實回復演練。

本機後續 plan 必須使用最新部署 digest；舊 tfvars 的 image 值會把正常部署顯示為待回復的差異。不要以 Console／`update-function-code` 另行改寫 Lambda，造成 Terraform drift。

## 5. 手動 dbt 雲端測試

```bash
.venv/bin/python scripts/test_dbt_cloud.py \
  --project trade-analytics-508604 \
  --location asia-northeast1 \
  --run-id unique_test_identifier \
  --dbt .venv-dbt/bin/dbt \
  --max-bytes-billed 1000000000 \
  --evidence-dir docs/evidence/manual-dbt-test
```

入口使用本機 ADC；AWS OIDC 不提供 GCP 身分。每次建立新的 `trade_ci_<run_id>` Dataset，已存在時直接失敗，避免舊結果污染驗收。於暫存專案執行 seed → run --empty → build，raw sources 只讀，所有模型寫入隔離 target，publication audit 關閉；不呼叫 raw loader 或 publisher。專案現有 SQL 沒有指定其他寫入 schema。

每個查詢上限 1 GB，2 threads，180 秒 job timeout；此上限是每次查詢限制，不是整輪費用上限。表格預設 24 小時到期，Dataset 本身不自動刪除。完成後由管理者確認 Dataset 名稱再刪除測試 Dataset，勿對 raw／published 執行清理。保存 manifest、run_results、各階段 log、job ID 與處理量摘要；失敗回傳非零狀態。Job 摘要包含同一 ADC 使用者在測試時間窗內的 query，可能含同時執行的其他查詢。

本次 88 項 build 全部通過，包含 5 項 unit tests；dbt unit tests 仍使用真實 warehouse。[官方 unit tests 說明](https://docs.getdbt.com/docs/build/unit-tests)。
