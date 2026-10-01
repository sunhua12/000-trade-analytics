# Day 18：Cloud Run 展示與正常路徑 E2E 執行紀錄

| 項目 | 紀錄 |
|---|---|
| 實作／驗收日期 | 2026-10-01～2026-10-02（Asia/Taipei）；管線重跑於 10 月 1 日，線上年度核對與預算於 10 月 2 日補齊 |
| 分支 | `feature/cloud-run-dashboard` |
| 狀態 | Cloud Run Live Demo、唯讀身分、固定 SQL／線上核對、單月正常路徑安全重跑與預算設定通過 |
| 本人實際學習工時／實際帳單 | 未提供，不以助理操作時間或 bytes 代填 |
| 操作入口 | [Cloud Run 手冊](day18-cloud-run-manual.md)、[學習計畫](day-18-learning-plan.md) |

## 1. 真實部署

[Live Demo](https://trade-dashboard-898093147725.asia-northeast1.run.app) 已公開可操作。首次啟用 Cloud Run、Artifact Registry 與 IAM API，建立專用 registry／runtime；沒有改動既有 AWS Terraform 或 Airflow 排程。

| 欄位 | 結果 |
|---|---|
| Project／region／service | `trade-analytics-508604`／`asia-northeast1`／`trade-dashboard` |
| Revision／流量 | `trade-dashboard-00001-glf`／100％ |
| Image digest | `sha256:bf659188d8f1c4a7bc4cf910bb48e1d72db2c43d4a9610e2183846b40d9b2819` |
| Base Git SHA | `c684f58436983309e455e789cb62825447d7a47e`；部署含未提交的本日修改，不宣稱此 SHA 單獨代表完整部署來源 |
| 容器來源 hash | `b1b20f129537d714`；[完整來源清單](evidence/day18/build-source-manifest.json)與目前容器來源檔一致 |
| 規模 | 最小 instances 0、service／revision 最大 instances 1、1 CPU／1 GiB、concurrency 10、timeout 3600 秒 |
| 容器 | Python 3.11、`linux/amd64`、非 root UID 10001；自訂 `PORT=8090` 健康檢查通過 |
| 證據 | [部署 log](evidence/day18/deployment.log)、[首次設定](evidence/day18/service.json)、[目前設定](evidence/day18/service-current.json)、[公開 invoker](evidence/day18/service-iam.json)、[container smoke](evidence/day18/container-smoke.log) |

本機 Dashboard 保留 `202301～202412` 的預設展示契約；Cloud Run 明確設定日期上界 `2025-05-01`（不含），故可查 `202301～202504` 的 28 個已發布月份。新日期設定驗證完整月份、先後順序及最多 60 個月，所有 query 保留參數與分區條件；新邊界測試確認 202504 可查、202505 在查詢前被拒絕。

## 2. Runtime 權限與查詢量

`trade-dashboard-runtime@trade-analytics-508604.iam.gserviceaccount.com` 只有 project `roles/bigquery.jobUser` 與 published Dataset `READER`。Project ancestor 只回傳 project，沒有 organization／folder；project IAM 沒有授予此 runtime viewer／editor，raw 與 candidate ACL 也沒有授權。BigQuery／registry 沒有 `allUsers` binding；公開 invoker 僅授予 Cloud Run 服務。權限依據為 [project IAM](evidence/day18/project-iam.json)、[ancestors](evidence/day18/project-ancestors.json)與 [Dataset ACL](evidence/day18/dataset-access.json)，未以真實資料寫入做負面測試。

Runtime ADC 由 Cloud Run 綁定身分提供，image 不帶 JSON key、ADC 或 `.env`。實際 [runtime query jobs](evidence/day18/runtime-query-jobs.json) 的 `user_email` 與專用身分相符；10 月 1 日保存的 41 個 jobs 合計 billed bytes 461,373,440，僅為當時查核時間窗，不代表整日費用或最終帳單。每 query 上限 1 GB，快取 3600 秒。

## 3. 線上與獨立 SQL 核對

[驗證腳本](../scripts/verify_day18.py)比對獨立月度 SQL 與 Dashboard query，並以真實 BigQuery 資料執行本機 AppTest，無 UI exception。線上另外以瀏覽器操作日期／Partner、檢查圖表與表格，保存 [年度畫面文字](evidence/day18/live-historical.txt)、[年度截圖](evidence/day18/live-historical.png)、[單月文字](evidence/day18/live-april.txt)與 [單月截圖](evidence/day18/live-april.png)。

| 固定條件 | 獨立查詢與線上結果 |
|---|---|
| `202401～202412／8542／H6／partner 458` | World 合計 USD 40,386,451,682；Malaysia 合計 USD 9,598,343,899，占比 23.77％ |
| 同條件的 12 個月 | 每月 Partner 金額、格式化 YoY、國家覆蓋率均與 SQL 一致；HHI 顯示不足及 `insufficient_coverage`，不補 0 |
| `202504／全部國家` | World USD 3,114,414,147；只列 1 個月份，HHI 不可用、品質 PASS，成功發布與最新嘗試時間分開 |
| 快取重新讀取 | 按鈕可清除快取並重新取得相同正式數值，不改動發布資料 |

完整 query／job／處理量見 [SQL 與 AppTest 證據](evidence/day18/query-ui-verification.json)、[年度參考查詢](evidence/day18/live-reference.json)與 [線上數值比較](evidence/day18/live-comparison.json)。金額以 `NUMERIC` 原值核對，線上百分比依兩位小數格式比較；月度圖表中的整數金額與查詢一致。空結果、缺基期與 query 錯誤仍由既有隔離測試覆蓋，本日未刻意破壞正式服務權限或資料。

## 4. 單月正常路徑 E2E

選用原本已成功發布的 `202504`，保存 [執行前基準](evidence/day18/e2e-before.json)，沿用 `backfill-202504-32a1f3080f769f4e`。Airflow run `manual__2026-10-01T08:57:05.730081+00:00` 於台北時間 16:57～16:58 成功，兩種類型來源查核 → raw load → attest → dbt build／audit → gate → publish 完整通過；後續 Cloud Run 單月畫面與正式資料一致。

| 步驟 | 真實結果 |
|---|---|
| Ingest | 核對既有 S3 data／manifest、revision 1、checksum；兩類回傳 `already_exists` |
| Load | 明細 61 筆、World 1 筆；checksum 核對後均 `already_loaded`，沿用已成功 load job |
| Attest／build | 兩類來源 verified；dbt build 成功，未繞過品質檢查 |
| Audit／gate | PASS、無 reason code |
| Publish | `already_published`，未以新 ID 替換正式版本 |
| 重跑後比較 | 明細／World raw grain、金額、正式 61 筆、發布 run ID 及 `published_at=2026-10-01 02:36:29.695+00` 全部不變 |
| 線上顯示 | 202504 的 World 金額與 BigQuery 一致；runtime 保持唯讀 |

本次是已發布月份的真實正常路徑安全重跑，沒有新增 Comtrade API 擷取、Lambda invocation 或正式發布；最初來源擷取證據接續 [Day 16 紀錄](day16-run-record.md)。不把既有來源復用說成 fresh ingestion，也不將 UI fixture 當雲端成功。

[步驟摘要](evidence/day18/e2e-steps.json)保存 S3 URI／checksum、load／attest／audit／publish job ID；[Airflow log](evidence/day18/e2e-airflow.log)、[task 狀態](evidence/day18/e2e-task-states.json)、[重跑後查核](evidence/day18/e2e-after.json)及 [基準比較](evidence/day18/e2e-comparison.json)可追查整條流程。Monthly DAG 仍 [暫停](evidence/day18/monthly-dag.json)，未清空其餘積欠。

## 5. 預算與程式驗證

使用者指定 USD 10／月，並因 TWD 帳單另指定通知額度 TWD 250／月。已建立專案限定、月曆月、排除 credits 的 Budget，50％／90％／100％ actual 與 100％ forecasted 門檻採預設 billing IAM recipients。見 [建立結果](evidence/day18/budget-created.json)與 [獨立查核](evidence/day18/budget-verified.json)。此設定不會硬性停止服務，未刻意超額觸發 email；通知實收不宣稱已驗證。

[本機 CI](evidence/day18/local-ci.log)：255 tests passed，整體 coverage 91.66％、ingestion 97.03％、raw loader 96.52％；Ruff format／lint、strict mypy 通過。Dashboard 容器建置／自訂 PORT smoke 成功，CI workflow 新增同一建置與 smoke job。本日沒有 push 或 GitHub run，不能將本機成功寫成遠端 CI 成功。

## 6. 後續邊界

Day 18 技術驗收完成。本人學習工時與理解檢查未提供；實際雲端帳單未提供。Day 19 接續乾淨重建、真實回復與含 SNS 實收的故障演練；正式 monthly DAG 仍暫停，剩餘積欠另批處理。M5 留待 Day 20，未追加 GCP Terraform、WIF、自訂網域或新圖表。
