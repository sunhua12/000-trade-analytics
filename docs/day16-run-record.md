# Day 16：參數化回填與復原執行紀錄

| 項目 | 實測結果 |
|---|---|
| 日期 | 2026-10-01（Asia/Taipei） |
| 範圍 | 美國月度進口 `8542／H6`；三月 smoke test 為 `202501`～`202503`，受控復原演練為 `202504` |
| Airflow | 本機 Airflow 3.3.2；`trade_backfill_pipeline` 無排程、`max_active_runs=1`、`max_active_tasks=1`，與暫停的 monthly DAG 共用單 slot Pool |
| 程式檢查 | Python 全套 229 passed、3 skipped；Ruff lint／format、`mypy src`、`git diff --check` 通過；DAG import errors 為空 |

## 初次品質停損與分類審查

第一個真實 DAG run `manual__2026-09-30T16:58:51.109780+00:00` 對 `202501` 完成兩種來源擷取、raw 載入、來源查驗與 dbt build，但 `gate` 失敗。品質 audit `backfill-202501-a1dfd2c68d3e4b18` 記錄 `FAIL`，原因為 `missing_dimension`、`unresolved_reconciliation`、`unreviewed_classification`。BigQuery 查核顯示明細 raw 67 筆、World 1 筆，兩者金額均為 3,525,209,472；正式發布 0 筆，`202502`／`202503` 下游任務均為 `upstream_failed`，沒有開始寫入。

唯讀查詢 job `2e13dbc9-2174-4c61-8d4d-92a9e7261ca2` 找出 `202501` 未分類代碼 `112`、`499`、`716`。進一步唯讀掃描 `202502`／`202503` 來源，合計另有 `148`、`132`、`670`、`834`。這 7 個代碼均在已保存的 Comtrade `partnerAreas.json` 與 UN M49 快照中找到單一、非群組且期間有效的國家／地區對應；審查清單見 [partner-review.json](evidence/day16/partner-review.json)。依審查結果重建 `country_reference.csv`，由 142 增為 149 列，未調整品質門檻。原 FAIL audit 保留；重新執行時使用新的品質嘗試 ID。

## 三個月真實回填

第二個 DAG run `manual__2026-10-01T02:22:56.108332+00:00` 於台北時間 10:22 開始、10:28 完成。三個月份依舊到新串行，兩類來源載入、來源查驗、dbt 88 項 build／test、品質 gate 與發布均完成。`202501` 的 raw 已由首次失敗 run 載入，故第二次回傳 `already_loaded`；後兩月為新載入。每月品質均為 PASS、無 reason code。六份 S3 URI、checksum 與筆數見[來源身分證據](evidence/day16/source-identities.json)，載入 job ID 見[載入證據](evidence/day16/load-jobs.json)，正式結果見[唯讀 BigQuery 驗證](evidence/day16/three-month-verification.json)。

| 月份 | 明細 raw／World raw | 明細與 World 金額 | 正式筆數 | 發布 run ID |
|---|---:|---:|---:|---|
| `202501` | 67／1 | 3,525,209,472 | 67 | `backfill-202501-f345c669360ee0ee` |
| `202502` | 62／1 | 2,896,179,813 | 62 | `backfill-202502-f345c669360ee0ee` |
| `202503` | 61／1 | 3,897,507,654 | 61 | `backfill-202503-f345c669360ee0ee` |

每月明細的 `COUNT(DISTINCT partner_code)` 等於 raw 筆數；兩種 raw 各只有一個 checksum 和 revision。這是 17 個積欠月份中的前三個月，不能代表全部積欠已清完。

## 載入提交後失去成功回報的復原演練

為驗證真實 Airflow task retry，以尚未發布的 `202504` 啟動 `manual__2026-10-01T02:31:33.177542+00:00`，明確指定 `recovery_probe` 為 `partner_detail`。來源預檢確認兩種類型均可用；新代碼 `320`（Guatemala）經同一 Comtrade／M49 快照審查後加入 seed，合計 150 列。

第一次 `load_detail` 將 61 筆明細成功提交 BigQuery，然後故意在 Airflow task 回報前丟出例外，task 轉為 `up_for_retry`。第二次 task 嘗試沿用同一 DAG run 與月份，`RawLoader` 核對原始快照後回傳 `already_loaded`，Airflow task 最終為 success，嘗試次數 2。下游 attest、dbt、品質 PASS 與發布隨後完成。[復原證據](evidence/day16/recovery-verification.json)保存 XCom 結果及唯讀 BigQuery 查核：明細 61 個不同 partner grain、World 1 筆，兩者金額均為 3,114,414,147；正式 61 筆，只有一個發布 run ID。

此演練覆蓋「BigQuery 已提交，但 Airflow 沒收到成功回報」；不宣稱涵蓋容器硬中斷、BigQuery transaction 中途失敗或 SNS email 實際收件。Day 15 的 email 訂閱與實收仍待另外驗證。

## 三個月安全重跑與 M4

第三個 DAG run `manual__2026-10-01T02:40:06.944602+00:00` 明確提供三個月各自原本的 `published_run_id`，於台北時間 10:40～10:43 成功。兩種 raw 載入回傳 `already_loaded`，各月 publish 回傳 `already_published`。將[重跑後驗證](evidence/day16/replay-verification.json)與[首次發布驗證](evidence/day16/three-month-verification.json)逐月比較：明細 raw 筆數／不同夥伴數、World 筆數、正式筆數、`published_run_id` 與 `published_at` 全部相同。特別是三月正式發布時間依序維持 UTC `02:24:33.796`、`02:26:43.081`、`02:28:43.890`。

至此，M4 所需的 monthly DAG、三個月真實 backfill 與故障後復原均有技術證據。剩餘 `202505`～`202605` 積欠月份須另批處理；monthly DAG 仍保持暫停。SNS email 實收屬 Day 15 的未完成項，不能由本日復原結果代替。

完整的執行前 raw baseline 與預估／實際雲端費用未保存，因此[學習計畫](day-16-learning-plan.md)中該細項維持未勾選；不影響上述 M4 功能與資料正確性驗收。
