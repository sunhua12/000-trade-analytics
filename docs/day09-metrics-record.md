# Day 9：分析指標與固定資料驗收

完成日期：2026-09-21（Asia/Taipei；執行證據為 2026-09-20 UTC）。以 Day 8 提交 `e2b135d` 為基底，分支為 `analytics-metrics`。個人學習工時未提供。

## 交付物

| 模型 | 粒度與用途 |
|---|---|
| `int_partner_market_share` | 月份 × 夥伴 × 商品 × HS 版本；保留 fact 欄位，新增 World 金額、市占率、前月／去年同月金額、MoM、YoY、USD/kg 與市占率狀態 |
| `int_market_concentration_hhi` | 月份 × 商品 × HS 版本；實際國家金額、國家數、覆蓋率、內部 HHI、可顯示 HHI 與可用性原因 |
| `mart_us_semiconductor_supply_chain_candidate` | 與 fact 相同粒度；結合指標與 lineage，尚未通過 Day 10 正式發布 gate |

World 僅作分母，不加進夥伴金額。特殊代碼、未知代碼與未匹配資料仍保留在夥伴模型；HHI 僅計 `partner_type=country`。HHI 模型使用 FULL JOIN，讓只有 World 或只有明細的月份也能顯示原因。兩邊都沒有資料的月份不造交易列，後續 UI 可從 `dim_months` LEFT JOIN 並顯示 NULL。

## 指標口徑與精度

- 金額為來源 `primary_value`，單位 USD；計算維持 BigQuery NUMERIC。
- 市占率為夥伴金額／同月同商品同版本 World；分母缺值、零或負數時回傳 NULL，保留原因欄位。
- MoM／YoY 為本期／前期 − 1，以日曆日期 LEFT JOIN 前一個月／去年同月；夥伴、商品及版本都必須一致。前期缺值或非正值時回傳 NULL。本期為零且前期正值時，結果為 −1。
- Window function 的 `LAG(value, 1)` 代表前一列，`LAG(value, 12)` 代表前十二列；缺月時不能視為前月或去年同月。若使用 LAG，必須先補完整月份 spine 並保持缺值。本次採日曆 join，避免為每個夥伴產生不存在的交易。
- USD/kg 僅在重量 > 0 時計算；重量缺值、零或負值均保持 NULL。此指標不是晶片單顆售價。
- `hhi_raw = SUM((country market_share × 100)^2)`；不將已知國家重新正規化，不裁切異常值。它可能因缺值或異常輸入而不完整，只供內部稽核。
- `country_coverage = country_value / world_value`；只有 World 有效、國家存在、國家金額完整非負、國家分類已審核，且 `ABS(1 − coverage) ≤ 0.005` 時才提供 `hhi`。門檻集中於 `hhi_coverage_tolerance`。
- 市占率、MoM、YoY、覆蓋率皆為比例值，顯示百分比時再乘以 100。NUMERIC 除法保留 9 位小數，HHI 使用該市占率平方；真實資料以 Python Decimal 獨立核對，HHI 絕對容差為 0.00002，其他比例為 0.000000001。
- 月份級 HHI 在 candidate 的每個夥伴列重複，不可跨夥伴 SUM；月份集中度應直接查 HHI 模型。

## 固定資料與手算

`dbt/models/intermediate/_metrics__unit_tests.yml` 提供 5 組 dbt 原生 unit tests。BigQuery 執行合成輸入與固定預期值，不修改 raw 或正式資料。

| 情境 | 固定預期 |
|---|---|
| World 100、兩國 60／40 | 市占率 0.6／0.4，覆蓋率 1，HHI = 60² + 40² = 5,200 |
| World 100、兩國 60／20、特殊項目 20 | 覆蓋率 0.8，內部 HHI 4,000，顯示 HHI 為 NULL；群組與 World 不混算 |
| World 100、國家 99.5 | 覆蓋差距恰為 0.5%，HHI 9,900.25，可提供 |
| World 100、國家 99.4／101 | 差距超過門檻，低覆蓋與超額覆蓋都回傳 NULL |
| 202301 金額 50、202302 金額 100 | 二月 MoM = 1；重量 0 時單位價值 NULL |
| 三月缺月、四月金額 120 | 四月 MoM 為 NULL，不誤用二月 |
| 202401 金額 75、202402 金額 150 | YoY 分別為 0.5；二月 MoM = 1；重量 30 時 USD/kg = 5 |
| 前期零、本期零、World 缺少／零／負數 | 前期零不除；本期零可為 −100% 成長；無效 World 不算市占率 |
| 國家缺金額、負金額、未審核、沒有國家 | 保留內部資訊，但顯示 HHI 為 NULL，附原因 |
| 同月份不同夥伴與 H5／H6 | 前期金額及 World 分母不跨夥伴或版本混用 |

另外有 candidate 雙向來源保真測試、grain 唯一性、狀態值、NULL 邊界等資料測試。既有 Day 7／8 測試一併執行。

## 真實驗收

在獨立 `trade_analytics_day09_dev` Dataset 建置，唯讀來源為既有 `trade_raw`。未修改 Day 8 dev／fixture Dataset，也未建立正式 published mart。

- 完整 `dbt build`：10 個模型、2 個 seeds、71 項 data tests、5 組 unit tests，合計 **PASS=88、WARN=0、ERROR=0、SKIP=0**。
- 真實 202301：fact 與 candidate 均為 67 列，全部 fact 欄位與 lineage 一致；市占率、MoM／YoY 與單位價值經 Decimal 核對。
- World 金額：2,799,575,181；66 個已審國家／地區金額：2,168,602,753；國家覆蓋率：0.774618509。
- 490 保留原名及金額，未算入實際國家。內部 HHI：992.713039409；`hhi_status=insufficient_coverage`，對外 HHI 為 NULL。
- 真實資料只有 202301，MoM／YoY 沒有比較月份，重量也缺值；有效成長率與重量計算由合成資料驗證，不宣稱已有完整 24 個月。
- 新增驗證腳本的 Ruff 檢查與格式檢查、`git diff --check` 通過。

證據：[建置日誌](evidence/day09/build.log)、[dbt 執行結果](evidence/day09/build-run-results.json)、[真實查詢、job IDs 與 Decimal 核對](evidence/day09/verification.json)。

## 重現

沿用 Day 8 已驗證的 Python 3.11／dbt 環境及 ADC，依 `docs/evidence/day08/requirements-python311.txt` 建立 `.venv-dbt`。將 `dbt/day09-profiles.yml.example` 複製到被忽略的 `dbt/local/profiles.yml`，從專案根目錄執行：

```bash
DBT_RAW_PROJECT=trade-analytics-508604 DBT_SEND_ANONYMOUS_USAGE_STATS=false .venv-dbt/bin/dbt build --project-dir dbt --profiles-dir dbt/local
.venv-dbt/bin/python scripts/verify_day09.py
```

只重跑固定資料測試（前置模型已建置）：

```bash
DBT_RAW_PROJECT=trade-analytics-508604 .venv-dbt/bin/dbt test --project-dir dbt --profiles-dir dbt/local --select test_type:unit
```

`scripts/verify_day09.py` 只讀取隔離 Dataset，核對現有真實月份並寫入本機證據；不是發布工具。Day 10 接續對帳 audit、PASS／WARN／FAIL 與正式發布 gate；Day 6 延後項目及 M1 狀態維持原紀錄。
