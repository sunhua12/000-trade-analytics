# Day 17：CI／CD、OIDC 與 Terraform 執行紀錄

| 項目 | 紀錄 |
|---|---|
| 實作日期 | 2026-10-01（Asia/Taipei） |
| 分支 | `feature/ci-oidc-deployment` |
| 部署程式提交 | `ef3fb618868178cf3df07743b4aa7f97c0fd3d8a` |
| 狀態 | 真實 GitHub CI、OIDC → ECR → Terraform → Lambda 部署、digest 核對及無 drift 全部通過；隔離 dbt 雲端測試完成 |
| 本人實際學習工時 | 未提供；不以助理執行時間代填 |
| 操作入口 | [CI／CD 手冊](day17-cicd-manual.md) |

## 1. CI 與必要檢查

新增 `.github/workflows/ci.yml`，將 Python、真實 DAG import、Docker build 與兩組 Terraform 檢查分開執行。部署重用同一提交的 CI，全部通過才取得 AWS 身分。

| 檢查 | 結果與範圍 |
|---|---|
| Ruff format／lint | src、tests、scripts、dags、兩個根目錄 Python 入口通過；保留個人 `tests/TEST/` 排除 |
| strict mypy | `trade_analytics` package 的 18 個來源檔通過；歷史 scripts／DAG 不宣稱全數 strict typing |
| Python unit tests | 251 項通過；UI tests 使用拒絕真實 query 的 BigQuery Client 測試替身，不依賴 ADC |
| Coverage | 整體 91.53％、ingestion 97.03％、raw loader 96.52％，均超過總規格門檻 |
| Airflow | 真實 3.3.2 DagBag 匯入兩條 pipeline，各 31 個 task；Pool、gate、跨月串行與無排程 backfill 契約通過 |
| Docker | `linux/amd64` Lambda image 建置成功；非法事件 handler smoke test 通過，不呼叫 Comtrade／S3 |
| Terraform | 1.16.2／AWS provider 6.64.0，bootstrap／application fmt、init -backend=false、validate 通過；lock file 補齊 Linux AMD64 checksum |

真實 run：

- [首次失敗 CI](https://github.com/sunhua12/000-trade-analytics/actions/runs/36832393166)：發現 UI 意外依賴 ADC、lock file 缺 Linux checksum、Airflow SDK timetable 型別不同；不是刻意注入的錯誤。
- [首次部署被阻擋](https://github.com/sunhua12/000-trade-analytics/actions/runs/36832393501)：CI 失敗使 deploy job skipped，沒有發布映像或改寫 Lambda。
- [修正後成功 CI](https://github.com/sunhua12/000-trade-analytics/actions/runs/36832945629)。
- [部署程式提交的成功 CI](https://github.com/sunhua12/000-trade-analytics/actions/runs/36834988698)。

載入核心新增離線案例，驗證首次交易載入、同 revision 重跑不寫入、checksum／舊 revision／快照衝突、提交後查核不符、query 回報不明及 fixture 演練限制；不是只以程式碼字串比對拉高 coverage。部署 plan guard 的負面案例確認其他資源、替換／刪除、timeout 改動、不同 digest 或未知配置都被拒絕。

## 2. Bootstrap 與受限身分

原帳號沒有 GitHub OIDC provider。本次以既有授權 AWS `hua` profile 執行 bootstrap，新增 provider、部署角色與 inline policy，共 3 個資源；既有 state bucket 未更動或重建。隨後只更新角色 trust 與必要唯讀政策。

此 repository 的 OIDC API 回傳 `use_immutable_subject=true`，實際 prefix 為 `repo:sunhua12@102355763/000-trade-analytics@1349279018`。AWS 以 `StringEquals` 限定上述 prefix 的 `feature/ci-oidc-deployment` branch 與 `aud=sts.amazonaws.com`；沒有任意 repository／branch wildcard。角色 session 最長 1 小時。

角色只可推送指定 ECR repository、更新指定 Lambda code、refresh 既有 application 資源，以及讀寫指定 application state／lockfile。無 bootstrap state 存取或部署角色管理權。`iam:PassRole` 限定 Lambda execution role 與 Lambda service。IAM 模擬確認指定 Lambda code 更新為 allowed，修改部署角色 trust 與讀取 bootstrap state 為 implicitDeny；模擬不代替真實 OIDC 部署。

GitHub repository secret 清單只有 `AWS_APPLICATION_TFVARS_JSON`，保存 application 設定；未建立靜態 AWS Access Key secrets。OIDC trust 證據見 [trust](evidence/day17/aws/oidc-trust.json)，權限模擬見 [simulation](evidence/day17/aws/role-simulation.json)。

## 3. 真實 AWS 部署與排障

[中間部署 run](https://github.com/sunhua12/000-trade-analytics/actions/runs/36832946098)先因 trust 更新尚未生效而憑證交換失敗；重跑後成功取得 OIDC 身分並推送 ECR，Terraform refresh 因指定 raw bucket 的 GetBucketPolicy 與 Logs tag ARN 權限不足而失敗，apply 未執行。

依 provider 的 [bucket read 原始碼](https://github.com/hashicorp/terraform-provider-aws/blob/v6.64.0/internal/service/s3/bucket.go)補齊指定 bucket 設定的唯讀 API，Logs 同時允許該 Log Group 的兩種 ARN 形式。沒有加入 administrator 或 raw 物件寫入權限。

[中間 image-only plan run](https://github.com/sunhua12/000-trade-analytics/actions/runs/36834452066)已成功 refresh 與產生純映像 plan，但 guard 把巢狀 `false` 結構誤認為未知配置，apply 被阻擋。修正為逐一檢查未知 leaf，增加已知／未知巢狀結構回歸案例，仍拒絕真實未知配置。

最終 [OIDC Lambda 部署](https://github.com/sunhua12/000-trade-analytics/actions/runs/36834989026)第一次因 Docker job 的 PyPI 下載逾時停止；只重跑失敗 job 與相依部署後，全部成功。這些重跑沒有放寬 CI 或 plan guard。

| 項目 | 真實結果 |
|---|---|
| 部署提交 | `ef3fb618868178cf3df07743b4aa7f97c0fd3d8a` |
| OIDC 角色 | `arn:aws:iam::816079797958:role/trade-analytics-github-deploy` |
| ECR／Lambda digest | `sha256:befb469c96c356b086152b6fd5d68b3679bacc950b84ee4fe238016b68154a09` |
| Plan／apply | 0 add、1 update、0 destroy；只更新 `aws_lambda_function.ingestion` 的 image，使用同一份 saved plan apply |
| Lambda | `State=Active`、`LastUpdateStatus=Successful`；獨立 AWS 查核的 resolved digest 與 workflow 一致 |
| Drift | 部署 job 的 application plan exit code 0；本機 bootstrap／application 的最終獨立 plan 亦確認無差異 |
| 證據 | [plan 摘要](evidence/day17/aws/deployment-summary.json)、[部署核對](evidence/day17/aws/deployment-verification.json)、[獨立 Lambda 查核](evidence/day17/aws/lambda-verification.json)、[workflow run](evidence/day17/aws/deployment-run.json) |

`AWS_AUTO_DEPLOY_ENABLED` 已設回 `false`，關閉這次 feature 分支的自動部署；預設日常部署採手動入口。PR 尚未合併，不宣稱 main 已有手動 dispatch 或部署授權；合併後需同步修改 trust branch 與 GitHub ref 設定。舊 digest `sha256:93b903a9eab711734abd1a66615bd6cb34200e948e98945c59d5d977fa955eb6` 留作回復參考，真實回復演練未在本日執行。

## 4. 真實 dbt 雲端測試

手動入口 `scripts/test_dbt_cloud.py` 使用 ADC，於新建 Dataset `trade_ci_oidc_20261001_v1` 執行 seed → run --empty → build。模型只寫隔離 Dataset，來源 `trade_raw` 唯讀；publication audit 關閉，不執行資料發布。

| 項目 | 結果 |
|---|---|
| Project／location | `trade-analytics-508604`／`asia-northeast1` |
| Build 結果 | 88 項全部通過：10 models、2 seeds、71 data tests、5 unit tests |
| 查詢限制 | 每 query 最大 1 GB、2 threads、180 秒 timeout；不是整輪費用上限 |
| Jobs／處理量 | 摘要列出測試時間窗內目前 ADC 使用者的 105 個 query jobs，billed bytes 合計 985,661,440；可能包含同時執行查詢 |
| 保留 | 測試表預設 24 小時到期；Dataset 本身保留，清理方式見手冊 |
| Artifacts | [summary](evidence/day17/dbt/summary.json)、[run_results](evidence/day17/dbt/run_results.json)、[manifest](evidence/day17/dbt/manifest.json)、[build log](evidence/day17/dbt/build.log) |

沒有 GCP JSON key，沒有以 AWS OIDC 代替 GCP 認證；dbt unit tests 是真實 warehouse 執行，不屬離線 CI。雲端實際帳單費用未提供。

## 5. 範圍與後續

本次由 AI 協助實作與驗證，未測驗本人對 trust、saved plan、digest 或依賴隔離的理解。正式 monthly DAG 保持暫停；剩餘積欠、Day 15 的 SNS email 實收、Day 18 Cloud Run，以及 Day 19 乾淨重建／真實回復演練仍分別追蹤。
