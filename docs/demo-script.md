# 5 分鐘展示稿與操作路線

此稿已依現有查詢／復原證據整理，可直接練習；時間欄是目標分配，並非本人計時實測。本人展示與理解確認尚待完成。

## 展示準備

開啟 [Live Demo](https://trade-dashboard-898093147725.asia-northeast1.run.app)，另開 [架構圖](architecture.md)、[分析證據](evidence/day13-verification.json)與 [復原紀錄](day19-run-record.md)。三項觀察固定 `8542／H6`，年度比較使用完整 2023／2024，不使用 2025 部分年度。現場只讀展示；故障與重跑使用歷史實測證據回放。

## 0：00～0：40：問題與成果

「這個作品分析美國半導體月度進口金額與來源國變化。我把來源擷取、原檔保存、資料建模、品質發布及展示串成可追溯流程。原始驗收涵蓋 2023～2024 連續 24 個月，之後延伸至 2025 年 4 月，目前線上共 28 個已發布月份。它分析的是進口金額，不直接代表產量或供應鏈因果。」

操作：指出月份、資料新鮮度與 published 品質摘要。

## 0：40～1：30：設計取捨

「每月分別取得國家明細與 World，保存 revision、checksum 和 manifest。Load 後先查驗來源配對，dbt 只建立候選；候選凍結並通過品質 gate 才交易式發布。FAIL 保留前一次正式版本。Airflow 使用單 slot Pool 維持單 writer，Cloud Run 身分只讀正式資料。AWS 部署透過受限 OIDC 的臨時憑證，image digest 可追到 Git SHA。」

操作：沿架構圖說明資料流，指出 gate 與唯讀邊界。補充本機 Airflow 與 GCP 手動部署是本版取捨。

## 1：30～3：10：三項有證據的觀察

| 觀察 | 固定條件與結果 | 解讀界線 |
|---|---|---|
| World 年度成長 | 2023 USD 36,062,821,301；2024 USD 40,386,451,682；年度約 +11.99％ | 每月 World 只取一次；年度比率不是月 YoY 平均 |
| 主要來源國 | 2024 Malaysia USD 9,598,343,899，在已確認國家／地區中第一 | 國家排名排除 490；不稱完整所有原碼排名 |
| 集中度不可用 | 24 月 country coverage 63.01％～82.92％，HHI 全部 insufficient_coverage | 不是 HHI＝0；不能推論低集中度，品質 PASS 與覆蓋充分不同 |

「金額成長與主要來源可以分析，但集中度必須保留限制。特殊項目仍保存並參與對帳，不能為了漂亮圖表把未知範圍假裝消失。」

操作：先選 2024-01～2024-12、全部 Partner、Top 10，指出 World 精確值與 Malaysia 第一；再選 2023-01～2024-12 查看缺基期／覆蓋提示。查詢結果與 job ID 見 [Day 13 SQL 驗證](evidence/day13-verification.json)，SQL 入口為 [verify_day13.py](../scripts/verify_day13.py)；展示用獨立查詢見 [reference.sql](evidence/day20/reference.sql)。

## 3：10～4：30：故障復原與安全重跑

「Day 19 我們在隔離 Lambda 設錯來源 URL，真實 handler 失敗觸發分類與 Errors Alarm。使用者於台北時間 10 月 2 日 01：34 回報收到兩封通知。由 Alarm 時間與函數定位日誌，查到 run ID `rebuild-recovery-20261002`。修正來源後同 run 成功取得 61 筆，再次執行回傳 already_exists，checksum 相同。」

「另外，正式 202504 用原發布 ID 完整安全重跑，明細 61 筆、World 1 筆，World 金額 USD 3,114,414,147，正式 run ID 與發布時間不變。這證明重跑沒有增加有效資料或假造新發布。它與隔離告警、合成品質 FAIL 是分開的案例。」

操作：指出 [SNS 實收](evidence/day19/sns-receipt.json)、[Lambda replay](evidence/day19/lambda-replay.json)與 [正式前後比較](evidence/day19/production-comparison.json)，不要現場觸發故障／寫入。需要補看單月畫面時，選 2025-04～2025-04。

## 4：30～5：00：限制與交付

「目前 monthly DAG 仍暫停，積欠另批處理，沒有宣稱長期全自動營運。Cloud Run 直接切回舊 revision 曾失敗，實測以舊 digest 新建 revision 復原；image 回復不是資料回滾。README、資料字典、runbook、限制與驗收索引都已整理，下一步是理解確認、積欠處理與實際費用核對。」

## 備援與理解檢查

網路失敗時使用 [歷史線上畫面](evidence/day18/live-historical.png)與 [復原畫面](evidence/day19/live-restored.png)，明說是歷史畫面而非即時數據。本人練習時記錄實際耗時與五題理解答案；問題見 [learning plan](day-20-learning-plan.md#6-學習檢查與完成條件)，不可用本稿代替理解驗收。

## 可使用的作品敘述

「建置美國半導體月度進口分析作品，完成 24 個連續月份來源查驗與發布，延伸展示至 28 月；整合 AWS Lambda／S3、BigQuery／dbt、Airflow 與 Cloud Run，實測 OIDC 部署、品質失敗不發布、故障通知復原及同月安全重跑。」

實作由 AI 協助，本人使用此句前應能說明與重現涉及的設計。不填未量測的節省成本、效能改善、長期可用率或本人投入時數。
