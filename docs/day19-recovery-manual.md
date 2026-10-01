# Day 19：重建、故障追查與版本復原手冊

本手冊沿用 [AWS Terraform 流程](../infrastructure/aws/README.md)、[OIDC 部署](day17-cicd-manual.md)、[Airflow backfill](day16-backfill-manual.md)及 [Cloud Run 部署](day18-cloud-run-manual.md)。實際驗收見 [執行紀錄](day19-run-record.md)。

## 1. 乾淨來源與安裝

以明確提交建立新的 checkout 或 `git archive` 解開目錄；不複製 `.venv`、`.terraform`、ADC、`.env`、state 或 plan。工具版本為 Python 3.11、Terraform 1.16.2、AWS provider 6.64.0；Airflow／dbt 版本由 `Dockerfile.airflow` 固定。授權透過既有登入重新提供，不打包憑證。

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev,warehouse,dashboard]'
PATH="$PWD/.venv/bin:$PATH" bash scripts/ci_checks.sh
docker buildx build --platform linux/amd64 --provenance=false --load -t trade-rebuild:lambda .
docker build --platform linux/amd64 --provenance=false -f Dockerfile.dashboard -t trade-rebuild:dashboard .
bash scripts/check_dashboard_container.sh trade-rebuild:dashboard
docker build -f Dockerfile.airflow -t trade-rebuild:airflow .
docker run --rm -v "$PWD:/opt/trade-analytics:ro" -e AIRFLOW__CORE__LOAD_EXAMPLES=False \
  apache/airflow:3.3.2-python3.11 \
  python /opt/trade-analytics/scripts/check_dags.py /opt/trade-analytics/dags
```

先等 build 成功才做 smoke。本次依賴在宣告範圍內重新解析，使用快取不等於複製舊虛擬環境；不宣稱未鎖定套件或 image 能逐 byte 重現。

## 2. 隔離 AWS application 重建

[重建設定快照](evidence/day19/rebuild-config/)只包含 Terraform 原始設定、provider lock、非敏感變數及獨立 backend key，沒有 state／plan／credential。快照保留回復後的舊 digest；重新演練前要換唯一命名、state key 與已存在於新 repository 的 digest。

1. 由 `infrastructure/aws/application/` 複製 `.tf` 與 lock file 到空目錄；新環境不複製 `imports.tf`。正式環境不能照此移除 import 或防刪設定。
2. 指定隔離 bucket、ECR、Lambda、execution role、raw prefix 及獨立 state key。既有 bootstrap state bucket／帳號 OIDC provider 共用，不能宣稱它們重新建立。
3. `init -backend-config=backend.hcl -lockfile=readonly`；首次僅規劃／建立 `aws_ecr_repository.ingestion`，之後完成 image push、取得 digest，再規劃完整 application。日常部署不用 `-target`。
4. 本次隔離 Alarm 名稱採 `trade-analytics-ingestion-rebuild-*`，actions 指向既有正式 SNS topic，符合既有 topic policy；Metric 的 FunctionName／namespace 仍指向隔離函數。隔離自有 topic 亦建立，但未另設收件訂閱。
5. 檢視 saved plan 的名稱、ARN、actions，確認只新建隔離資源；apply 同一份 plan。完整 state、plan 不提交 Git。
6. 核對函數 Active、resolved digest、handler smoke，再執行 `plan -detailed-exitcode`，exit code 0 才算無 drift。

帳號配額若不允許 reserved concurrency，隔離函數可用 `-1`，維持無排程、手動串行呼叫。Apply 部分失敗時先查 state／真實函數狀態；本次函數已 Active，只有 concurrency 設定失敗，查核後 untaint 接續建立缺少的 Alarms，不刪除重建正式資源。

## 3. SNS 訂閱與 OIDC 同步

收件 endpoint 由敏感變數 `alarm_email_endpoint` 提供，存在未追蹤 `.auto.tfvars` 與 GitHub 既有 `AWS_APPLICATION_TFVARS_JSON` secret；不寫入手冊或 Git。收件者完成確認後，查 subscription ARN，不能只檢查 Terraform apply 成功。

新 subscription 納入 state 後，日常 OIDC 角色需對指定 SNS topic 具 `sns:GetSubscriptionAttributes`，供 Terraform refresh；不授予訂閱修改或發信權限。Bootstrap plan／apply 管理此唯讀權限。

目前精確 trust／`AWS_DEPLOY_REF` 已同步為 `main`，immutable repository subject 與 `aud` 限制保留，`AWS_AUTO_DEPLOY_ENABLED=false`。原 Day 17 手冊的 feature 分支設定是歷史值。現行執行入口：

```bash
gh workflow run ci.yml --ref main
gh workflow run deploy-aws.yml --ref main -f apply=true
```

部署前同步現行 application 設定，包含已確認的 SNS endpoint；否則 image-only guard 可能因刪訂閱計畫拒絕部署。正式部署後更新本機未追蹤 tfvars 的 digest，獨立核對 application／bootstrap 無 drift。

## 4. 真實 handler 故障、通知與復原

只在隔離 Lambda 將 `COMTRADE_BASE_URL` 設為不回傳 Comtrade JSON 的 `https://example.com`，透過 Terraform saved plan 管理。使用下列事件呼叫隔離函數，正式函數不得改錯誤來源。

```json
{"action":"ingest","period":"202504","query_type":"partner_detail","run_id":"rebuild-recovery-20261002","revision":1}
```

保存 invocation response 與 Log Tail，確認真實 `ComtradeResponseError`、request ID／run ID，並核對沒有寫入 S3。等待 metric 使分類 Alarm／Errors 真正進入 ALARM；保存 history、SNS action 及收件者回報的台北時間，不用 `set-alarm-state` 或手動 SNS publish 冒充。

定位順序：通知 Alarm 名稱／時間 → 對應隔離 FunctionName → CloudWatch `ingestion_failed` → `aws_request_id`／`run_id` → invocation／manifest／Airflow／品質紀錄。原生通知沒有 run ID；本次 Lambda 故障與 BigQuery gate 案例分開，不冒稱同一 Airflow 事故。

以 Terraform 移除錯誤 base URL，回到官方來源；同事件應先 `success`，再 `already_exists`，兩次 row count／checksum／URI 相同。確認 S3 物件與 manifest，復原不另增 revision 或覆寫正式資料。

## 5. 品質失敗與正式安全重跑

```bash
.venv/bin/python scripts/verify_day10.py --transactions-only --tag rebuild_acceptance
```

這個入口使用真實 BigQuery 與 Publisher，但輸入是合成 fixture；只寫入命名含 `rebuild_acceptance` 的隔離 Dataset。驗證 FAIL 不發布、修正後成功、凍結候選不可竄改、交易回滾與重跑保真。輸出原先落在 `docs/evidence/day10/rebuild_acceptance/`，本日交付集中至 `docs/evidence/day19/quality-fixture/`。

正式單月重跑沿用 Day 18 的 `202504` 原發布 ID。先以 `scripts/verify_day16.py 202504 202504` 保存基準，再執行既有 `airflow dags test trade_backfill_pipeline`（conf 見 Day 18 手冊）；重跑後比對 raw grain／金額、正式筆數、run ID 與 `published_at`，忽略新 query job ID。最新品質 attempt 時間可以更新，成功發布時間應不變。

## 6. 版本回復與清理

Lambda：將舊已驗證 image 完整拉取／推送隔離 ECR，再以舊 digest 產生 image-only saved plan、apply，核對 resolved digest、同事件 `already_exists` 及無 drift。只複製 image manifest 可能因隔離 repository 缺 layers 而失敗。

Cloud Run：保存原 revision／digest，新 revision 先 0％ 流量，再切 100％ 驗證 UI。直接切回原 revision 時本次實際遇到 429／無可用 instance；暫時調整 service max／min 未解決，最終重新部署原 digest 至 `trade-dashboard-recovered-original`，**再明確執行 update-traffic 指向新 revision** 才恢復。先前的固定 revision 流量配置不一定因 deploy 自動切到最新版本；不可只讀 deploy 成功訊息。

恢復後重新操作原 Live URL、核對固定 SQL／單月金額與設定，服務最小 instances 0、service／revision 最大 instances 1。原 revision 直接回切在本次環境未通過，已驗證復原入口是舊 digest 重新部署；這不撤銷已發布資料。

清理前保存證據，僅在隔離 Terraform 副本移除防刪、設定 bucket `force_destroy=true`／ECR `force_delete=true`，先 apply 兩個旗標，再產生／檢視 destroy saved plan。正式原始碼的防刪設定維持不變。本次 21 個隔離 AWS 資源全刪，兩個 BigQuery fixture Dataset 刪除；remote state key 的空 state 保留於共用 backend。GCP 無流量 revisions／映像保留作版本證據，min 0 不代表 registry 儲存免費。
