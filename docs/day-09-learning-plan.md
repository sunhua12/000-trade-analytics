# Day 9：市占率、MoM、YoY、HHI 與有效重量單位價值

| 項目 | 內容 |
|---|---|
| 對應計畫 | [20 天實作規格](trade-analytics-spec.md) 的 Day 9 |
| 前置成果 | [Day 8 學習計畫](day-08-learning-plan.md) 的維度、fact、分類決策與映射 audit |
| 預計投入 | 約 4～4.5 小時；前置补課與資料考證另記 |
| 核心目標 | 將指標口徑寫成 dbt SQL，手算結果一致，缺月、缺分母與覆蓋不足時正確回傳 NULL 及原因 |
| 今日交付物 | 指標模型、資料字典、固定測試資料、驗證 SQL、真實來源抽查及學習日誌 |
| 目前狀態 | 待實作；本文件不代表前置 fact 或本日指標已通過驗收 |

今天完成可檢查的指標運算；Day 10 再建立正式對帳、PASS／WARN／FAIL 與發布流程。Day 9 的開發模型成功 build，不代表資料已可公開發布。

## 1. 先固定指標口徑與模型 grain

**預計時間：20 分鐘。**

| 指標 | 定義 | 無法計算時 |
|---|---|---|
| 進口金額 | 沿用 fact 的 `primary_value` | 必要值缺漏視為資料錯誤，不補 0 |
| 夥伴市占率 | 夥伴金額／同月份、商品、分類版本的 World 金額 | World 缺少、重複或 ≤ 0，回傳 NULL 並記錄原因 |
| MoM | 本月金額／上一日曆月金額 − 1 | 前月缺資料或為 0，回傳 NULL |
| YoY | 本月金額／去年同月金額 − 1 | 去年同月缺資料或為 0，回傳 NULL |
| USD／kg 單位價值 | 金額／淨重 | 淨重缺少或 ≤ 0，回傳 NULL |
| 國家覆蓋率 | 已確認國家的金額合計／World 金額 | 無有效 World 時回傳 NULL |
| HHI | `SUM(POWER(country_share * 100, 2))` | 保留內部值；覆蓋或分類不足時，對外候選值為 NULL |

市占率、成長率與覆蓋率以小數保存，例如 `0.25` 表示 25%；HHI 為 0～10,000 尺度。顯示時才格式化，不先四捨五入市占率再算 HHI。

| 建議模型 | Grain／用途 |
|---|---|
| `int_partner_market_share` | 每月 × partner × 商品 × 分類；連接有效 World 與市占率 |
| `int_partner_trade_metrics` | 同 fact grain；MoM、YoY、單位價值及原因狀態 |
| `int_market_concentration_hhi` | 每月 × 商品 × 分類；國家覆蓋、HHI 與資料可用性 |

Reporter 842 與 flow M 仍是固定契約。若未來擴展 reporter／flow，必須同步擴大 grain、JOIN 與 window partition，不能沿用本日固定假設。

## 2. 確認前置資料與追溯欄位

**預計時間：15～20 分鐘。**

- [ ] Day 8 fact 與 staging 保真，grain 唯一，維度 JOIN 無倍增。
- [ ] World staging 同月份、商品、分類恰一筆，partner 為 0。
- [ ] 國家分類、490、aggregate 與待審狀態可查；未知類型不自動當作國家。
- [ ] 日期範圍沿用 Day 7 的 2023-01～2024-12，dim_months 仍有 24 列。
- [ ] 列出實際已有資料的月份，區分「缺歷史資料」與「指標程式有錯」。
- [ ] 確認來源金額的 USD 及淨重 kg 口徑有資料字典依據；不足時列為待補，不推斷成晶片顆數或單顆價格。

目前可能只有 202301 的真實入倉；MoM／YoY 可先用獨立 fixture 驗證。2023 年缺少 2022 年基期時，YoY 應為 NULL，不為了產生數字而偷偷擴展來源期間。

保留 detail 與 World 各自的 `run_id`、revision、checksum、source_file 及 ingested_at，以不同欄位名稱區分。兩類來源的 revision 不必同號；必須各自是已接受版本且可追溯，不能以同號代替完整性檢查。

## 3. 連接 World 並計算市占率

**預計時間：30～35 分鐘。**

先為 World 建立一個驗證 CTE：按月份、商品、分類分組，保存 `world_row_count`，只有筆數恰一且金額大於 0 時才提供有效分母。重複 World 應觸發錯誤，不以 SUM 或任選一列掩蓋。

從 fact LEFT JOIN 驗證後的 World，使用月份、商品及分類匹配，並驗證兩邊 reporter／flow 的固定值。JOIN 後 fact 筆數、grain 及原始金額必須不變。

```sql
case
    when world_row_count = 1 and world_value > 0
        then safe_divide(primary_value, world_value)
    else null
end as partner_share
```

另設 `share_status`，至少區分 `ok`、`missing_world`、`duplicate_world`、`invalid_world`。`SAFE_DIVIDE` 可處理除零錯誤，但負分母仍可得到數值，因此必須另寫業務條件。[BigQuery SAFE_DIVIDE 官方文件](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/mathematical_functions#safe_divide)

特殊或 aggregate 的原始比值可以保留於內部查核欄位，但標示類型與用途；HHI 只取經確認的國家集合。不將 World 改成已知國家合計，也不將比值大於 1 的異常靜默截成 1。

## 4. 用日曆月計算 MoM 與 YoY

**預計時間：40～45 分鐘。**

今日正式模型採明確日期 self JOIN，避免缺月時 `LAG` 取得錯誤基期。以下為 MoM 的 JOIN 與運算骨架；實作時保留全部必要欄位並透過 `ref()` 引用 fact：

```sql
select
    current_month.period_start_date,
    current_month.partner_code,
    current_month.cmd_code,
    current_month.hs_version,
    current_month.primary_value,
    previous_month.primary_value as previous_month_value,
    case when previous_month.primary_value > 0
        then safe_divide(
            current_month.primary_value, previous_month.primary_value
        ) - 1
    end as mom_rate
from {{ ref('fct_monthly_semiconductor_imports') }} as current_month
left join {{ ref('fct_monthly_semiconductor_imports') }} as previous_month
    on previous_month.period_start_date = date_sub(
        current_month.period_start_date, interval 1 month
    )
    and previous_month.partner_code = current_month.partner_code
    and previous_month.cmd_code = current_month.cmd_code
    and previous_month.hs_version = current_month.hs_version
```

YoY 使用相同 key，日期改為 `INTERVAL 1 YEAR`。月份起始日皆為 1 日，因此可直接以日期運算找基期。[BigQuery DATE_SUB 官方文件](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/date_functions#date_sub)

狀態至少區分 `ok`、`missing_base`、`zero_base`、`invalid_base`。本期真實金額為 0 且基期為正數時，結果是 −1，即 −100%；缺資料不能轉成 0。基期負值或本期必要金額違約時觸發資料測試，不當成合理成長率。

### Window function 練習

另寫練習查詢，以 partner／商品／分類分組，日期排序，對缺少 2 月的 1 月與 3 月使用 `LAG(primary_value)`，觀察 3 月會拿到 1 月。`LAG` 的 offset 是資料列距離，並非日曆月距離。[BigQuery LAG 官方文件](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/navigation_functions#lag)

再將 dim_months 與實際出現的 partner／商品／分類組合形成完整月序列，LEFT JOIN fact 後使用 LAG，保留空月為 NULL，結果應與日期 JOIN 一致。這個練習不回寫 fact。正式模型只維護日期 JOIN 版本。

計算基期時先保留完整可用歷史，再於外層限制顯示月份；若先篩成只有 2024 年再做 window，會遺失 2023 年的 YoY 基期。

## 5. 有效重量與單位價值

**預計時間：20～25 分鐘。**

```sql
case when net_weight > 0
    then safe_divide(primary_value, net_weight)
end as unit_value_usd_per_kg
```

新增 `weight_status`：`valid`、`missing`、`non_positive`；不使用 quantity 代替淨重，不把 NULL 補 0。金額仍可用時，不因重量無效而丟棄該交易列。

按明確的分析集合，例如已確認國家，另查 `valid_weight_row_count`、`total_row_count` 與兩者比值，呈現有效重量筆數比例。名稱須與分母一致；筆數比例不能稱為金額覆蓋率。

若練習月度整體單位價值，分子與分母必須使用同一批淨重 > 0 的列，計算 `SUM(primary_value) / SUM(net_weight)`，不能平均各國比值，也不能用全部金額除以部分有效重量。它仍是貿易組合的 USD／kg，不是晶片單顆售價。

## 6. 國家覆蓋率與 HHI

**預計時間：40～45 分鐘。**

從 `int_partner_market_share` 選出 `partner_type='country'` 且分類已驗證的列；先確認其代表互不重疊的分析單位。分類未知、World、aggregate 與特殊未分配代碼不加入國家平方和，原始交易仍保留供查核。

對每個月份、商品與分類計算：

```text
country_sum = 已確認且互斥國家的 primary_value 合計
country_coverage = country_sum / World
coverage_gap = ABS(1 - country_coverage)
hhi_internal = SUM((country_share * 100)²)
```

以 dim_months 與目標商品 H6／8542 作為月份骨架，再 LEFT JOIN World 及國家彙總，讓整月缺資料也能出現狀態。沒有有效交易時不把空集合的 HHI 補成 0。

建議輸出 `world_value`、`country_sum`、`country_count`、`country_coverage`、`coverage_gap`、`hhi_internal`、`hhi_display_value`、`hhi_status`，並保留未知分類筆數與金額及來源追溯資訊。

| 情境 | 處理 |
|---|---|
| 有效 World、國家集合可用，覆蓋差距 ≤ 0.5% | 可以提供開發用途的 hhi_display_value，仍需 Day 10 發布 gate |
| 覆蓋差距 > 0.5% | 保留 hhi_internal，hhi_display_value 為 NULL，標示資料不足 |
| World 缺少、重複或 ≤ 0 | 覆蓋率與 HHI 為 NULL，記錄分母問題 |
| 國家分類未審核、疑似重疊或無有效明細 | 不提供顯示值，記錄原因；可計算的部分內部值須標示未完整 |
| 覆蓋率 > 1 或 HHI 超出合理範圍 | 保留原始計算供調查，觸發異常檢查，不截斷數值 |

把 `hhi_max_coverage_gap: 0.005` 集中在 dbt vars 或共用設定，不散落魔術數字。覆蓋差距使用絕對值，才能發現超額加總；超額覆蓋的資料異常需調查，即使其差距尚在容許範圍，也不能忽略其他檢查。

490 沿用 Day 8 的特殊代碼決策，不納入已確認國家集合，也不為補足 100% 而自行改名。HHI 的 0.5% 覆蓋門檻與 Day 10 的全體互斥明細對帳是不同檢查；全體明細對得上 World，國家覆蓋仍可能不足。

保留來源金額為 NUMERIC；除法與平方的輸出型別需驗證，固定測試可採明確數值誤差，例如 `1e-6`，不能為了過測試放寬業務覆蓋門檻。

## 7. 固定資料手算與反例測試

**預計時間：30～35 分鐘。**

測試寫入獨立 fixture Dataset／target，與真實資料分開。預期結果手算或獨立列成常數，不用複製同一段模型 SQL 產生 expected。

| 案例 | 輸入 | 預期 |
|---|---|---|
| 完整兩國 | World 100，國家 A 60、B 40 | 市占 0.6／0.4，覆蓋 1，HHI 5,200 |
| 特殊項占比 | World 100，A 60、B 20、特殊項 20 | 國家覆蓋 0.8，內部 HHI 4,000，顯示值 NULL |
| MoM | 前月 100，本月 120 | 0.2 |
| YoY | 去年同月 80，本月 120 | 0.5 |
| 缺月 | 1 月 100、3 月 120，沒有 2 月 | 3 月 MoM 為 NULL，不是 0.2 |
| 零基期 | 前月 0，本月 120 | NULL，zero_base |
| 零本期 | 前月 100，本月 0 | −1 |
| 缺年基期 | 去年同月不存在，但有其他 12 筆資料 | YoY 為 NULL |
| World 異常 | 分別缺少、為 0、為負、重複兩筆 | 市占與可用 HHI 為 NULL，原因可辨識，JOIN 不倍增 |
| 重量 | 金額 120，重量分別 10、NULL、0、−1 | 單位價值分別 12、NULL、NULL、NULL |
| 覆蓋門檻 | World 100，國家合計分別 99.5、99.4 | 差距 0.005 可通過該項檢查；0.006 顯示 NULL |
| 整月空缺 | Spine 有月份，World 與明細均無 | 狀態列存在，金額及 HHI 不補成 0 |
| key 隔離 | 同 partner／月份加入另一商品或版本 | 不跨商品／版本配 World 或基期 |

另驗證：模型 grain、來源欄位與 lineage 不變；異常狀態有理由；比率未提前捨入；HHI 不混入特殊項；有效重量比例分母明確。NULL 的預期結果需使用 `IS NULL` 比較，不能只做數值相減。

用 dbt singular data tests 回傳違規列，0 列才通過；fixture 測試必須引用實際模型邏輯，例如透過獨立 target 的同名上游模型或所用版本支援的 unit tests，不只測孤立的公式片段。[dbt data tests 官方文件](https://docs.getdbt.com/docs/build/data-tests)

## 8. 執行、交付與完成條件

**預計時間：15 分鐘。**

本日先採 view 或完整重建 table，沿用 Day 7～8 的依賴版本與 dev 設定。從專案根目錄執行：

```bash
.venv-dbt/bin/dbt build --project-dir dbt --target dev
.venv-dbt/bin/dbt docs generate --project-dir dbt --target dev
```

依選定 fixture 架構另執行測試，確認有選中且實際執行。真實 202301 至少抽查一個普通夥伴、490、市占分母與重量狀態；沒有真實基期時，把 MoM／YoY 標成資料不足，手算通過不等於真實跨月驗收完成。

| 建議交付路徑 | 內容 |
|---|---|
| `dbt/models/intermediate/int_partner_market_share.sql` | World 驗證、市占及分母狀態 |
| `dbt/models/intermediate/int_partner_trade_metrics.sql` | 日曆基期、MoM、YoY 與單位價值 |
| `dbt/models/intermediate/int_market_concentration_hhi.sql` | 月份骨架、國家覆蓋、HHI 與可用性 |
| `dbt/models/intermediate/_intermediate__models.yml` | Grain、欄位、口徑、依賴與測試 |
| `dbt/tests/` | 對應固定案例與邊界條件的測試 SQL |
| `docs/day09-metrics-record.md` | 指標資料字典、分類集合、門檻及來源限制 |
| `docs/evidence/day09-verification.sql` | 真實抽查、手算與 window function 練習 |
| `docs/evidence/day09-verification.md` | Fixture／真實驗證、build 結果與數值誤差設定 |
| `docs/learning-log.md` | Day 9 實際工時、理解、問題與待補事項 |

以上是預定交付物；模型存在、build 通過與真實資料可用是分開的驗收項目。

完成後用自己的話回答：

1. 為什麼市占率以 World 為分母，而不是已知國家合計？
2. 為什麼缺月時 LAG 的上一筆不等於上一月？
3. 0 金額與缺資料，對 MoM 的影響有何不同？
4. 全體明細與 World 相同，為什麼 HHI 仍可能顯示資料不足？
5. 為什麼國家份額先四捨五入會改變 HHI？
6. 為什麼 USD／kg 不能解讀為晶片單顆售價？

- [ ] 指標 grain、分母、單位與 NULL 規則有明確文件。
- [ ] 三個指標模型在 dev build 成功，JOIN 無倍增且來源可追溯。
- [ ] 市占、MoM、YoY、單位價值與 HHI 的手算結果一致。
- [ ] 缺月、缺分母、零基期、分類不足與覆蓋門檻反例通過。
- [ ] 真實可用月份已抽查，缺基期與未解分類明確列出。
- [ ] 固定資料測試引用實際邏輯，未修改真實 raw 注入錯誤。
- [ ] 資料字典、驗收證據及實際學習日誌完成。

下一步 Day 10 建立 `audit_world_reconciliation`、正式 PASS／WARN／FAIL 與 candidate／published 分離；未通過發布 gate 的開發結果不作為 Dashboard 正式資料。
