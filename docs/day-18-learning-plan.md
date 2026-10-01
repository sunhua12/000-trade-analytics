# Day 18：Cloud Run 展示部署、唯讀身分與正常路徑 E2E

| 項目 | 內容 |
|---|---|
| 對應計畫 | [20 天實作規格](trade-analytics-spec.md)的 Day 18；建立 M5 所需的 Live Demo 與正常路徑整合證據 |
| 前置成果 | [Day 13](day13-dashboard-record.md)已完成本機 Dashboard 與固定條件核對；[Day 16](day16-run-record.md)已完成 M4；[Day 17](day17-run-record.md)已完成 CI、AWS OIDC 部署及隔離 dbt 測試 |
| 預計投入 | 約 7～9 小時；雲端建置、部署、查詢及排障等待另記 |
| 核心目標 | 將既有 Streamlit 部署到 Cloud Run，以專用 Service Account 唯讀正式資料，限制查詢與服務規模，並保存線上核對及單月正常路徑 E2E 證據 |
| 今日交付物 | Dashboard 容器、可重做部署入口、最小權限身分、Live URL、查詢成本設定、線上核對與 E2E 紀錄、操作手冊及學習日誌 |
| 目前狀態 | 技術驗收完成；Cloud Run、線上固定條件核對及單月安全重跑通過，詳見[執行紀錄](day18-run-record.md) |

MVP 維持美國月度進口、`8542／H6`，Dashboard 只讀已發布 mart 與品質摘要。現有入口為 `dashboard.py`；[查詢程式](../src/trade_analytics/dashboard/queries.py)目前將展示範圍固定為 `202301～202412`，不能因 Day 16 已發布較新月份就宣稱線上會自動顯示。正式 monthly DAG 的積欠與暫停政策沿用既有紀錄；SNS 實收、故障復原及乾淨重建於 Day 19 接續驗收。

## 1. 確認部署與展示契約

**預計時間：35～45 分鐘。**

- [x] 核對實際 GCP project、BigQuery location、正式 Dataset、可用 Cloud Run region、Artifact Registry repository 及服務名稱；沿用既有環境，不將本機 ADC 身分當成線上執行身分。
- [x] 盤點 `dashboard.py`、`.[dashboard]` 依賴、查詢允許清單、快取與錯誤處理；Dashboard image 與 Lambda／Airflow image 分開。
- [x] 明列歷史展示範圍及 E2E 驗收月份。如果 E2E 月份超出現有日期邊界，先將範圍改成可驗證的設定或由正式發布月份取得，保留月份分區條件與查詢上限，補上邊界驗證。
- [x] 定義 Live Demo 存取方式：公開展示僅暴露正式彙總資料；若環境政策要求登入，記錄可操作的授權方式，不能將登入拒絕頁當成可展示成果。
- [x] 從既有預算紀錄取得可接受費用與限制；記錄尚缺設定，不代填個人預算或帳單。

Day 17 的 GCP 隔離測試使用本機 ADC，未建立 GitHub GCP WIF。今天採可重做的 GCP 部署指令即可，不以 AWS OIDC 成功推定已有 GCP 自動部署身分。

## 2. 建立 Dashboard 容器並驗證本機啟動

**預計時間：70～90 分鐘。**

- [x] 新增專用 Dashboard Dockerfile，使用 Python 3.11 與既有 Dashboard 依賴，明確複製入口及 package；建置內容排除 ADC、JSON key、`.env`、本機虛擬環境、Terraform state／plan 與證據資料。
- [x] 啟動 Streamlit 時綁定 `0.0.0.0`，從環境變數 `PORT` 取得監聽埠；確認啟動命令確實展開變數，不能將字串 `$PORT` 原樣傳入。
- [x] 驗證容器啟動、健康檢查、頁面載入及關閉；本機真實查詢若需要 ADC，僅以執行時唯讀掛載或既有授權方式提供，不打包進 image。
- [x] 沿用必要 CI 檢查，新增本次啟動／日期範圍改動所需驗證；雲端權限不足、空結果或查詢失敗時，畫面呈現明確狀態。
- [x] 建置並推送 Artifact Registry，以 Git SHA 標記並取得實際 image digest；保存建置提交、命令與結果。

## 3. 配置專用身分、查詢與服務限制

**預計時間：60～80 分鐘。**

- [x] 建立或引用專用 Cloud Run runtime Service Account，與部署身分分離；runtime 僅具執行 BigQuery query jobs 的必要專案權限，以及 `trade_analytics_published` 的唯讀權限。
- [x] 核對有效 IAM 權限，確認 runtime 無 raw／candidate 讀寫或正式資料寫入權；如有專案層繼承權限，記錄並處理，不能只看新增的 Dataset binding。
- [x] Cloud Run 使用綁定身分的 ADC；不設定 JSON key，不在 image、Git 或日誌保存憑證。
- [x] 注入 `TRADE_BQ_PROJECT`、`TRADE_BQ_LOCATION`、`TRADE_BQ_MAX_BYTES_BILLED`、`TRADE_DASHBOARD_CACHE_TTL`；沿用每 query 預設 1 GB 與快取 3600 秒，調整時記錄理由。
- [x] 設定 `min-instances=0`、明確最大 instances、CPU／memory、concurrency 與 request timeout，記錄實際值及展示負載下的觀察；確認 Streamlit 互動與長連線可用。
- [x] 檢查預算通知與停止服務入口；最大 instances、單次查詢上限及快取均不等於整體費用硬上限，多個 instances 的快取也不能假設共用。

| 邊界 | 驗證重點 |
|---|---|
| 資料存取 | 僅查正式 mart 與品質摘要，不讓訪客提交任意 SQL 或 table 名稱 |
| 查詢成本 | 參數化 SQL、月份分區條件、每 query bytes 上限、有限日期／Top N 與快取 |
| 容器規模 | 零最小 instances、明確最大 instances、合理 concurrency 與資源配置 |
| 展示資訊 | 缺值、新鮮度、HHI 可用性及品質狀態維持原契約 |

## 4. 部署 Cloud Run 並保存可回復版本

**預計時間：60～80 分鐘，加上雲端等待。**

- [x] 建立可重做的部署腳本或指令清單，區分首次 API／registry／IAM 前置設定與日常 revision 更新；GCP IaC 依總規格延後。
- [x] 以不可變 image digest 部署，指定 runtime 身分、region、環境變數與服務限制；公開展示時明確設定 invoker 存取，保存實際採用的模式。
- [x] 取得服務 URL、revision、image digest 與流量設定，核對 Git SHA → image → revision 的對應。
- [x] 從線上 URL 驗證冷啟動、頁面載入、篩選切換、重新讀取、圖表互動與錯誤訊息；HTTP 成功回應不能取代 Dashboard 操作驗證。
- [x] 查閱部署及執行日誌，確認無 credential 輸出；保存去敏的設定與錯誤處置。記錄回復舊 revision／digest、停止展示及清理順序，實際回復演練留待 Day 19。

## 5. 線上固定條件核對與正常路徑 E2E

**預計時間：140～180 分鐘，加上真實雲端執行等待。**

先用已發布歷史資料完成 Live Demo 核對，再選一個兩類來源均可用的月份驗證完整單月管線。先查發布狀態、revision 與既有 `run_id`：已發布月份遵守原 ID 安全重跑政策；尚未發布月份採既有手動流程，不能為了展示繞過 gate 或覆寫正式版本。積欠未解決時保持 monthly DAG 暫停。

- [x] 固定歷史條件，例如 `202401～202412／8542／H6／partner 458`，以獨立 BigQuery SQL 比對線上月度金額、World、排名與 YoY；保存 SQL、job ID、畫面條件、數值、驗證時間與處理量。
- [x] 以格式化前的 `NUMERIC` 金額與比率核對，浮點圖表採明列容差；檢查特殊代碼 490 排除、缺去年基期、HHI 不可用及空結果，不能以 0 代替缺值。
- [x] 選定 E2E 月份，保存執行前正式版本與 raw grain 基準；透過既有 DAG／單月入口完成兩類 ingest → S3 manifest → BigQuery load → attest → dbt build／audit → gate → publish。
- [x] 保存同一月份的 Airflow run／task、Lambda／S3 manifest、revision／checksum、BigQuery job、品質 audit 與 `published_run_id`；品質 FAIL 時記錄未通過，不以手動資料發布補成成功。
- [x] 清除或等待線上快取，再用包含該月份的篩選核對正式 mart 與 Cloud Run 畫面；確認最新月份、成功發布時間、品質嘗試時間與畫面讀取時間分開呈現。
- [x] 確認 Dashboard runtime 唯讀，E2E 寫入由原 pipeline 身分執行；重跑既有月份的證據標記為安全重跑，不宣稱新增發布。

若只能完成歷史線上核對，則 Live Demo 可記為完成，但正常路徑 E2E 保留未完成及原因。Fixture 僅補真實資料沒有覆蓋的 UI 反例，不能取代完整雲端鏈。

## 6. 交付紀錄與學習檢查

**預計時間：35～45 分鐘。**

| 交付物 | 最少內容 |
|---|---|
| Dashboard 容器與部署入口 | Dockerfile、建置／推送／部署命令、PORT 契約及必要 CI 驗證 |
| 身分與成本設定 | Runtime／部署身分分工、有效 IAM 權限、環境變數、服務規模及查詢限制 |
| Live Demo 證據 | URL、Git SHA、digest、region、revision、線上操作及固定 SQL 比對 |
| 正常路徑 E2E 證據 | 月份、run ID、來源配對、load／品質／發布紀錄與線上結果 |
| 操作手冊與執行紀錄 | 建議新增 `docs/day18-cloud-run-manual.md`、`docs/day18-run-record.md`；證據放 `docs/evidence/day18/`，包含回復、停止／清理及未完成項 |
| [學習日誌](learning-log.md) | 實際日期、本人投入時間、部署決策、驗收結果及未解問題；未提供的工時與帳單不代填 |

完成後用自己的話回答：

1. 本機 ADC、部署身分與 Cloud Run runtime Service Account 各負責什麼？為什麼 runtime 不需要 JSON key？
2. BigQuery query job 權限與 Dataset 唯讀權限有何差異？如何核對繼承權限？
3. 每 query bytes 上限、快取與最大 instances 分別限制什麼？為什麼仍不能保證總費用上限？
4. 為什麼 Live URL 能開啟，仍需要固定 SQL 核對與完整單月 E2E？
5. 資料已發布但線上仍顯示舊月份時，如何依序檢查日期邊界、快取、revision 與正式發布紀錄？

- [x] Live URL 可實際操作，部署提交、image digest 與 revision 可追溯。
- [x] Runtime 使用專用身分，只讀正式資料；服務規模、查詢限制及停止方式有紀錄。
- [x] 固定條件線上圖表與獨立 BigQuery 查詢一致，缺值與資料新鮮度呈現正確。
- [x] 單月正常路徑 E2E 有完整真實證據，正式發布結果能在線上查到。
- [x] 操作手冊、執行紀錄與學習日誌完成，證據齊全後才勾選總規格的 Day 18；M5 保留至 Day 20 驗收。

本人實際工時、雲端帳單與個人理解檢查未提供；預算通知設定已查核，通知 email 實收未驗證。單月 E2E 採既有來源與原發布 ID 安全重跑，未新增 API 擷取或發布。

Day 19 接續乾淨重建與失敗 → SNS 實收 → run ID 追查 → 重跑復原；不以本日正常路徑成功推定故障、回復或通知鏈已通過。
