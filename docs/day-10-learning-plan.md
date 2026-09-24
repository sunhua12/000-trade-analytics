# Day 10：對帳、PASS／WARN／FAIL 與正式發布門檻

| 項目 | 內容 |
|---|---|
| 對應計畫 | [20 天實作規格](trade-analytics-spec.md) 的 Day 10／里程碑 M2 |
| 前置成果 | [Day 8](day-08-learning-plan.md) 的 fact 與分類決策、[Day 9](day-09-learning-plan.md) 的指標與反例測試 |
| 預計投入 | 約 4～4.5 小時；前置補課、分類考證與環境除錯另記 |
| 核心目標 | 真實單月可追溯對帳；只有通過品質門檻的候選資料能更新正式資料 |
| 今日交付物 | 對帳 audit、candidate mart、發布程序、品質摘要、異常 fixture 與單月分析 SQL |
| 目前狀態 | 待實作；建立本計畫時專案尚無 dbt 目錄，不代表 Day 7～9 已完成 |

今天將「指標算得出來」推進到「能判斷資料是否可發布」。先完成單月手動執行流程；24 個月回填留在 Day 11，Airflow 編排留在後續日程。建立學習計畫不等於完成 M2。

## 1. 確認前置成果與本日資料範圍

**預計時間：15 分鐘。**

- [ ] Day 7～9 的 dev 環境、staging、維度、fact 與指標模型已建立且可驗證。
- [ ] 選定真實月份 202301、商品 8542、分類 H6；reporter 固定 842、flow 固定 M。
- [ ] 明細與 World 各有已接受的來源版本、checksum、source_file、ingested_at 與載入 audit。
- [ ] Day 8 的 `reconciliation_role` 與分類依據可查，未知與待審項目有清單。
- [ ] Day 9 的手算與缺月、缺分母、覆蓋不足測試有證據。
- [ ] Fixture 使用獨立 Dataset／target，與真實 raw 及正式發布表隔離。

若前置模型尚未完成，先依既有計畫補齊並另記工時。Day 2 的 202301 檔案抽查曾得到明細與 World 同為 2,799,575,181；這是歷史參考值，本日仍須驗證本次接受版本及實際入倉資料。

本日發布單位固定為 `period × cmd_code × hs_version`，下文稱為「月份分區」。這是業務替換範圍，不代表 BigQuery 實體 partition 同時使用三個欄位。

## 2. 分開全體明細對帳與國家覆蓋率

**預計時間：25 分鐘。**

| 集合 | 用途與處理 |
|---|---|
| 已審核、互不重疊的明細 | `reconciliation_role=detail`，納入 partner_sum，可包含特殊未分配項目 |
| 已確認且互斥的國家 | 納入 country_sum 與 HHI；沿用 Day 9 的國家集合 |
| 重疊區域／群組 | `reconciliation_role=overlap`，排除對帳合計，保留排除依據、筆數及金額 |
| World | 獨立 staging 分母，不加入 fact 明細合計 |
| 未知或待審對帳角色 | 保留原始交易與 audit；本日採保守阻擋，不能默認成可加總明細 |

特殊代碼 490 沿用 Day 8 的考證結果。只有確認其為互斥明細後才納入 partner_sum；不能為了對帳成功而直接指定角色，也不能為了補足國家覆蓋率把它改成一般國家。

```text
partner_sum = 可與 World 對應的全部互斥明細金額合計
country_sum = 已確認且互斥的國家金額合計
difference = partner_sum - world_total
difference_rate = ABS(difference) / ABS(world_total)
country_coverage = country_sum / world_total
```

World 必須恰一筆且大於 0，否則比率為 NULL 並判定 FAIL。金額維持 NUMERIC，先以未四捨五入數值判斷門檻。沒有明細時保留缺資料狀態，不把空集合補成 0 冒充完整資料。

例如 World 100、國家 80、已確認互斥特殊項 20，對帳差異為 0，可為 PASS；國家覆蓋只有 80%，HHI 顯示值仍為 NULL。對帳狀態與 HHI 可用性必須分欄保存。

## 3. 建立對帳 audit 與品質規則

**預計時間：40 分鐘。**

新增 `audit_world_reconciliation`，以本次明確指定的月份分區為骨架，LEFT JOIN 明細彙總、World 檢查、來源載入狀態及分類 audit。即使整個月份缺資料，也要有失敗紀錄；不要只從已有 fact 的月份起算。

| 建議欄位 | 內容 |
|---|---|
| run_id、period、cmd_code、hs_version | 每次品質檢查的唯一 key |
| detail_run_id、world_run_id | 各自來源執行識別；不得假設兩者相同 |
| 兩類 revision、checksum、source_file、ingested_at | 明細與 World 分別保存，或連到不可變來源清單 |
| detail_row_count、world_row_count | 缺明細、World 缺失或重複的證據 |
| partner_sum、country_sum、world_total | 兩種分析集合及分母 |
| difference、difference_rate、country_coverage | 未格式化的對帳與覆蓋數值 |
| unresolved_count、excluded_overlap_count | 待審與排除項目，另附金額及原因 |
| status、reason_codes、tested_at | PASS／WARN／FAIL、完整原因清單及實際檢查時間 |
| 門檻、規則版本、candidate_batch_id | 追蹤此次判斷與待發布的確切批次 |

此處 `run_id` 是本次品質檢查識別，不取代 ingestion 的來源 run_id。新嘗試使用新 run_id；重試同一 run_id 時採明確的冪等規則，不產生重複 key。Audit 保存歷次嘗試，不沿用 Day 8 的重建快照方式覆蓋歷史。

將以下初始門檻集中於共用設定，並將實際值寫入 audit：

```yaml
reconciliation_pass_max: 0.005
reconciliation_warn_max: 0.02
hhi_max_coverage_gap: 0.005
```

| 條件 | 對帳／發布結果 |
|---|---|
| 有任一阻擋問題 | FAIL，不發布；優先於數值差異判斷 |
| 無阻擋問題，差異率 ≤ 0.005 | PASS，可發布 |
| 無阻擋問題，0.005 < 差異率 ≤ 0.02 | WARN，可發布，保留品質標記與原因 |
| 差異率 > 0.02 | FAIL，不發布 |
| 重量或 ISO 缺漏 | 金額分析仍可發布；保存單位價值／地圖限制 |
| 國家覆蓋不足 | 依 Day 9 規則將 HHI 顯示值設為 NULL，不單憑此項否決其他金額指標 |

阻擋問題至少包含：World 缺失、重複或非正值，明細缺失，重複 grain，必要金額缺漏或負值，分類／固定維度不符，來源疑似截斷、載入驗證未成功，以及對帳角色尚未確認。後兩項不靠金額剛好相等推定通過；保存 Manifest、載入 audit 與分類依據。

同時存在多個問題時，reason_codes 保存全部原因。若上游失敗而無法產生 candidate，外層執行流程仍須持久化該次 FAIL 嘗試，數值可為 NULL；不能因模型被略過而完全沒有紀錄。

## 4. 組合 candidate mart 與單月分析 SQL

**預計時間：30 分鐘。**

建立 `mart_us_semiconductor_supply_chain_candidate`，整合 fact、夥伴／商品描述、Day 9 指標與本次品質結果。業務 grain 維持 `period_start_date × partner_code × cmd_code × hs_version`；若保存多批 candidate，儲存唯一 key 另含 candidate_batch_id。

至少保留以下內容：

- 金額、市占率、MoM、YoY、有效重量單位價值與各指標原因狀態。
- partner_type、分類狀態、reconciliation_role 與地圖可用性。
- 國家覆蓋、HHI 內部值、HHI 顯示值與可用性。
- PASS／WARN／FAIL、來源 lineage、本次 run_id 與 candidate_batch_id。

月級 World、HHI 或 country_coverage 若出現在每個夥伴列，資料字典須標成不可跨列加總。月級 audit JOIN candidate 後，夥伴列數與金額不能倍增。

在 `docs/evidence/day10-verification.sql` 準備單月展示查詢：

1. 列出 202301 的互斥明細合計、World、差異率、國家覆蓋與品質原因。
2. 查詢已確認國家的金額排名、市占率、MoM、YoY 與單位價值，保留 NULL 原因。
3. 獨立展示該月 HHI 與覆蓋限制，不能因排名查詢只取前幾名而重算完整市場 HHI。
4. 查詢 490 的原碼、原名、對帳角色、金額及分類依據。

目前缺少真實基期時，MoM／YoY 為 NULL 是可解釋結果，不補造歷史數據。

## 5. 分離 gate 與正式發布

**預計時間：45 分鐘。**

本日採單一發布程序、單一 writer，實作順序如下：

```text
選定來源版本與本次 run_id
    → 建立本批 candidate 與對帳結果
    → 持久化 audit
    → 執行阻擋測試與發布 gate
    → PASS／WARN：交易式替換指定月份分區
    → FAIL：留下原因，published 保持原狀
```

正式表命名為 `mart_us_semiconductor_supply_chain`。它由發布程序管理，不是直接引用 candidate 的 view，也不能讓一般 dbt build 或 full-refresh 無條件重建。

本日選用「交易內刪除指定分區，再插入同批已驗證 candidate」的方式；published 表事先建立。交易中的刪除範圍必須包含月份、商品與分類，候選輸入限定 candidate_batch_id 及相同分區。任一步驟失敗須回滾，不能留下已刪除但未補回的資料。

發布前重新核對 gate、candidate 批次、唯一 key 與預期筆數。Audit 通過後 candidate 不可被另一批重建替換；可採固定批次快照，確保「測試的資料」就是「發布的資料」。缺少 audit 或批次不符，一律拒絕發布。

| 情境 | 必須觀察到的行為 |
|---|---|
| 首次 PASS／WARN | 新增該分區，保存 published_at、published_run_id 與品質標記 |
| 已有成功版本，下一次 FAIL | 正式資料與已發布版本時間不變，最近嘗試狀態更新為 FAIL |
| 首次即 FAIL | 不新增分區，但品質摘要仍看得到這次失敗 |
| 成功修訂移除一個夥伴 | 舊夥伴列不殘留；完整替換該業務分區 |
| 替換途中失敗 | 原成功版本完整保留；發布嘗試記錄失敗原因 |
| 同一成功批次重試 | 資料不重複，沿用已記錄的發布識別與時間 |

另保存發布嘗試結果，分開 `quality_status` 與 `publish_status`：品質 PASS 不代表寫入正式表已成功。品質 audit 不可因發布交易回滾一起消失。

建立允許 Dashboard 讀取的品質摘要，顯示已發布資料時間、已發布 run_id、最新嘗試時間與結果。以目標月份／嘗試紀錄為骨架，讓首次失敗的月份也可見。Dashboard 後續只讀正式表與此摘要。

## 6. 固定案例與發布反例驗證

**預計時間：40 分鐘。**

Fixture 必須引用實際 audit、gate 與發布程序，不只驗證孤立的 CASE 公式。每個案例列出預期狀態、原因、是否發布及正式表的預期內容。

| 案例 | 輸入／操作 | 預期 |
|---|---|---|
| 完全一致 | World 100，互斥明細 100 | PASS，差異率 0 |
| PASS 邊界 | 明細分別 99.5、100.5，World 100 | 差異率 0.005，PASS |
| WARN 下界之外 | 明細 99.49，World 100 | 差異率 0.0051，WARN，可發布 |
| WARN 上界 | 明細分別 98、102，World 100 | 差異率 0.02，WARN，可發布 |
| FAIL 邊界之外 | 明細分別 97.99、102.01，World 100 | 差異率 0.0201，FAIL |
| 分母異常 | World 缺失、0、負值、重複 | FAIL；比率 NULL，不倍增 candidate |
| 金額相等但資料違約 | 重複 grain、NULL 金額、錯誤分類或截斷旗標 | 即使表面差額為 0 仍 FAIL |
| 未審分類 | 對帳角色 unresolved | FAIL，原因包含待審代碼 |
| 重疊群組 | 國家 60＋40、已確認重疊群組 100，World 100 | partner_sum 100，群組排除有依據 |
| 國家覆蓋不足 | 國家 80、互斥特殊項 20、World 100 | 對帳 PASS，HHI 顯示 NULL |
| 模組資料不足 | 金額完整但重量／ISO 缺少 | 金額仍可發布，相關模組有狀態 |
| 整月缺資料 | 指定月份無 World 與明細 | 有 FAIL audit，不新增正式分區 |
| 舊版保留 | 先發布 A，再嘗試失敗批次 B | 正式表內容、版本及時間仍為 A |
| 交易回滾 | 在隔離環境模擬刪除後插入失敗 | 正式表與交易前完全一致 |
| 完整替換／重試 | 成功修訂少一個夥伴，再發布同批 | 無殘留、無重複，不影響其他分區 |
| 批次不一致 | 通過 audit 後改用另一批 candidate | Gate 拒絕，不更新正式資料 |

驗證正式表時比對雙向資料差異、grain、筆數、金額、來源批次及發布時間；只比總金額不足以證明舊版本沒被改動。保存實際執行的測試數量，0 tests 不算通過。

## 7. 真實單月驗收、交付與完成條件

**預計時間：20 分鐘。**

使用真實 202301 接受版本跑完 candidate → audit → gate → publish，記錄每步執行結果與批次。若分類或來源證據仍不足，保留 FAIL 及待補事項，不為達成 M2 放寬規則。

| 建議交付路徑 | 內容 |
|---|---|
| `dbt/models/audit/audit_world_reconciliation.sql` | 持久化對帳歷史、原因及來源批次 |
| `dbt/models/audit/_audit__models.yml` | Audit grain、欄位與必要測試 |
| `dbt/models/marts/mart_us_semiconductor_supply_chain_candidate.sql` | 候選分析資料 |
| `dbt/models/marts/_marts__models.yml` | 指標、grain、不可加總欄位與 lineage |
| `dbt/macros/publish_partition.sql` | Gate 核對、交易式分區替換與冪等處理 |
| `dbt/tests/` | 對帳邊界、阻擋條件及候選資料測試 |
| `scripts/publish_partition.py` | 手動執行入口、錯誤紀錄及發布順序控制 |
| `docs/day10-quality-publish-record.md` | 集合、門檻、audit 儲存與發布設計、實際命令 |
| `docs/evidence/day10-verification.sql` | 真實單月展示、正式表前後差異核對 |
| `docs/evidence/day10-verification.md` | Fixture、真實對帳、回滾、版本保留與重試證據 |
| `docs/learning-log.md` | 實際工時、理解、阻礙與待補項目 |

以上是建議新增路徑，尚非可執行介面。實作時沿用 Day 7 的依賴與 dev profile，為 candidate／audit、阻擋測試及發布建立明確的選取與執行順序；先保存 audit，再讓阻擋測試回傳失敗。將驗證過的命令補進操作紀錄，不以一次全專案 build 成功代替發布驗收。

完成後用自己的話回答：

1. partner_sum 與 country_sum 為什麼可能不同？
2. 差異率為 0，為什麼仍可能 FAIL？
3. 對帳 PASS，為什麼 HHI 仍可能是 NULL？
4. 為什麼 audit 必須先保存，且不能隨發布失敗一起回滾？
5. Candidate 與 published 分離，如何保護上一個成功版本？
6. 為什麼「最近品質 PASS」不等於「最新資料已發布」？
7. 為什麼只更新／插入夥伴列可能留下來源修訂已移除的舊資料？

- [ ] 真實單月對帳可追溯到明細與 World 的接受版本。
- [ ] 全體對帳與國家覆蓋分開，490 與 aggregate 的角色有依據。
- [ ] PASS／WARN／FAIL 與 0.5%／2% 邊界測試符合總規格。
- [ ] Audit 保存歷次嘗試，FAIL 有原因且不被測試或交易回滾抹除。
- [ ] WARN 可發布並帶品質標記；HHI 仍獨立遵守覆蓋門檻。
- [ ] Gate 與發布綁定同一批 candidate，FAIL 不修改正式分區。
- [ ] 首次失敗、舊版保留、交易回滾、修訂移除與冪等重試驗證通過。
- [ ] 正式表與品質摘要能分辨已發布版本及最近嘗試結果。
- [ ] 單月分析 SQL、證據與學習日誌完成，未解問題明列待補。

通過以上驗收後才將總規格 M2／Day 10 勾選完成。下一步 Day 11 先回填 3 個月，再完成 2023-01～2024-12 的 24 個月覆蓋，沿用本日品質 gate 與失敗保留規則。
