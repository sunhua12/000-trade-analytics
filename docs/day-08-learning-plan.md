# Day 8：國家／商品維度與月度進口事實表

| 項目 | 內容 |
|---|---|
| 對應計畫 | [20 天實作規格](trade-analytics-spec.md) 的 Day 8 |
| 前置成果 | [Day 7 學習計畫](day-07-learning-plan.md) 的 dbt project、兩個 staging models、dim_months 與測試 |
| 預計投入 | 約 4～4.5 小時；特殊代碼考證與環境除錯另記 |
| 核心目標 | 建立可追溯的維度與 fact，JOIN 後 grain 唯一、資料不遺失，未知代碼可查 |
| 今日交付物 | 國家／商品 seeds、dim_countries、dim_hs_codes、fct_monthly_semiconductor_imports、映射 audit 與驗收紀錄 |
| 目前狀態 | 2026-09-20 技術實作與真實／隔離驗收完成；490 地圖與對帳角色仍待考證。詳見 [驗證摘要](evidence/day08-verification.md) |

今天把「來源交易資料」接上「夥伴與商品的說明」。維度提供分類與描述，fact 保存交易粒度、金額及來源；市占率、MoM、YoY、HHI 留在 Day 9，正式對帳與發布 gate 留在 Day 10。

## 1. 今天要理解的模型關係

**預計時間：15 分鐘。**

```text
官方夥伴參考快照 → 審核後 country seed → dim_countries
官方 H6 參考快照 → HS 8542 seed       → dim_hs_codes
Day 7 月份 spine                    → dim_months
                                          ↓ LEFT JOIN
stg_un_comtrade__partner_trades → fct_monthly_semiconductor_imports
                                          ↓
                            grain／金額保真／映射缺口 audit

stg_un_comtrade__world_totals → 保留為獨立 World 來源，供 Day 9～10 使用
```

| 概念 | 白話說明 | 今日決策 |
|---|---|---|
| Dimension | 描述代碼代表什麼 | 保存名稱、類別、版本及映射依據 |
| Fact | 保存每筆交易的數值 | 每月、夥伴、商品、分類版本一列 |
| Seed | 隨 Git 管理的小型參考 CSV | 固定已審核的代碼與分類決策 |
| Natural key | 來源已有的識別欄位 | 夥伴用 partner_code，商品用 hs_version ＋ cmd_code |
| JOIN fanout | 一筆交易配到多筆維度而倍增 | JOIN 前先測維度 key 唯一 |
| Unknown mapping | 來源有代碼，但維度或分類尚未確認 | 保留交易，顯示狀態並寫 audit |

Fact 的有效 grain 沿用 `period_start_date × partner_code × cmd_code × hs_version`，reporter 固定為 842、flow 固定為 M。`run_id` 與 revision 是追蹤欄位，不加入 grain，避免同一交易因重跑變成多筆。

## 2. 確認前置資料與本日範圍

**預計時間：15～20 分鐘。**

- [x] Day 7 的 dev target 可 build，兩個 staging models 與 dim_months 可查詢。
- [x] 202301 明細及 World 有真實來源與成功 audit；若僅 fixture，明確標記。
- [x] 確認 staging 日期、金額、代碼與 lineage 都符合 Day 7 契約。
- [x] 列出目前已載入資料的 DISTINCT partner_code，以及明細筆數與 NUMERIC 金額合計。
- [x] 查出目前已載入的 `hs_version × cmd_code`，預期只有 H6／8542。
- [x] 確認 raw 的日期篩選仍由 staging 保留，開發模型不寫回 raw。

本日先覆蓋實際出現的所有夥伴碼，另包含 World 0 與 reporter 842 供參考。其他月份回填時重新檢查新代碼；不因 202301 映射齊全就宣稱全部 24 個月皆已覆蓋。

## 3. 建立有來源依據的 country seed

**預計時間：45～55 分鐘。**

從 [UN Comtrade 官方 partnerAreas](https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json) 取得快照，記錄 URL、實際取得時間與 SHA-256。保存使用到的原始欄位及擷取流程，再建立經審核的 `country_reference.csv`；後續 dbt build 讀取 seed，不在每次 build 即時抓取遠端參考表。

| 建議欄位 | 型別／內容 |
|---|---|
| `partner_code` | STRING，與 staging 的代碼格式一致 |
| `source_name`、`source_note` | 官方原名與註解，與自訂顯示名稱分開 |
| `source_iso_alpha3`、`source_is_group` | 保留來源欄位，不直接等同地圖映射或國家分類 |
| `partner_type` | `country`、`world`、`aggregate`、`special`、`unknown` |
| `classification_status` | `verified` 或 `needs_review` |
| `map_iso3` | 已驗證的地圖代碼，不能確認時為 NULL |
| `reconciliation_role` | `detail`、`overlap`、`world`、`unresolved` |
| `source_url`、`retrieved_at` | 名稱／代碼的來源與取得時間 |
| `classification_source_url`、`classification_note` | 分類與對帳角色的依據，必要時引用額外官方說明 |
| `mapping_source_url`、`mapping_note` | 地圖映射依據，未建立映射時說明原因 |

`country` 是本專案已審核、可納入國家分析的單一夥伴經濟體類別；國家或地區的納入規則要寫清楚，不把參考表全部條目當成主權國家清單。`dim_countries` 沿用總規格名稱，但保存所有本次使用的夥伴類型。

分類時逐項判斷：

1. World 0 明確標成 `world`，不作一般交易夥伴加總。
2. 國家／地區須核對來源語意、分析口徑與可用映射；ISO 格式合法只是必要檢查之一。
3. 區域／群組記錄是否與明細重疊；不能與其成員同時加總。
4. 特殊未分配項保留原碼與金額；是否可納入互斥明細對帳需另外考證。
5. 找不到或證據不足的項目標成 `unknown`／`needs_review`，不自行猜名稱或國家。

### 特別練習：490 與 isGroup

本次查閱官方參考表，490 的名稱為 `Other Asia, nes`，來源 ISO 欄位為 `S19`，`isGroup=false`。這說明 `isGroup=false` 本身不能證明一筆代碼是一般國家。[官方參考資料](https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json)

- 保留 490 與官方名稱，依現有 [資料契約](data-contract.md) 歸為特殊代碼。
- 地圖映射尚未有充分依據時，`map_iso3=NULL`；不能直接把 S19 當成標準地圖國碼。
- 官方名稱的確認，不等於國家歸屬或互斥對帳角色已確認；後兩者分別記錄證據及狀態。
- 不自行改名、不刪除金額，也不因它占比較大就改變分類。
- 若投入時間內仍無法確認對帳角色，保留 `reconciliation_role=unresolved`，列入 audit 與 Day 10 待辦；模型可完成技術驗收，分類考證仍標示待補。

官方表含有效日期及歷史條目。今日不做 SCD 或國家群組期間 bridge；審核採用的單一映射能否適用 2023～2024。遇到同碼多筆或期間語意變更，停止該項自動映射並記錄，不能任意取最新一筆。

## 4. 建立兩個維度並沿用 dim_months

**預計時間：30～35 分鐘。**

### dim_countries

透過 `ref('country_reference')` 建立 table，明列欄位與必要型別。`partner_code` 唯一且非 NULL；保留所有分類狀態，不只留下 `country`。

在 seed 設定中明確指定代碼為 STRING，避免自動推斷移除前導零；partner_code 的格式需與 staging 一致，不能擅自將 `'4'` 補成 `'004'`。CSV 由正確 CSV writer 產生，名稱含逗號時需加引號。載入後核對空白映射欄位實際是 NULL，而非字串 `'NULL'`。[dbt seeds 官方文件](https://docs.getdbt.com/docs/build/seeds)

### dim_hs_codes

從 [UN Comtrade 官方 H6 參考檔](https://comtradeapi.un.org/files/v1/app/reference/H6.json) 擷取 8542 的原始描述與階層資訊，建立 `hs_code_reference.csv`：

| 欄位 | 規則 |
|---|---|
| `hs_version`、`cmd_code` | STRING，組合唯一；本日只有 H6／8542 |
| `hs_description` | 官方描述，中文解釋另欄保存，不覆寫原文 |
| `code_level` | 本日為 4，需與商品碼長度及來源層級一致 |
| `source_url`、`retrieved_at` | 實際來源與取得時間 |

透過 `ref('hs_code_reference')` 建立 `dim_hs_codes`。JOIN 必須同時使用版本與商品碼；不能只比 cmd_code，也不能混入 8542 的六碼子項後直接加總。

### dim_months

沿用 Day 7 的 24 列維度，不另建同用途日曆。以 fact 的 `period_start_date` 對應 `month_start_date`。缺交易月份仍只存在於日曆，不補成 0 金額的 fact。

## 5. 建立月度進口 fact

**預計時間：35～45 分鐘。**

模型名稱使用 `fct_monthly_semiconductor_imports`，本日採 table，每次完整重建 staging 設定範圍。尚未引入 incremental，避免在維度學習階段再加入另一套 revision 更新邏輯。

| Fact 欄位群組 | 內容 |
|---|---|
| Grain | period_start_date、partner_code、cmd_code、hs_version |
| 來源維度 | period、reporter_code、flow_code |
| 數值 | primary_value、net_weight、quantity，保留 NUMERIC 與 NULL |
| 夥伴描述 | source_name、partner_type、classification_status、map_iso3、reconciliation_role |
| 維度匹配狀態 | country_mapping_found、hs_mapping_found、month_mapping_found |
| 追蹤資訊 | ingested_at、source_file、checksum、run_id、revision |

實作順序：

1. 從 `ref('stg_un_comtrade__partner_trades')` 明列全部必要欄位，作為 fact 基底。
2. LEFT JOIN `dim_countries`，以 partner_code 比對；維度缺漏時保留來源代碼，類型標成 `unknown`，匹配旗標為 false。
3. LEFT JOIN `dim_hs_codes`，同時比對 hs_version 與 cmd_code。
4. LEFT JOIN `dim_months`，比對月份起始日。
5. 不在 WHERE 篩選維度欄位，避免將 LEFT JOIN 變成實際上的 INNER JOIN。
6. 保留來源金額、重量、數量及所有 lineage，逐欄比對結果。

Fact 保留所有來源明細，包括特殊代碼與可能的 aggregate；不能把 `SUM(fact.primary_value)` 當成已分類的正式國家總額。後續依 `partner_type` 及 `reconciliation_role` 決定分析與對帳集合。

World 不 UNION 到此 fact，也不把 World 總額複製到每一筆夥伴列供加總。Day 9 再從 `stg_un_comtrade__world_totals` 依月份、商品、分類及固定維度匹配分母。

JOIN 前先驗證維度 key 唯一；LEFT JOIN 可以避免丟資料，但不能避免一對多倍增。若維度 key 重複，先修正參考資料，不能對 fact 使用 DISTINCT 掩蓋。

## 6. 建立映射 audit 與保真測試

**預計時間：30～40 分鐘。**

新增開發用途的 `audit_partner_mapping_issues`，從 staging LEFT JOIN 維度產生缺漏或待審項目。以本次 build 的觀察時間、來源 run_id、月份、商品、版本、partner_code、issue_type 記錄問題，附筆數、金額、source_file 與原因。

Issue 至少區分 `missing_reference`、`classification_needs_review`、`reconciliation_unresolved`、`map_unavailable`。有官方名稱但不能畫地圖，不等於交易資料不可信；三種用途的狀態須分開。

Audit 今日可採重建 table，代表目前問題快照；每次驗收將摘要保存至證據，不宣稱已有追加式歷史。若要以測試阻擋未審分類，先建立並保存 audit，再執行阻擋測試，避免失敗後沒有問題清單。

| 測試 | 通過條件 |
|---|---|
| Country key | partner_code 唯一且非 NULL；類型與狀態為允許值 |
| HS key | hs_version × cmd_code 唯一且非 NULL，H6／8542 可匹配 |
| Month key | 沿用 Day 7 唯一、連續 24 個月的測試 |
| Fact grain | 四欄組合唯一且皆非 NULL，reporter／flow 符合固定契約 |
| JOIN 保真 | Fact 與 staging 筆數、金額合計一致，原始欄位雙向差異為 0 |
| Lineage | 每個 grain 的 revision、checksum、source_file、run_id、ingested_at 都與 staging 相同 |
| 未知代碼保留 | 缺 country 維度的列仍存在於 fact，匹配旗標為 false，且出現在 audit |
| 商品／月份缺漏 | 匹配旗標皆為 true；未匹配列仍保留供調查，但驗收失敗 |
| World 分離 | Fact 無 partner 0，獨立 World staging 的資料未改變 |
| NULL 與特殊碼 | 原有 NULL 重量保留；490 的筆數、金額與原碼一致 |

關聯檢查與 `not_null` 要分開。dbt 的內建 relationships test 會排除待測欄位的 NULL；通過關聯測試不等於 key 沒有缺值。[dbt data tests 官方文件](https://docs.getdbt.com/reference/resource-properties/data-tests)

隔離 fixture 至少練習以下反例：

1. 移除某個 country seed 項目：fact 不少一列、不少金額，audit 能找到該原碼。
2. 重複一個維度 key：唯一性測試失敗，不能讓倍增 fact 通過驗收。
3. 同 cmd_code 加入另一個 hs_version：H6 只匹配 H6，不發生倍增。
4. 缺少月份或 HS 維度列：來源交易仍保留，但匹配檢查失敗。
5. 加入未審特殊碼：不被當作 country 或自動賦予地圖 ISO，audit 有明確問題。

測試資料使用獨立 target／Dataset；不要修改真實 raw 或正式參考快照來注入錯誤。

## 7. 執行、交付與完成條件

**預計時間：15～20 分鐘。**

將模型與 seed 加入 Day 7 的 dbt project，確認 `seed-paths` 指向 `seeds`，代碼型別設定完成。以下從專案根目錄執行，沿用 `.venv-dbt` 與 dev profile：

```bash
.venv-dbt/bin/dbt seed --project-dir dbt --target dev
.venv-dbt/bin/dbt test --project-dir dbt --target dev --select country_reference hs_code_reference
.venv-dbt/bin/dbt build --project-dir dbt --target dev
.venv-dbt/bin/dbt docs generate --project-dir dbt --target dev
```

先確認 seed 測試確實有被選取並執行，不以「0 tests」作為通過。第一次 build 後核對真實 202301，再以相同來源重建一次，確認 grain、數值與 lineage 不變。Audit 的觀察時間可以更新，不應混入交易保真比較。

| 建議交付路徑 | 內容 |
|---|---|
| `dbt/seeds/country_reference.csv` | 已審核的夥伴參考與分類決策 |
| `dbt/seeds/hs_code_reference.csv` | H6／8542 描述與來源 |
| `dbt/seeds/_seeds.yml` | Seed 欄位說明與唯一／必要值測試 |
| `dbt/models/marts/core/dim_countries.sql` | 全部使用中夥伴類型的維度 |
| `dbt/models/marts/core/dim_hs_codes.sql` | 版本與商品組合維度 |
| `dbt/models/marts/core/fct_monthly_semiconductor_imports.sql` | 月度明細 fact |
| `dbt/models/audit/audit_partner_mapping_issues.sql` | 缺漏與待審映射快照 |
| `dbt/models/marts/core/_core__models.yml` | 更新模型、欄位、grain 與測試說明 |
| `docs/day08-modeling-record.md` | 維度設計、參考資料來源、490 決策及限制 |
| `docs/evidence/day08-verification.sql` | JOIN 保真、grain、映射缺口與 lineage 查詢 |
| `docs/evidence/day08-verification.md` | 真實 build／重跑與 fixture 反例結果 |
| `docs/learning-log.md` | 實際工時、理解、問題及待補項目 |

來源快照保存於明確記錄的位置，證據附 checksum 與取得時間；CSV 中來源名稱與分類依據也要能追溯。不要在執行日誌中把「計畫完成」寫成「資料考證完成」。

完成後用自己的話回答：

1. Fact 的 grain 為什麼不包含 revision 或 run_id？
2. LEFT JOIN 為什麼仍可能讓金額倍增？
3. 找到官方名稱、確認是國家、可以畫地圖，分別需要什麼證據？
4. 為什麼 `isGroup=false` 不足以將 490 歸成一般國家？
5. 為什麼未知代碼應保留交易並寫 audit，而非 INNER JOIN 丟掉？
6. 為什麼 World 與夥伴明細不能混在一起加總？

- [x] Seeds 附來源、取得時間與分類依據，代碼型別及 key 唯一性通過。
- [x] dim_countries、dim_hs_codes 與 fact 在開發 Dataset build 成功。
- [x] Fact grain 唯一，JOIN 前後筆數、原始欄位與金額完全一致。
- [x] 所有交易的月份及商品可匹配；夥伴缺漏或待審項目可由 audit 追查。
- [x] 490、World、aggregate、國家與未知項目的處理規則清楚，未靜默刪除資料。
- [x] 重建結果一致，維度重複與缺漏的 fixture 反例驗證通過。
- [x] 已保存真實證據、模型說明與日誌；未解決分類問題明列待補。

下一步 Day 9 建立市占率、MoM、YoY、HHI 與有效重量單位價值。分類或覆蓋率仍不足時，依總規格保留資料不足狀態，不能將尚未驗證的 HHI 當成完整市場集中度。
