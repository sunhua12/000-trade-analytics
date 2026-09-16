# Day 6：載入稽核、raw MERGE 與失敗重跑

| 項目 | 內容 |
|---|---|
| 對應計畫 | [20 天實作規格](trade-analytics-spec.md) 的 Day 6／M1：單月可信入倉 |
| 前置成果 | [Day 5 學習計畫](day-05-learning-plan.md) 的兩類 landing 資料、raw 空表及載入證據 |
| 預計投入 | 約 3～4 小時；前置補課與雲端除錯另記 |
| 核心目標 | 將 202301／8542／H6 正規化到 raw，能追查來源、安全重跑並拒絕舊版回寫 |
| 今日交付物 | 正規化 SQL、Manifest gate、load audit、raw MERGE、重跑證據及學習日誌 |
| 目前狀態 | 2026-09-16 更新：單月基本載入與手動 SQL 練習完成，可進入 Day 7；版本保護與完整驗收延後，M1 保留待驗收 |

今天完成的是「同一個來源檔案再跑一次，資料仍正確，失敗也能查出原因」。先沿用 Day 5 選定的單一載入方案；本日不擴展到 24 個月、dbt 指標或 Airflow。

## 目前進度與 Day 7 銜接（2026-09-16）

以下是實際進度；後續章節保留原始完整驗收規格。未勾選項目表示尚未完整驗收，不代表全部未做。

| 項目 | 目前成果與證據 |
|---|---|
| Day 5 前置 | 兩類 landing、Transfer 及 raw 結構已確認；分區期限已取消，見 [Day 5 紀錄](day05-load-record.md) |
| 真實單月 raw | 本人確認新增 SQL 已執行且結果正確；明細 67 筆、World 1 筆，各自金額 2,799,575,181，兩邊均有 success，見 [Day 6 紀錄](day06-load-record.md) |
| 來源核對 | 助理於 2026-09-15 下載兩類 S3 原始檔，核對 SHA-256、筆數、Decimal 合計、身分與數值精度，見 [來源核對證據](evidence/day06-source-verification.json)；此證據不等同於 raw 完整快照驗收 |
| 明細 SQL | 已補真實來源 metadata、gate 失敗中斷、交易內筆數／合計／重複檢查及回滾後 failed audit |
| World 本機同步 | SQL 與載入紀錄的真實 checksum 已同步；World SQL 擷取時間已對齊 manifest 的 `2026-09-12T12:20:59.992916Z`；本次為本機修改，未重新執行雲端 SQL |
| 測試結果 | 本人確認既有 SQL 練習結果正確；同版衝突、新版刪列後舊版回放、完整快照與故障復原的完整整合驗收尚未確認 |
| 驗收文件 | 已確認 [day06-verification.md](evidence/day06-verification.md) 存在，由 SQL 檔改名；目前保存驗證與 World 寫入 SQL，實際結果與完整整合驗收證據仍待補齊 |
| 學習日誌 | 已追加 Day 6 實際成果、證據來源及延後事項；實際學習工時未提供 |

### 延後事項與恢復時機

為銜接 Day 7，先使用目前已確認的 `202301／8542／H6` raw 快照進行 dbt sources 與 staging 學習。

- **版本保護延後**：正式 MERGE 的 `already_loaded`、`conflict`、`stale_revision` 與成功版本核對，須在處理來源修訂、舊版重送或自動載入前補齊。
- **完整檢查與追蹤延後**：無損精度檢查接入正式流程、固定維度 NULL／頻率驗證、完整欄位及 lineage 比對、job ID 與每次 attempt 區分，須在擴大到新來源／多月份自動載入前補齊。來源檔本機精度已核對，不能據此宣稱正式 SQL 已有相同保護。
- **M1 暫不勾選完成**：以上項目與驗收證據仍保留；進入 Day 7 不表示已滿足完整安全重跑規格。
- **執行方式已統一**：保留獨立的 `merge-raw.sql`，其中已包含明細正規化、gate 與交易。已移除未完成的獨立正規化模板、Python SQL 產生器、雲端執行腳本及其專用 job 工具；保留 `warehouse.gate` 作為唯讀來源檔核對工具，不自動提交 BigQuery 工作。World SQL 保存在驗收 Markdown 中。

### 驗收文件應包含的最小內容

若既有驗收文件已包含以下內容，無須重寫；缺項再補，延後測試明列「未驗收」。

1. 兩類來源的完整 URI、manifest／checksum／revision／擷取時間，可引用來源核對 JSON。
2. 明細與 World 的實際筆數、金額、grain 檢查結果，以及對應 Transfer run／查詢或 MERGE job ID；缺少的 ID 如實標記。
3. 每項已跑測試的情境、預期結果、實際結果及截圖或查詢輸出；區分真實來源與人工 fixture，不以 SQL 存在代替執行證據。
4. 版本保護、完整快照及故障復原等延後項目，以及 M1 仍待驗收的結論。

## 1. 今天要理解的流程

**預計時間：15 分鐘。**

```text
指定 S3 data／manifest ＋ 建立本次執行識別
                     ↓
核對原始 bytes、checksum、筆數、Decimal 合計與來源身分
                     ↓
沿用 Day 5 載入方案 → 等待 job／Transfer run 成功
                     ↓
landing → 正規化暫存結果 → 核對 Manifest／grain／型別
                     ↓
檢查該批次最新已接受 revision
                     ↓
交易內：raw MERGE ＋ 結果核對 ＋ success audit
                     ↓
重跑同檔、較舊版本、修訂刪列及失敗復原測試
```

| 概念 | 白話說明 | 今日用途 |
|---|---|---|
| Grain | 一筆資料代表的最小單位 | 判斷重複資料，不靠分區自動去重 |
| Manifest gate | 入倉前的來源核對關卡 | 筆數、金額或 checksum 不合就停止 |
| MERGE | 比對來源與目的表後新增、更新或刪除 | 維持最新已接受的完整快照 |
| Revision | 同一批來源的修訂版號 | 防止舊檔覆蓋新資料 |
| Load audit | 每次執行留下的追蹤紀錄 | 從錯誤找到來源檔案及雲端 job |
| Transaction | 多項變更一起成功或一起回復 | 避免 raw 已變更，成功紀錄卻未寫入 |

本日的處理批次為 `period × query_type × cmd_code × hs_version`；兩種 query type 各自對應一張 raw 表。表內有效 grain 為 `period_start_date × partner_code × cmd_code × hs_version`，其餘維度依資料契約固定。

## 2. 確認 Day 5 前置成果

**預計時間：15～20 分鐘。**

- [x] 真實 BigQuery 已有 202301 的明細與 World landing 表，且可查詢。
- [ ] 保存兩類來源的完整 S3 URI、manifest、checksum、revision 與載入 job／run ID。
- [x] 明細及 World 的筆數與金額各自符合 manifest。
- [x] 兩張 raw 表的 schema、月份分區、cluster 與 Dataset location 已確認。
- [ ] 已決定使用 Transfer 或 Python adapter，能查詢既有工作的狀態。
- [ ] 今日採單 writer，從來源檢查至 raw 提交皆串行執行，避免共用 landing 被其他工作覆寫。

參照 [資料契約](data-contract.md) 與 [Day 5 計畫](day-05-learning-plan.md)。歷史樣本是明細 67 筆、World 1 筆，兩者金額各為 2,799,575,181；本日以選定檔案的 manifest 為驗收依據。

若 Day 5 尚未完成，可先用明確標記的 fixture 練習 SQL 與錯誤分支；M1 必須等真實 AWS／S3／BigQuery 證據補齊後才驗收。

## 3. 建立追加式 load audit

**預計時間：30～35 分鐘。**

在與 raw 相同位置的 `trade_raw` Dataset 建立 `audit_ingestion_runs`。本日建議每個執行階段追加一筆事件，保留失敗與重試歷史，不覆寫前次結果。

| 欄位 | 建議型別 | 記錄內容 |
|---|---|---|
| `event_id`、`run_id`、`attempt_id` | STRING | 事件、邏輯執行與嘗試的識別；恢復既有 job 時沿用 attempt |
| `period`、`query_type`、`cmd_code`、`hs_version` | STRING | 來源批次身分 |
| `revision` | INT64 | 本次來源版號 |
| `source_file`、`manifest_file`、`checksum` | STRING | 完整 URI 與原始 data 的 SHA-256 |
| `load_job_id`、`transfer_run_id`、`merge_job_id` | STRING，可為 NULL | 已提交工作的識別；提交前失敗可為 NULL |
| `expected_row_count`、`actual_row_count` | INT64，可為 NULL | Manifest 與驗證結果 |
| `expected_primary_value_sum` | STRING，可為 NULL | 保留 manifest 原始十進位字串，即使超出 NUMERIC 仍可記錄 |
| `actual_primary_value_sum` | NUMERIC，可為 NULL | 可無損轉型後的實際合計 |
| `status`、`error_stage`、`error_message` | STRING | 狀態、出錯階段與去除機密的摘要 |
| `source_ingested_at`、`event_at` | TIMESTAMP | 來源擷取時間與事件紀錄時間 |

狀態至少區分 `started`、`loaded`、`validated`、`success`、`already_loaded`、`stale_revision`、`conflict`、`failed`。一次手動重跑新增 attempt，查詢既有 job 的恢復操作不偽裝成新載入。

實作順序：

1. 提交載入前，先保存來源身分及 `started`；取得工作識別後追加事件。
2. 等載入成功，追加 `loaded`；正規化與 gate 通過後追加 `validated`。
3. 將 raw 變更及 `success` 事件放在同一個交易。
4. 交易失敗先回滾，再於交易之外追加 `failed`。若 audit 本身無法寫入，將 metadata 與錯誤保存至本機證據，列為待補。
5. 網路逾時先查既有 job 狀態；結果未明時，不回報失敗或重送寫入。重送 audit 前按 `event_id` 查重。

BigQuery 支援多陳述式交易；交易與例外處理的行為請參照 [官方交易文件](https://docs.cloud.google.com/bigquery/docs/transactions)。本日仍以單 writer 為前提，事件識別與查重不代表已有跨 writer 的唯一性保證。

## 4. 正規化與 Manifest gate

**預計時間：35～40 分鐘。**

先產生本次載入專用的正規化暫存結果，通過所有檢查後才允許寫入 raw。原始 checksum 必須從 S3 data 的 bytes 計算，不能對 SQL 查詢結果重新序列化後比較。

| Raw 欄位 | 來源與轉換 |
|---|---|
| `period` | 來源 `period`，先驗證為本次月份 |
| `period_start_date` | 將 `202301` 明確解析為 `2023-01-01` |
| `reporter_code`、`partner_code`、`flow_code`、`cmd_code` | 對應來源欄位，代碼統一為 STRING |
| `hs_version` | 來源 `classificationCode`，必須為 H6 |
| `primary_value` | `primaryValue`，無損轉為 NUMERIC |
| `net_weight`、`quantity` | `netWgt`、`qty`，NULL 保留；非 NULL 值須無損轉型 |
| `ingested_at` | 來源 manifest 的擷取時間 |
| `source_file`、`checksum`、`run_id`、`revision` | 從已核對的本次執行 metadata 補入 |

先用 Decimal 確認數值可無損表示為 NUMERIC，再轉型。`SAFE_CAST` 回傳非 NULL 不能證明沒有捨入；超出範圍或精度時停止並記錄，沿用 Day 5 的精度規則。不可把非法字串轉成 NULL 後繼續。

- [x] Data／manifest 齊全，schema version 為 `2.0.0`；路徑、manifest、資料列身分一致。
- [x] 原始 bytes 的 SHA-256、非空行數與 Decimal 合計符合 manifest。
- [ ] 載入完成後，landing 與正規化結果的筆數、金額均符合 manifest。
- [ ] 月份、842、M、8542、H6，以及 `partner2Code=0`、`customsCode=C00`、`motCode=0` 均符合契約，頻率為 M。
- [ ] Grain 欄位無 NULL，沒有重複 grain；不能用任意 `ROW_NUMBER()` 選一筆掩蓋問題。
- [ ] 明細沒有 World，金額有限且非負；World 恰一筆、partner 為 0 且金額大於 0。
- [ ] 重量及數量的 NULL 保留，夥伴 490 原碼與金額保留。

任一檢查失敗，raw 維持原狀，audit 指出檔案與失敗階段。本日核對各檔與 manifest 的一致性；正式國家分類、World 對帳模型及發布 gate 留待後續建模。

## 5. 實作 revision 保護與 raw MERGE

**預計時間：45～55 分鐘。**

先對整個處理批次判斷版本，再執行 MERGE。不能只在 `WHEN MATCHED` 比較 revision，否則舊檔中已被新版刪除的 grain 仍可能被重新插入。

| 已接受狀態與本次來源 | 預期動作 |
|---|---|
| 尚無已接受版本 | Gate 通過後插入本次完整快照 |
| 同 revision、同 checksum 與契約 metadata | 核對 raw 快照仍一致，追加 `already_loaded`；保留原始 raw lineage |
| 同 revision，checksum 或契約 metadata 不同 | `conflict`，不改 raw |
| 本次 revision 較舊 | `stale_revision`，整批略過，不插入、更新或刪除 |
| 本次 revision 較新 | Gate 通過後更新整個批次快照，包含刪除新版不再存在的 grain |
| Raw 與成功 audit 不一致 | 停止並調查，不能以 `already_loaded` 掩蓋資料缺損 |

以成功 audit 中該批次最高已接受 revision 作為版本依據，再與 raw 核對；不能只取 raw 的 `MAX(revision)`，因為來源快照刪空時表內可能沒有資料列。同版本比較的 metadata 不包含本次 job ID 或 attempt 時間。

撰寫 `merge-raw.sql` 時依序完成：

1. 建立並驗證單一批次的正規化暫存來源；檢查目的表同範圍也無重複 grain。
2. 在交易內再次確認已接受版本，依上表決定停止、略過或寫入。
3. `ON` 比對完整 grain，且對目標加上本次月份、商品與分類範圍。
4. `WHEN MATCHED` 更新所有值與 lineage；`WHEN NOT MATCHED BY TARGET` 明列欄位插入。
5. `WHEN NOT MATCHED BY SOURCE` 僅刪除目標中屬於本次月份、商品及分類的列。query type 由所選 raw 表隔離。
6. 交易內再次核對 raw 的筆數、金額、grain、revision 及 lineage；成功才追加 success audit 並提交。

MERGE 的刪除分支必須自己限制目標範圍，不能以為 `ON` 有月份條件就能保護其他月份。執行前用唯讀查詢列出預計刪除的 grain。語法與分支行為見 [BigQuery MERGE 官方文件](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/dml-syntax#merge_statement)。

明細與 World 各自載入、驗證及提交；一邊成功不代表另一邊完成。兩邊皆成功才通過本日單月驗收；本日不宣稱兩張表已整體原子更新。

## 6. 重跑、刪列與失敗復原練習

**預計時間：35～45 分鐘。**

真實 202301 來源執行首次載入與同檔重跑。修訂、損毀與故障注入使用獨立測試 Dataset／fixture，不修改已保存的真實 S3 revision，也不把人工 revision 當成官方來源更正。

| 情境 | 準備方式 | 必須觀察到的結果 |
|---|---|---|
| 首次載入 | 真實明細與 World 各執行一次 | 各自 raw 與 manifest 筆數、金額一致，保存成功 job |
| 同檔第二次執行 | 相同 revision、checksum | Raw grain、筆數、金額與 lineage 不變；留下第二次嘗試紀錄 |
| 同版內容衝突 | Fixture 修改資料並重算 manifest，版號不變 | `conflict`，raw 完全不變 |
| 新版刪列 | Fixture r2 刪除一個夥伴、修改另一筆金額並重算 manifest | 被刪 grain 消失，金額更新，raw 全批符合 r2 |
| 舊版回放 | r2 成功後再次送 r1 | 不回復被刪 grain，不覆蓋新版金額 |
| Gate 失敗 | 分別製造錯 checksum、重複 grain、非法金額或錯誤月份 | 在 MERGE 前停止，保留前次 raw 與可定位錯誤 |
| MERGE 後提交前失敗 | 測試交易中注入失敗檢查 | Raw 回滾，無 success 事件，交易外有 failed 紀錄 |
| 工作結果未明 | 模擬提交後客戶端中斷 | 先查原 job，再依成功或確認失敗恢復，不盲目追加 |
| 僅 World 失敗 | 明細成功後令 World gate 失敗 | 明細結果保留，World 失敗可追查，整體單月未完成 |
| 範圍隔離 | 測試表先放另一月份或商品資料 | 修訂 MERGE 後，其他範圍逐欄不變 |

以完整 grain 與欄位比較驗證快照，不能只比較 `COUNT(*)` 和 `SUM()`；相同筆數及金額仍可能包含錯誤夥伴。SQL 查 raw 時需帶月份分區篩選。真實執行與 fixture 結果分開保存。

## 7. 交付物、複習與完成條件

**預計時間：10 分鐘。**

以下為原始交付物清單；目前多數 SQL 與載入紀錄已存在，完成程度以本頁「目前進度」及實際證據為準：

| 建議路徑 | 內容 |
|---|---|
| `infrastructure/gcp/audit-ingestion-runs.sql` | Audit DDL 與事件欄位說明 |
| `infrastructure/gcp/merge-raw.sql` | 明細正規化、gate、範圍限制、刪列及交易；版本保護延後 |
| `docs/day06-load-record.md` | 選定載入方案、來源／job 對應、成功與失敗結果 |
| `docs/evidence/day06-verification.md` | World 正規化／寫入與驗證 SQL；真實重跑結果及獨立 fixture 測試摘要待補齊 |
| `docs/learning-log.md` | Day 6 實際工時、理解、問題與未完成項目 |

若新增 Python gate／adapter 邏輯，補對應的精度、版本與錯誤復原單元測試，執行專案既有 Ruff、mypy 與相關測試；SQL 行為另以 BigQuery 測試 Dataset 驗證，不能以假 client 測試取代。

完成後用自己的話回答：

1. 為什麼 landing 重載不增加筆數，仍不能證明 raw 重跑安全？
2. 為什麼 MERGE 前必須驗證來源 grain 唯一？
3. 為什麼只做 upsert 會留下新版已刪除的資料？
4. 為什麼舊 revision 必須整批攔下，而非只禁止 UPDATE？
5. 為什麼來源擷取時間、載入時間與本次重跑時間要分開？
6. 客戶端逾時時，如何區分「job 失敗」與「尚未知道 job 結果」？

- [x] 真實明細與 World 均已進入 raw，筆數與金額各自符合 manifest（依本人執行確認；完整逐欄比對仍待驗收）。
- [ ] 同檔連跑兩次，raw grain 不重複，值與 lineage 不變。
- [ ] 同版衝突、舊版回放、新版刪列與範圍隔離測試通過。
- [ ] Gate 與交易失敗保留原資料，audit 可定位來源及已提交 job。
- [x] Day 6 學習日誌與目前進度標示已回填。
- [ ] SQL／設定整合與完整驗收證據完成（驗收 Markdown 已存在，完整結果待補齊）。
- [ ] M1 的 API／Lambda／S3／BigQuery 真實證據逐項核對；缺項明列待補。

下一步可使用已確認的真實單月 raw 進入 Day 7 的 dbt 基礎與 staging；本次版本保護與完整驗收延後，M1 保留待驗收狀態。
