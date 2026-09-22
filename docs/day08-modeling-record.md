# Day 8：維度與月度進口事實表實作紀錄

實作日期：2026-09-20。實際執行結果見 [驗證摘要](evidence/day08-verification.md)；本文件說明設計，不代替執行證據。

## 模型與粒度

- `country_reference` → `dim_countries`：69 個參考條目，涵蓋真實 202301 的 67 個夥伴，另含 World 0 與 reporter 842。
- `hs_code_reference` → `dim_hs_codes`：H6／8542 一列，保存官方原始描述、父層 85 與層級 4。
- 沿用 `dim_months` 的 24 個月份，不產生零金額交易。
- `fct_monthly_semiconductor_imports`：以 partner staging 為基底，LEFT JOIN 三個維度，每次完整重建。grain 為 `period_start_date × partner_code × cmd_code × hs_version`。
- `audit_partner_mapping_issues`：直接從 staging 與 country 維度產生本次 build 的問題快照；依 run_id、月份、商品、版本、夥伴、來源檔與問題類型彙總，保存觀察時間、筆數、金額及原因。

Reporter 固定 842、flow 固定 M。run_id／revision 屬於 lineage，不加入 grain，避免同一交易因重跑而變成不同交易。Fact 明列全部 15 個來源欄位，保留 NUMERIC、NULL 與追蹤資訊。World 不進入 fact，仍留在獨立 staging。

## 參考資料與審核

原始快照存於 [reference](evidence/day08/reference/manifest.json)，包含來源 URL、下載完成時間（檔案 mtime，UTC）與 SHA-256。`scripts/build_day08_seeds.py` 可離線從固定快照重建 CSV，重建時先核對 checksum；不在 dbt build 時上網。

來源：

- [UN Comtrade partnerAreas](https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json)：夥伴原名、註解、ISO、isGroup 與有效期間。
- [UN Comtrade H6](https://comtradeapi.un.org/files/v1/app/reference/H6.json)：商品原始 text、aggrlevel 與 parent。
- [UNSD M49](https://unstats.un.org/unsd/methodology/m49/overview/)：交叉核對單一國家／地區與 ISO alpha-3。

採用 `country` 的是已逐項檢視的單一夥伴經濟體，包含 Hong Kong SAR、French Polynesia 等地區，不將此清單當成主權國家名單。審核名單固定於 seed 產生腳本，不以三個英文字母或 `isGroup=false` 自動分類未來新碼。Comtrade 數字碼與 M49 數字碼可能不同，例如 USA 的 Comtrade 為 842、M49 為 840；保留來源碼，依已核對的經濟體及 ISO 映射，不做數字碼直接替換。

本次每個選取碼在官方快照均只有一筆，且有效期間覆蓋 2023～2024。日後同碼多筆、有效期間不符或新夥伴出現，產生腳本停止並要求補充審核。沒有建立 SCD 或群組期間 bridge。地圖欄位表示經 M49 核對的 ISO 識別碼，尚未驗證未來採用的地圖幾何檔是否包含所有地區。

CSV 由 csv.DictWriter 產生，所有代碼在 seed 中明確指定 STRING；不補零。空白 map_iso3 經維度轉為 SQL NULL，未使用字串「NULL」。來源與分類、映射依據分欄保存。

## 490、World 與未知項目

490 保留官方 `Other Asia, nes`、來源 ISO `S19`、isGroup=false。依資料契約確認為 `special`，所以分類狀態為 `verified`；這僅代表特殊類型已確認。地圖映射仍為 NULL，對帳角色仍為 `unresolved`，兩者分別出現在 audit。沒有自行更名、映射成其他經濟體或刪除金額。

World 0 標記 `world`／`world`，僅供維度參考，不與一般夥伴一起加總。目前實際夥伴沒有 aggregate；未來群組須審核是否為 overlap，不能與成員同時計入正式總額。未知代碼保持原交易，類型 unknown、狀態 needs_review、對帳 unresolved、地圖 NULL。

未審分類在 Day 8 產生 audit，不作整體 build 阻擋；商品／月份缺漏則驗收失敗。正式對帳及發布門檻留到 Day 10。Audit 一筆交易可以有多種 issue，不能跨 issue 加總金額當成缺漏總額。

## 驗證設計

Seed 與維度鍵分別檢查唯一及非 NULL。HS 與 fact 使用自訂 compound_unique 測試，無外部套件依賴。Fact 保真測試雙向比較全部來源欄位，另比較列數與金額；grain 測試防止 DISTINCT 隱藏重複。每一個 lineage 欄位都包含在雙向比較中。

專用 `trade_raw_day08_fixture` 保存真實來源的隔離副本，`trade_analytics_day08_fixture` 保存測試模型。反例只修改這兩個 Dataset。驗證順序為：

1. 缺夥伴維度：不丟交易、未知旗標正確、audit 可查。
2. 重複夥伴 key：唯一性失敗；刻意生成倍增 fact 後，保真測試也失敗。
3. 同商品新增 H5：H6 仍只匹配 H6，fact 與 baseline 完全相同。
4. 分別缺月份與 HS：交易仍保留，匹配契約測試失敗。
5. 新增未審特殊碼：保留 special／needs_review、地圖 NULL，audit 有未審問題。
6. 移除測試交易並完整重建 fixture，恢復 baseline；真實 World 前後保持一致。

## 重現方式

從專案根目錄執行。`dbt/day08-profiles.yml.example` 為本次 profile 範例，複製到被 Git 忽略的 `dbt/local/profiles.yml`。沿用 ADC，不把金鑰寫入專案。Day 7 的 requirements 與 profile 範例保持原狀；本次 Python 3.11 的實際依賴另存 evidence/day08/requirements-python311.txt。

```bash
python3.11 -m venv .venv-dbt
.venv-dbt/bin/pip install -r docs/evidence/day08/requirements-python311.txt
python3.11 scripts/build_day08_seeds.py
DBT_RAW_PROJECT=trade-analytics-508604 .venv-dbt/bin/dbt seed --project-dir dbt --profiles-dir dbt/local --target dev
DBT_RAW_PROJECT=trade-analytics-508604 .venv-dbt/bin/dbt test --project-dir dbt --profiles-dir dbt/local --target dev --select country_reference hs_code_reference
DBT_RAW_PROJECT=trade-analytics-508604 .venv-dbt/bin/dbt build --project-dir dbt --profiles-dir dbt/local --target dev
DBT_RAW_PROJECT=trade-analytics-508604 .venv-dbt/bin/dbt docs generate --project-dir dbt --profiles-dir dbt/local --target dev
```

完整自動驗收：`.venv-dbt/bin/python scripts/verify_day08.py`。它會重建 dev 與專用 day08 fixture，保存 dbt run-results、查詢 job IDs、audit 與結果摘要，且斷言預期失敗確實發生。不要與其他 dev／fixture build 同時執行。fixture Dataset 保留供檢查，未自動刪除。

## 學習重點與限制

LEFT JOIN 不丟未匹配來源，但重複維度鍵仍會一對多倍增；應先修正維度，而不是對 fact 做 DISTINCT。未知代碼保留才能調查漏映射，也才能保持金額保真。World 與明細混合會重複計算市場總額。

本次只對已載入的 202301 真實資料驗收；不代表其餘 23 個月已載入或完成映射。490 對帳角色與地圖仍待考證；Day 9 應保留覆蓋不足狀態，不能因技術測試通過就將 HHI 當成完整市場結果。實際個人學習工時未提供。
