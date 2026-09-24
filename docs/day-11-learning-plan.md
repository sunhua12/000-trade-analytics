# Day 11：分批回填、24 個月覆蓋與來源修訂驗證

| 項目 | 內容 |
|---|---|
| 對應計畫 | [20 天實作規格](trade-analytics-spec.md) 的 Day 11 |
| 前置成果 | [Day 10](day-10-learning-plan.md) 的單月對帳、品質 gate 與正式發布；[Day 6](day-06-learning-plan.md) 的載入與版本保護 |
| 預計投入 | 先安排約 4～5 小時進行規劃、3 個月試跑與驗證；24 個月回填及外部等待時間依實測另記，必要時延長實作日 |
| 核心目標 | 讓 202301～202412 的每個月份都有可追溯的來源、載入、品質與發布狀態；安全處理重跑與來源修訂 |
| 今日交付物 | 3 個月試跑紀錄、24 個月覆蓋清單、逐月對帳與品質摘要、修訂／失敗驗證、學習日誌 |
| 目前狀態 | 技術實作與 24 個月驗收完成；見[執行紀錄](day11-backfill-record.md)與[覆蓋摘要](evidence/day11/coverage-summary.json)。真實來源修訂仍待實例驗收 |

今天的重點是把「單月流程可用」擴成「每個目標月份都能查到結果」。回填先手動、依月份串行執行；Airflow 的排程與獨立 backfill DAG 分別留在 Day 14～16。本計畫後續已依[執行紀錄](day11-backfill-record.md)完成，以下保留原定驗收項目作為學習對照。

## 1. 確認擴大載入的必要前置

**預計時間：20～30 分鐘。**

- [ ] Day 10 真實單月的 candidate → audit → gate → publish 已驗收；FAIL 不更新正式表，WARN 可發布並帶品質標記。
- [ ] Day 6 延後的同版重跑、同版衝突、舊版拒絕、修訂刪列、無損精度、完整快照與 lineage 檢查已補齊並留下證據；在此之前不批量寫入新月份。
- [ ] 固定 reporter `842`、flow `M`、商品 `8542`、分類 `H6`；兩種來源查詢分開驗證。
- [ ] 確認單一載入方案、S3／BigQuery 權限、雲端成本限制及執行 Dataset；fixture 與真實資料隔離。
- [ ] 確認每月 ingestion、load、dbt、publish 的手動入口與失敗重啟點，並限制為單一 writer，避免共用 landing 互相覆寫。

若前置未完成，先補齊並另記時間。可以先用唯讀盤點與隔離 fixture 練習覆蓋表，但不能把它算成真實 3 個月或 24 個月驗收。202301 的歷史金額與筆數只作比對參考，實際驗收以本次選定的兩類來源版本及 manifest 為準。

## 2. 建立 24 個月份的執行與覆蓋清單

**預計時間：25 分鐘。**

以 `dim_months` 的 202301～202412 共 24 個連續月份為骨架，每月固定產生一列；即使 API 尚無資料、載入失敗或首次發布失敗，也必須留在清單中。執行單位是 `period × cmd_code × hs_version`，其下的 `partner_detail` 與 `world_total` 分別記錄來源與載入狀態。

| 欄位群 | 最少記錄內容 |
|---|---|
| 目標與來源 | period、商品、分類、兩類來源可用性、revision、checksum、S3 URI、manifest 筆數與金額 |
| 入倉 | 各自 load job／run ID、raw 接受 revision、筆數、金額、grain 與 lineage 核對結果 |
| 品質 | 對帳 run_id、partner_sum、world_total、差異率、country_coverage、PASS／WARN／FAIL、全部 reason codes |
| 發布 | candidate_batch_id、最近發布 run_id／時間、最近嘗試時間與結果；未發布原因 |

明確區分 `not_available`（來源尚未提供）、`not_attempted`、`failed`、`quality_fail`、`published_pass`、`published_warn` 等狀態；這些是建議清單狀態，不必與既有 audit 欄位名稱相同。缺資料或查詢失敗不寫成零金額，也不因上一版已發布而將最新嘗試標為成功。清單最好由月份 spine LEFT JOIN 來源、load audit、品質 audit 與發布摘要產生；避免從已有 mart 出發而漏掉整月缺失。

## 3. 先跑 3 個月試批

**預計時間：60～90 分鐘，加上 API 與雲端工作等待。**

試批選 `202301`、`202302`、`202401`：第一個月用既有真實基準核對，第二個月檢查連續月份與 MoM，第三個月檢查跨年 YoY。若其中一月來源不可用，保留原月份及其原因，再選一個可用月份完成流程試跑；不能以替代月份覆蓋原目標清單。

對每個月份依下列順序串行操作：

```text
確認來源可用與既有版本
  → 擷取 detail／World 並驗證 data、manifest、checksum
  → 載入與 raw gate；核對兩類來源各自筆數、金額、版本
  → 建置本月 candidate 與對帳 audit
  → 依 PASS／WARN／FAIL gate 決定是否發布
  → 更新覆蓋清單並保存 job、run 與 SQL 查核證據
```

每月停止點須明確：來源未就緒不進入載入；任一來源或 raw gate 失敗不建置可發布 candidate；品質 FAIL 不更新正式分區。暫時性 API 錯誤可以依既有 client 規則有限重試；checksum 衝突、分類不符、疑似截斷與權限錯誤須先定位，不盲目重送。試批完成後再核對 raw、fact、candidate、published 的月別筆數與來源 lineage；MoM／YoY 的檢查以同夥伴、商品、H6 的真實基期為準，缺基期維持 NULL。

3 個月試跑是本日的擴大載入 smoke test；Day 16 仍要用 Airflow 的獨立 backfill DAG 再完成其 3 個月編排與復原驗收。

## 4. 擴展至連續 24 個月

**預計時間：依試批耗時與來源狀態估算，超出當日時間則分次執行並保留進度。**

試批通過後才依月份順序處理剩餘月份。每次只對缺少或明確需要修訂的月份／來源動手，先比對接受版本；相同 checksum 的已完成批次應驗證後略過，不能為了重新跑 24 次而製造新 revision。執行中斷時，從覆蓋清單的最後穩定狀態恢復，先查既有雲端 job 與 audit，再決定是否重送。

每月最少檢查：

1. detail 與 World 均有接受的來源版本，固定維度與 H6 一致，未達截斷警戒。
2. manifest、S3 data、landing 與 raw 的筆數、金額、checksum／lineage 可連結；World grain 唯一，明細 grain 唯一。
3. 對帳差異率與完整品質原因已寫入 audit；全體互斥明細與已確認國家集合分開計算。
4. PASS／WARN 才可發布；FAIL 保留前次成功版本。HHI 是否可顯示仍看國家覆蓋門檻，不以對帳 PASS 推定可用。
5. 指標在跨月與跨年邊界沒有錯接；缺基期、缺重量與缺 ISO 保留 NULL／限制說明。

完成後以月份 spine 做 anti-join，確認目標 24 個月份全部列於清單，並分別統計來源齊全、raw 已接受、品質 PASS／WARN／FAIL、正式已發布的月份數。`24/24` 只能描述「每月有可解釋狀態」；若有月份缺來源或品質 FAIL，不能宣稱「24/24 已發布」。若 H6 無法涵蓋全部月份，記錄缺口及來源回應；依總規格另評估可驗證的連續 24 個月範圍，不混用分類版本。

## 5. 驗證來源修訂與失敗保留

**預計時間：35～45 分鐘。**

先在隔離資料集以 fixture 測試修訂；真實來源有正式修訂時再以新 revision 執行，保留舊版 S3 檔案。兩種來源的 revision 獨立判斷，不能假設 detail 與 World 同號。

| 情境 | 預期結果 |
|---|---|
| 同一檔案重跑 | checksum 相同、有效 raw／published grain 不重複；可追查這次嘗試 |
| 同 revision、內容不同 | 判定 conflict，停止寫入，保留既有接受版本 |
| 較舊 revision 回放 | 判定 stale，不能覆蓋較新 raw 或 published |
| 新 revision 刪去一個夥伴 | 驗證新版完整快照後移除舊 grain；candidate 與正式分區也沒有殘留 |
| 新 revision 對帳 FAIL | 保存失敗 audit 與來源版本；正式表維持前一成功版本與時間 |
| 失敗後修正重跑 | 新嘗試有獨立識別；成功後僅替換指定月份，其他月份不變 |

修訂引發的 raw 變更與 published 更新分屬不同 gate。不可只用總金額相同判定快照相同；需比對兩方向 row set、grain、金額與 lineage。正式來源沒有修訂案例時，將真實修訂標為未驗收，fixture 結果單獨列示。

## 6. 檢視歷史品質分布與記錄限制

**預計時間：25～30 分鐘。**

彙整各月差異率、PASS／WARN／FAIL、國家覆蓋率、HHI 可用性、重量／ISO 缺值及 490 的占比；列出異常月份與來源版本。先查明來源、分類與載入原因，再評估門檻。若調整 0.5%／2% 或 HHI 覆蓋門檻，需記錄舊值、新值、規則版本、受影響月份與理由，重跑受影響 audit／發布判斷；不能為了使月份通過而直接放寬。

## 7. 交付與完成條件

**預計時間：20～30 分鐘。**

| 實際交付路徑 | 內容 |
|---|---|
| [Day 11 執行紀錄](day11-backfill-record.md) | 執行順序、3 個月試跑、24 個月回填、成本／耗時未取得的範圍與阻礙 |
| [24 個月覆蓋清單](evidence/day11/coverage.csv) | 固定 24 列的逐月來源、raw、品質與發布狀態 |
| [覆蓋 SQL](evidence/day11-coverage.sql)、[發布比對 SQL](evidence/day11-publication-check.sql)、[指標 SQL](evidence/day11-metrics.sql) | 月份 spine、raw／audit／published 比對與指標查核 |
| [驗收摘要](evidence/day11/coverage-summary.json)、[載入](evidence/day11/load-range.json)、[發布](evidence/day11/release-final.json)、[修訂 fixture](evidence/day11/revision-fixture.json) | 真實查詢結果、job IDs 與隔離修訂測試 |
| [學習日誌](learning-log.md) | 未提供的實際學習工時、理解整理與下一步 |

實際文件與證據集中於[Day 11 執行紀錄](day11-backfill-record.md)及 `docs/evidence/day11/`，以可重現的執行命令、SQL 與雲端證據為準。

完成後用自己的話回答：

1. 為什麼覆蓋清單要從 24 個月份出發，而不能從 published mart 出發？
2. `24/24` 有狀態與 `24/24` 已發布有何不同？
3. 為什麼 detail 和 World 必須各自核對 revision、checksum 與載入結果？
4. 來源新版刪除夥伴時，只有 upsert 會留下什麼錯誤？
5. 某月最新嘗試 FAIL，但 Dashboard 仍看見該月資料，應如何解釋？
6. 為什麼跨月 MoM／YoY 不能以「上一筆／前十二筆」直接計算？

- [x] 多月份載入與版本保護、Day 10 發布 gate 均有實測證據。
- [x] 3 個月試批逐月核對兩類來源、raw、candidate、品質與發布結果。
- [x] 202301～202412 的覆蓋清單恰有 24 個月份，無靜默漏月或混版。
- [x] 每個已發布月份可追至兩類來源、載入 job、品質 audit 與 candidate batch。
- [x] 同版、衝突、舊版、修訂刪列、交易回滾及 FAIL 保留有隔離驗證；真實來源尚無 revision 2。
- [x] 歷史品質分布及門檻決策已記錄；雲端帳單與個人實際學習時間未提供，未虛構數值。

通過以上驗收後，才更新總規格的 Day 11 完成狀態。Day 12 使用已發布的資料建立 Dashboard；Day 16 再將手動回填流程放進獨立 Airflow DAG 驗證。
