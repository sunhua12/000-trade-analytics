# Day 19：乾淨重建、告警實收與復原執行紀錄

| 項目 | 結果 |
|---|---|
| 驗收日期 | 2026-10-02（Asia/Taipei）；雲端證據使用 UTC |
| 分支 | `feature/rebuild-alert-recovery` |
| 重建來源 | `ff59ba5296eb02f29214980a8d6fdd80bd832ed9`；完整已提交來源，以 git archive 解開新目錄 |
| 狀態 | AWS 重建／SNS 實收／修正重跑／品質 gate／正式安全重跑／Lambda digest 回復完成；Cloud Run 採舊 digest 新 revision 復原，直接舊 revision 回切失敗如實保留 |
| 本人實際工時／實際帳單 | 未提供，不以助理操作時間或處理量代填 |
| 手冊 | [重建與復原手冊](day19-recovery-manual.md) |

## 1. 乾淨環境與 AWS 重建

新的 Python 3.11 虛擬環境依 `pyproject.toml` 安裝 `.[dev,warehouse,dashboard]`，未複製原虛擬環境、credential 或 Terraform cache。Ruff format／lint、strict mypy 通過，255 項測試全通過；coverage 91.66％、ingestion 97.03％、raw loader 96.52％，見 [clean CI](evidence/day19/clean-ci.log)。兩條 DAG 真實匯入，各 31 tasks；Lambda／Dashboard 容器從乾淨來源建置，Dashboard 自訂 PORT／UID smoke 通過。第一次 smoke 早於 build 完成而失敗，建置完成後成功，兩份日誌皆保留。

[真實 GitHub CI](https://github.com/sunhua12/000-trade-analytics/actions/runs/36900122256)對同一提交成功，沒有將本機結果代替遠端結果。

隔離 AWS 使用 `trade-rebuild-acceptance` 函數／ECR／execution role、新 bucket `trade-rebuild-816079797958-20261002`、`acceptance` prefix 與獨立 remote state key。先新建 ECR，再以重建 digest `sha256:3855f0da15fdeb154e7dfe34160e0cf95a9d718b3c5d426b7a1a43bec377687d` 建立完整 application；共 21 個資源。原 bootstrap state bucket／帳號 OIDC provider 共用，未重新建立，正式資料未搬入隔離 bucket。

首次 apply 因帳號 reserved concurrency 配額失敗。查核隔離函數已 Active／Successful 後取消保留額度、解除 taint，接續建立兩個缺少的 Alarms，沒有重建正式函數；[後續 plan 無 drift](evidence/day19/isolation-no-drift.log)。[設定快照](evidence/day19/rebuild-config/)可重現隔離拓樸，state／完整 plan 未提交。

## 2. SNS 真實實收與同一 run ID 復原

正式 SNS topic 原無 subscription。本次 Terraform 僅新增 1 個 email 訂閱；使用者點擊確認信，獨立查核 subscription 已啟用。Endpoint 僅存未追蹤敏感變數／既有 GitHub secret，證據去敏。

隔離函數設定錯誤 base URL，真實 handler 於解析來源時產生 `ComtradeResponseError`；run ID 為 `rebuild-recovery-20261002`，request ID 為 `6dae3bff-5b2b-4e75-8ac9-142adfadfc3b`。分類與 LambdaErrors Alarm 均 ALARM，history 顯示向既有 SNS topic 成功執行動作。

**使用者回報兩封實際告警皆於台北時間 2026-10-02 01:34 收到**，精度為分鐘：[實收紀錄](evidence/day19/sns-receipt.json)。這是本人收件回報，未讀取信箱或偽造 email 截圖。[Alarm history](evidence/day19/alarm-history.json)、[run ID 日誌](evidence/day19/run-id-logs.json)與 [invocation](evidence/day19/lambda-failure.json)可串接通知與根因。

Terraform 移除錯誤來源後，同事件首次復原回傳 `success`，61 筆；再次回傳 `already_exists`，checksum 均為 `sha256:2150cde13d68f474808135e4f76e0b710dc505905ade1ec6a783548ca1c22610`，S3 URI 相同。故障發生於 S3 寫入前，復原僅寫入隔離 bucket，未新增正式 raw 或發布版本。

三類 filter 本次重新以四類樣本驗證，每個只匹配自身分類，`Other` 不匹配；實際分類通知本次限 `ComtradeResponseError`。Duration > 150000 ms 的真實 151001.93 ms 證據沿用 [Day 15](day15-run-record.md)，不宣稱本次再執行耗時 fixture。

## 3. 品質停損與正式完整重跑

[隔離品質結果](evidence/day19/quality-fixture/fixture-checkpoint.json)有 10 個真實 BigQuery／Publisher 驗收案例通過：首次 FAIL 不發布、baseline PASS、同版本冪等、交易回滾保留所有欄位、凍結候選竄改拒絕、另月發布、修訂刪列、舊 ID 重跑、缺 audit／錯 partition 拒絕與 upstream failure 留存。輸入是合成 fixture，不冒稱正式來源故障。

正式 `202504` 以原發布 ID `backfill-202504-32a1f3080f769f4e` 執行完整 backfill 單月安全重跑，Airflow run `manual__2026-10-01T17:35:49.929927+00:00` 成功，台北時間約 01:35～01:36。兩類來源查核、load、attest、dbt、audit、gate、publish 通過，publish 為 `already_published`。

[前後獨立 SQL 比較](evidence/day19/production-comparison.json)確認 raw 明細 61 筆／World 1 筆、兩者金額 USD 3,114,414,147、正式 61 筆、原 run ID 及 `published_at=2026-10-01 02:36:29.695+00` 全不變。品質最新 attempt 可更新，不代表新增發布。Monthly DAG 保持暫停。

三個案例分開解讀：Lambda 真實告警與來源復原、隔離合成品質失敗不發布、正式來源完整安全重跑；它們不是同一次端到端故障。

## 4. OIDC 部署與最小權限修正

將 bootstrap 精確 trust 與 GitHub `AWS_DEPLOY_REF` 從歷史 feature 分支同步到 `main`，仍限定 immutable repository subject／`aud`，自動部署保持關閉。

[首次 OIDC run](https://github.com/sunhua12/000-trade-analytics/actions/runs/36900524421)的前置 CI 全通過，部署在 Terraform refresh 因新 SNS subscription 缺 `sns:GetSubscriptionAttributes` 而拒絕，尚未 apply。修正 `infrastructure/aws/bootstrap/oidc.tf`，只增加既有 topic 的唯讀權限；同步現行 application 設定與 SNS endpoint 到既有 secret，未增加靜態 credential。

[修正後 OIDC run](https://github.com/sunhua12/000-trade-analytics/actions/runs/36901101994)全成功，Git SHA 對應正式 Lambda digest `sha256:eadbfd0b1599935d8aeb64db18c04ebd8b4e5be529421f0e990071c4e3f94a66`。[部署 verification](evidence/day19/deployment-verification.json)確認 digest 一致、drift false；本機 application／bootstrap 獨立 plan 亦無 drift。

## 5. Lambda 回復與 Cloud Run 實際故障

隔離 Lambda 由重建 digest 回復原已驗證 `sha256:befb469c96c356b086152b6fd5d68b3679bacc950b84ee4fe238016b68154a09`，經 Terraform image-only saved plan／apply。回復後同事件仍 `already_exists`、61 筆、checksum 不變，[後續無 drift](evidence/day19/lambda-rollback-no-drift.log)。原 image 必須完整推送隔離 ECR；僅複製 manifest 曾因缺 layers 失敗。

Cloud Run 重建 image digest `sha256:9d64a8cc9a15a43f4be5ce9fb4c28a14579fa3b8cc13727880a16e5002990277`，revision `trade-dashboard-rebuild-ff59ba5`。先 0％ 流量，再切到 100％，真實 UI 的 202504 World 金額與 SQL 一致，[畫面](evidence/day19/live-new.png)／[文字](evidence/day19/live-new.txt)已保存。

直接回切原 `trade-dashboard-00001-glf` 後，新請求出現 429／無可用 instance；暫時 service max 2、min 1 未解決，刪測試 revision 亦因為 latest revision 被 GCP 拒絕。這些嘗試不算成功。最後以原 digest `sha256:bf659188d8f1c4a7bc4cf910bb48e1d72db2c43d4a9610e2183846b40d9b2819` 建立 `trade-dashboard-recovered-original`，明確 `update-traffic` 指向該 revision 後服務恢復。

此次驗證成功的 Cloud Run 復原方式是**舊 digest 重新部署至新 revision**；不宣稱直接舊 revision 回切通過。恢復服務 min 0、service／revision max 1，runtime、日期邊界、唯讀資料及每 query 1 GB 設定沿用原值。無預算擴張，暫時預熱的實際帳單未提供。

原 [Live Demo URL](https://trade-dashboard-898093147725.asia-northeast1.run.app)恢復後重新操作起始月份至 2025-04，顯示 1 個已發布月份、World USD 3,114,414,147，與獨立 SQL 一致；[恢復畫面](evidence/day19/live-restored.png)、[文字](evidence/day19/live-restored.txt)與 [最終服務設定](evidence/day19/cloud-run-final.json)已保存。Airflow image 亦從乾淨來源建置，內部 dbt Core 1.12.5／BigQuery adapter 1.12.1 版本已查核。

## 6. 清理與驗收邊界

[AWS 清理](evidence/day19/cleanup-apply.log)：0 added、0 changed、21 destroyed，只清本次隔離函數／bucket／ECR／IAM／Logs／filters／Alarms／自有 topic。正式 SNS 訂閱保留，共用 backend 留存隔離空 state；兩個 BigQuery fixture Dataset 已刪除。GCP 無流量 revisions／映像保留作版本證據，儲存仍可能收費。

[交付前獨立查核](evidence/day19/final-audit.json)確認隔離 Lambda／ECR／S3／IAM／Alarms 已不存在，正式 SNS 訂閱仍確認、Lambda Active 且 digest 與 OIDC artifact 一致。

本日不處理剩餘積欠，不追加功能，不把故障回復當資料回滾。本人理解檢查、實際學習工時與帳單未提供；M5 留待 Day 20 文件與展示驗收。
