# Day 12：Streamlit 查詢、篩選與基本分析畫面

| 項目 | 內容 |
|---|---|
| 對應計畫 | [20 天實作規格](trade-analytics-spec.md) 的 Day 12 |
| 前置成果 | [Day 11](day-11-learning-plan.md) 已發布 202301～202412 共 24 個月；[正式資料驗收](day11-backfill-record.md)為 1,560 列、24 個月份品質 PASS |
| 預計投入 | 約 3.5～4.5 小時；首次安裝、雲端登入或權限排障另記 |
| 核心目標 | 從已發布資料建立可篩選、可追溯且查詢量受控的本機 Dashboard 初版 |
| 今日交付物 | Streamlit 應用、參數化唯讀查詢、基本圖表與品質摘要、執行說明、核對證據及學習紀錄 |
| 目前狀態 | 技術實作與真實資料驗收完成；見[執行紀錄](day12-dashboard-record.md)與[固定條件證據](evidence/day12-verification.json) |

今天先把 Day 11 的正式分析資料變成能操作的頁面。畫面包含日期區間、Partner、Top N 篩選，以及金額排名、月度趨勢與品質摘要。本計畫已依[執行紀錄](day12-dashboard-record.md)完成；以下保留原定步驟作為學習對照。Day 13 再完成 YoY、HHI／覆蓋狀態、資料新鮮度及視覺化解讀，達成本機展示里程碑 M3。

## 1. 確認資料來源與欄位口徑

**預計時間：20～30 分鐘。**

- [x] 確認 ADC／BigQuery 唯讀查詢可連線，查詢 location 為 `asia-northeast1`，不在程式或 Git 放入服務帳號金鑰。
- [x] 只讀 `trade_analytics_published.mart_us_semiconductor_supply_chain` 與 `trade_analytics_published.publication_quality_summary`；不讓 UI 直接查 raw、dbt candidate 或可修改發布狀態的程序。
- [x] 以正式表查詢核對可用月份、商品 `8542`、分類 `H6`、夥伴列數與 `quality_status`。Day 11 的 1,560 列與 24 個月是起始基準，實作時仍以當下查詢結果為準。
- [x] 盤點 `period_start_date`、`partner_code`、`source_name`、`partner_type`、`primary_value`、`market_share`、`mom`、`yoy`、`world_value`、`country_coverage`、`hhi`、`hhi_status`、`published_at` 與品質摘要 view 的實際欄位及型別。

正式表的 grain 是 `period_start_date × partner_code × cmd_code × hs_version`。`world_value`、`country_coverage` 與 `hhi` 是月份級數值，會重複出現在每個夥伴列；不能對它們跨夥伴 `SUM`。490 是特殊互斥明細，可留在總額及品質分析中，但「來源國 Top N」只取 `partner_type='country'`，不可將它畫成單一國家。

## 2. 建立最小 Streamlit 應用與查詢邊界

**預計時間：45～60 分鐘。**

新增獨立的 Dashboard 程式入口與安裝／啟動說明。BigQuery client 使用本機 ADC；專案、Dataset、location、單次查詢處理量上限與快取 TTL 由設定提供，Dataset／table 名稱採固定允許清單，不由使用者輸入直接拼接。MVP 商品與分類在頁面明示為 `8542／H6`，不開放切換。

查詢層至少提供以下三種唯讀結果：

| 查詢 | 用途與必要限制 |
|---|---|
| 日期／夥伴選項 | 從已發布資料取得可選月份與夥伴；控制查詢處理量，不掃描 raw |
| 金額排名與月度趨勢 | 以 `period_start_date >= @start_date AND period_start_date < @end_exclusive` 篩選實體分區；固定商品與分類，夥伴選擇及 Top N 使用參數 |
| 品質摘要 | 從 `publication_quality_summary` 讀取已發布版本及最新品質／發布嘗試；用月份範圍與固定商品、分類限制，不將最新品質 FAIL 誤寫成「正式資料已更新」 |

日期選擇只允許可用月份範圍、起日不得晚於迄日；UI 顯示包含迄月，SQL 以次月月初作 exclusive end。BigQuery 使用 `ScalarQueryParameter`／`ArrayQueryParameter` 傳入日期、夥伴代碼與 Top N；Top N 限制在合理整數範圍，例如 5～30。每個查詢設定 `maximum_bytes_billed`，錯誤訊息能區分權限、超過處理量上限與其他查詢失敗。先用 dry run 或 job 統計核對日期條件確實可裁剪分區，再記錄實際處理量；不要把畫面上的篩選誤認為倉儲端已限制讀取。

對結果使用可設定 TTL 的快取，預設 3,600 秒；快取鍵包含完整篩選值與固定資料範圍。頁面提供重新整理入口，以便新的正式發布後清除舊結果。憑證與 BigQuery client 不序列化進資料快取；記錄資料最後發布時間，避免使用者把快取讀取時間當成資料發布時間。

## 3. 製作篩選與基本畫面

**預計時間：60～75 分鐘。**

- [x] 側欄提供起訖月份、Partner 多選與 Top N；若未選 Partner，清楚定義為「全部符合條件的已確認國家」。夥伴名稱顯示時保留代碼，避免同名或缺名稱無法辨認。
- [x] 主畫面顯示期間、固定商品／分類、已發布月份數、最新成功發布月份與目前套用的篩選條件。
- [x] 來源國排名依選定期間的 `primary_value` 加總排序，Top N 只控制顯示筆數；總額或市占率的分母須明示，不把 Top N 的合計當成 World 總額。必要時把「選定來源國合計」與「全部 World 金額」分開標示。
- [x] 月度趨勢依日曆月份排序，可顯示所選夥伴的進口金額；多夥伴合計只加總夥伴金額，不加總重複於夥伴列的 World。缺月顯示為無資料，不補成 0。
- [x] 品質區塊顯示各月 PASS／WARN、最新品質嘗試狀態、最新成功發布時間及異常原因；最新嘗試與已發布版本分開呈現。

金額的幣別、統計單位及圖表口徑寫在畫面上；百分比以數值計算後再格式化。初版以表格與簡單趨勢圖完成互動查詢，YoY、HHI 與進一步圖表留到 Day 13。空結果顯示清楚的提示，選項保持可調整；缺 `mom`／`yoy`／重量或 HHI 的 `NULL` 不轉成 0。

## 4. 驗證篩選、成本與失敗情境

**預計時間：40～50 分鐘。**

選一組固定條件，例如 `202301～202412／8542／H6／一個已確認國家`，將 Dashboard 顯示的逐月金額及期間合計，與相同條件的 BigQuery SQL 人工核對。另選跨年區間檢查月份順序、迄月包含規則與 Top N 排名；確認切換 Partner 及日期後，結果確實變動且沒有舊快取污染。

至少測試以下情境並保存畫面或結果摘要：

| 情境 | 預期結果 |
|---|---|
| 正常日期／Partner／Top N 操作 | 數值與固定 SQL 一致；查詢參數及處理量可查 |
| 無符合資料或空夥伴集合 | 顯示空狀態，不 crash、不顯示虛構的 0 |
| 迄月早於起月或 Top N 超出範圍 | 在送出 BigQuery 查詢前阻擋 |
| BigQuery 權限失敗或超過 bytes 上限 | 顯示可理解的錯誤，不沿用舊結果冒充成功 |
| 新品質嘗試 FAIL、既有月份仍已發布 | 同時顯示最新嘗試與已發布版本，不誤稱最新嘗試已發布 |

若當日沒有真實 FAIL 月份，最後一項可用受控的隔離資料或查詢層固定 fixture 驗證 UI，並明確標記為模擬案例。不要修改正式發布表來製造 Dashboard 測試資料。記錄查詢 job ID 或 dry-run 結果、固定 SQL 的核對數值，以及本機執行方式；實際雲端費用若無帳單資料，不自行推估為已驗收。

## 5. 交付、學習整理與完成條件

**預計時間：20～30 分鐘。**

| 預計交付 | 內容 |
|---|---|
| Dashboard 程式及依賴設定 | Streamlit 入口、唯讀參數化查詢、TTL、查詢上限與錯誤處理 |
| 本機使用說明 | ADC 前置、安裝與啟動命令、設定項、資料集與權限需求 |
| 驗收證據 | 固定條件 SQL／畫面核對、空結果與失敗情境、查詢成本或 dry-run 紀錄 |
| [學習日誌](learning-log.md) | 實際日期與本人投入時間、設計理由、驗收結果及待解問題 |

完成後用自己的話回答：

1. 為什麼 Dashboard 只能讀正式 mart，而不能直接讀 candidate？
2. 為什麼 `world_value` 不能在夥伴列上直接加總？
3. UI 已有日期篩選，SQL 為何仍要明確加入 `period_start_date` 分區條件？
4. 快取中的畫面時間、最新品質嘗試時間、正式發布時間各代表什麼？
5. 490 為什麼可參與對帳，但不能列入來源國排名？

- [x] 本機 Dashboard 可啟動，且只查已發布資料與允許的品質摘要。
- [x] 日期、Partner 與 Top N 篩選生效；查詢使用參數、日期分區條件與 bytes 上限。
- [x] 基本金額排名、月度趨勢及品質摘要可讀；空結果與查詢錯誤不 crash。
- [x] 至少一組固定條件與 BigQuery SQL 人工核對一致，保存查詢與畫面證據。
- [x] 文件與日誌標明已完成事項、未驗收限制及 Day 13 待補視覺化。

以上均有實測證據後，再更新[總規格](trade-analytics-spec.md)的 Day 12 狀態。Day 13 接續完成 YoY、HHI／覆蓋說明、資料新鮮度與三項有數據支持的觀察。
