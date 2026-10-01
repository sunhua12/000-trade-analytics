# Day 16：參數化回填、載入復原與 M4 驗收

| 項目 | 內容 |
|---|---|
| 對應計畫 | [20 天實作規格](trade-analytics-spec.md)的 Day 16；驗收 M4「可復原的自動流程」 |
| 前置成果 | [Day 14](day14-run-record.md)已驗證 monthly DAG 的單月安全重跑；[Day 15](day15-run-record.md)已實作三期串行與告警資源，但 SNS email 訂閱及實際收件仍待完成 |
| 預計投入 | 約 7～9 小時；三個月份的真實 API、AWS、BigQuery 執行及排障時間另記 |
| 核心目標 | 建立與 monthly DAG 分開的手動參數化 backfill DAG，從最早積欠月份起依序處理三個月，並證明載入中斷後能安全續跑 |
| 今日交付物 | Backfill DAG、參數驗證與操作說明、三個月真實 smoke test、載入故障與復原證據、執行紀錄及學習日誌 |
| 目前狀態 | M4 技術驗收已完成，詳見[執行紀錄](day16-run-record.md)；個人實際學習工時與雲端帳單金額未提供，以下細項僅勾選已查證部分 |

MVP 維持美國月度進口、商品 `8542`、分類 `H6`，每月均須有 `partner_detail` 與 `world_total`。Day 15 的唯讀檢查顯示 `202501`～`202605` 共 17 個月尚未發布；正式 monthly DAG 因此保持暫停。本次已回填 `202501`～`202503`，並以 `202504` 演練故障復原；仍有其他積欠月份，三月 smoke test 不代表全部補齊。

## 1. 盤點積欠、參數與共用資源

**預計時間：40～55 分鐘。**

- [x] 依 Day 15 的 17 個積欠月份選定最早三月，唯讀確認 `202501`～`202503` 均未發布、兩類來源可用且 revision 為 1；來源掃描記錄列數及檢查時間。
- [x] 定義手動 run 的必要參數：`start_period`、`end_period`；以 `YYYYMM` 驗證格式、完整月份、起訖順序、連續範圍與單次最多 3 個月。額外來源 revision 須同時指定兩種類型的正整數。
- [x] 定義已發布月份政策：預設略過並列出狀態；要重跑既有發布版本時，須明確提供該月原發布 `run_id`，不得以新 ID 意外取代正式資料。
- [x] 確認 backfill 與 monthly 共用 `trade_pipeline` 單 slot Pool，候選 Dataset 在任何時刻只有一個 writer。回填期間保持 monthly DAG 暫停，避免兩條流程交錯重建 candidate。

Backfill 是明確指定月份的人工 DAG run；不使用 Airflow 原生 Backfill 指令或 monthly DAG 的 logical date 來推算範圍。排程與歷史補期的語意分開，兩者共用既有單月處理與資料品質規則。

## 2. 實作獨立 backfill DAG 與續跑契約

**預計時間：100～130 分鐘。**

- [x] 在 `dags/` 建立無排程的 backfill DAG；DAG import 時不呼叫 AWS、GCP、Comtrade 或 dbt。手動參數由 DAG run `conf` 明確傳入，非法範圍在寫入前失敗。
- [x] 逐月由舊到新執行 `ingest_detail`／`ingest_world` → `load_detail`／`load_world` → `attest` → `build` → `audit` → `gate` → `publish`；兩種來源完成載入後才建置候選。上一月發布成功後才開始下一月；失敗時停止後續月份。
- [x] 沿用 `scripts/monthly_steps.py` 的單月入口及既有永久／暫時錯誤分類，不建立第二套擷取、載入或品質判定邏輯。XCom 只保存月份、`run_id`、revision 與必要的小型 metadata。
- [x] 每月產生穩定且可查的 `run_id`；同一 DAG run 的 task retry／故障續跑沿用該月 ID，新一次品質嘗試才建立新 ID。預檢記錄 `ready`／`already_published`；未就緒時在寫入前失敗，後續狀態由 Airflow task 和品質／發布 audit 追查。
- [x] 寫明 Airflow `clear` 失敗 task 或重新觸發 run 前的檢查步驟：先核對 S3 來源配對、BigQuery load audit／job、品質 audit 與正式發布紀錄；結果不明時先查 job，不盲目 append 或換 ID。

如果來源未就緒，該月份不得開始載入或發布；是否允許後續月份繼續，須在 DAG 與操作說明中採同一明確政策。三月 smoke test 選用已確認全數就緒的區間，以便驗證完整串行鏈。

## 3. 用隔離測試驗證月份、失敗與冪等

**預計時間：70～90 分鐘。**

- [x] 測試 DAG import、無 schedule、必填參數、跨年範圍、反向區間、未完成月份、超過三月及非法 revision；確認錯誤發生在任何雲端寫入前。
- [x] 測試三月任務相依與單一 writer：前一月 `publish` 失敗時，下一月不進入 ingest／load；`gate` FAIL 不執行 publish。
- [x] 隔離測試驗證 S3 缺 manifest 時不進入 BigQuery；真實受控演練驗證載入提交後回報遺失，重試依 checksum／既有快照回傳 `already_loaded`，不增加 grain。
- [x] 測試已發布月份預設略過、原 `run_id` 安全重跑，以及新 ID 不能無授權覆蓋正式版本。不要把 fixture 結果記成真實雲端回填。

## 4. 三個月份的真實 smoke test

**預計時間：100～140 分鐘，加上雲端等待。**

- [ ] 執行前保存三月的基準：正式發布狀態、raw grain 數、兩種來源的 revision／checksum、目前品質狀態及預期費用範圍。
- [x] 以一個明確的 backfill DAG run 處理三個連續、尚未發布且來源可用的月份；Airflow 與 BigQuery 保留 task／job、來源查驗、品質與發布紀錄，摘要見[執行紀錄](day16-run-record.md)。
- [x] 驗證三個月均有兩種來源、來源查驗通過、raw grain 唯一、品質 PASS／WARN、正式版本和 `published_at` 可追溯；若品質 FAIL，停止並記錄原因，不放寬 gate 來湊齊三月。
- [x] 對完成的同批次再跑一次安全重跑，核對 raw grain 數、正式 `published_run_id` 與 `published_at` 不變；實際雲端帳單費用未提供。

## 5. 故意中斷載入並完成復原演練

**預計時間：90～120 分鐘，加上雲端等待。**

隔離測試先確認不完整來源不會寫入 BigQuery；實際復原演練選尚未發布、來源完整的 `202504`，在載入提交後刻意讓 Airflow task 丟失成功回報。演練不改寫正式 Comtrade 來源、S3 不可變原檔或已發布 partition。

- [x] 在 `load_detail` 的成功提交後刻意丟失成功回報，保留失敗 task、同一 `run_id` 與 BigQuery 載入結果；重試前下游 attest／build／publish 未執行。
- [x] 查明中斷發生在載入提交後；第二次沿用同一 `run_id`，`RawLoader` 核對快照後回傳 `already_loaded`，再完成兩類來源、品質 gate 與發布。
- [x] 比對復原後 raw grain、筆數及金額合計，確認沒有重複有效資料；正式版本只在品質通過後出現。
- [x] 記錄從 Airflow task log、S3 manifest、BigQuery job／audit 到正式發布的追查路徑。SNS email 實際收件仍是 Day 15 的未完成項，不以本次載入復原推定通知鏈已驗收。

## 6. 交付紀錄與學習檢查

**預計時間：30～40 分鐘。**

| 交付物 | 最少內容 |
|---|---|
| Backfill DAG 與測試 | 參數契約、三月上限、串行相依、共用 Pool、失敗停損、續跑及冪等 |
| 操作說明 | 觸發範例、預檢、`run_id`／revision 用法、中斷後查核與重跑步驟、monthly DAG 暫停政策 |
| 真實執行紀錄 | 三月基準與結果、DAG／task／job ID、checksum、raw grain、品質與正式發布查核；隔離 fixture 分開標示 |
| [學習日誌](learning-log.md) | 實際日期與本人投入時間、回填與復原決策、未解問題；本人時間未提供時保留空白 |

完成後用自己的話回答：

1. 為什麼獨立 backfill DAG 要用明確月份參數，而不是 Airflow 原生 Backfill 或 monthly logical date？
2. 為什麼三個月份須串行，且 backfill 與 monthly 要共用 Pool？
3. 載入 task 逾時時，如何分辨 BigQuery job 沒完成、已完成但回報遺失？
4. 同一故障嘗試為什麼沿用 `run_id`？什麼情況才建立新的品質嘗試 ID？
5. 哪些證據能證明復原後沒有重複 raw grain，而且 FAIL 沒有發布？

- [x] 獨立 backfill DAG 可依明確範圍串行處理最多三個月，且不與 monthly DAG 同時寫入 candidate。
- [x] 三個連續未發布月份完成真實來源 → raw → dbt → 品質 → 發布 smoke test，逐月保留可查證據。
- [x] 載入中斷後沿用同一 `run_id` 安全續跑，raw grain 不重複，品質 FAIL 不發布。
- [x] 重跑後正式版本與 `published_at` 不被不必要地改寫；操作說明、執行紀錄與學習日誌完成。
- [x] 上述 M4 證據齊全後，才更新[總規格](trade-analytics-spec.md)的 Day 16 與 M4 狀態；Day 15 的 SNS 實收缺口另行追蹤。

Day 17 接續 CI／CD、OIDC 與 Terraform 部署檢查；其工作不取代本日的真實三月回填與故障復原證據。
