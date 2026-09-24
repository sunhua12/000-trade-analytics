# Day 12：Streamlit Dashboard 實作與驗收

| 項目 | 結果 |
|---|---|
| 驗證日期 | 2026-09-24（Asia/Taipei） |
| 分支 | `streamlit-dashboard-foundation` |
| 資料來源 | `trade_analytics_published.mart_us_semiconductor_supply_chain` 與 `publication_quality_summary` |
| 資料範圍 | 202301～202412、商品 8542、H6；24 個正式發布月份 |
| 實際學習工時 | 使用者未提供；未以程式執行時間代填 |
| 查詢與 UI 證據 | [固定條件驗證](evidence/day12-verification.json)、[Streamlit 操作驗證](evidence/day12-ui-verification.json) |

## 完成內容

新增 `dashboard.py` 及 `trade_analytics.dashboard.queries`。畫面提供起訖月份、Partner 多選與 Top N，呈現已發布月份、期間 World 金額、來源國／地區金額排名、月度進口趨勢，以及最新品質嘗試與正式發布狀態。未選 Partner 時代表全部已確認國家／地區；490 等特殊代碼不進入來源國排名。商品與分類固定顯示為 `8542／H6`。

所有正式表查詢都有 `period_start_date` 起日與次月月初上界，品質摘要 view 以月份字串限制範圍；日期、Partner 與 Top N 使用 BigQuery 查詢參數。只允許兩個正式資料表名稱，單次查詢預設 `maximum_bytes_billed=1,000,000,000`，資料快取 TTL 預設 3,600 秒，並提供手動清除。ADC 提供本機身份，程式沒有金鑰。World 金額先按月取一次再加總，避免因夥伴列重複而放大分母；圖表缺月保持空值，不補 0。

初次真實查詢發現空 Partner 陣列在排名 SQL 回傳 0 列，已改為明確的 `all_partners` 布林參數。修正後真實查詢回傳 139 個可選國家／地區與 10 列排名。這個情境已加入單元測試。

## 驗收結果

- 真實 BigQuery 查詢回傳 24 個月份；期間 World 金額為 76,449,272,983 美元，品質摘要 24 列，已發布品質均為 PASS。固定條件 `202301～202412／8542／H6／partner 458` 的 Dashboard 排名、24 個逐月趨勢加總及獨立 SQL 均為 **19,277,096,395 美元**。獨立查詢 job ID 與每項查詢處理量見 [JSON 證據](evidence/day12-verification.json)。不存在的夥伴 `999` 回傳 0 列。
- Streamlit `AppTest` 以正式資料執行，無例外或錯誤；畫面顯示 24 個月份、最新成功發布月份 2024-12 及正確 World 金額。切換起日為 2024-01 後顯示 12 個月份；選 Partner 458 時排名為 1 列、品質摘要為 12 列。Top N 可從 10 改為 5；逆序日期顯示阻擋訊息。逐項數值保存在[UI 驗證 JSON](evidence/day12-ui-verification.json)。
- 隔離的 UI fixture 驗證空排名／趨勢／品質不 crash、BigQuery 權限錯誤顯示訊息，以及「已發布 PASS、最新嘗試 FAIL」兩個狀態分開呈現。處理量上限錯誤另驗證為可辨識訊息。這些是模擬情境，未修改正式發布表。
- 本機 Streamlit 伺服器成功啟動，`/_stcore/health` 回傳 `ok`，驗證後已停止。Dashboard 專用測試為 13 passed；全專案 Python 測試為 203 passed、3 skipped（其中 1 個因一般 `.venv` 未安裝 Dashboard 選用依賴）。新增檔案的 Ruff 與 mypy 檢查通過。

## 限制與下一步

目前是 Day 12 的基本分析畫面。YoY、HHI／國家覆蓋說明、資料新鮮度、地圖／散佈圖及三項分析觀察留到 Day 13。Day 11 真實資料的 HHI 全部因國家覆蓋不足而不可顯示；Day 13 不能把 NULL 畫成 0。圖表為顯示使用浮點數，精確金額以 BigQuery `NUMERIC` 核對。雲端帳單費用及使用者實際學習工時未提供；`maximum_bytes_billed` 是單次查詢處理量限制，不是帳單上限。
