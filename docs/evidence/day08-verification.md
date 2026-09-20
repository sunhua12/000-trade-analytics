# Day 8 驗證摘要

驗收日期：2026-09-20。由助理實際連線 BigQuery 執行，並非僅整理計畫或沿用 Day 7 回報。完整執行摘要：[verification.json](day08/verification.json)，包含查詢 SQL、job IDs、dbt 節點狀態與業務斷言完成結果。

## 最終結果

- 真實 dev build 與重跑：各 **PASS=70、WARN=0、ERROR=0**，包含 7 個模型、2 個 seeds、61 個資料測試。
- Seed 單獨測試：20 項通過，並非 0 tests。
- 真實資料：202301，67 筆，金額 **2,799,575,181**，31 筆重量 NULL；JOIN 前後一致。
- 全部 15 個來源欄位（含 revision、checksum、source_file、run_id、ingested_at）雙向差異為 0；grain 唯一且必要鍵非 NULL。
- 連續兩次重建 fact 的全部欄位完全一致，觀察時間只存在於 audit。
- 69 個夥伴參考條目、1 個 H6／8542 商品條目；dim_months 仍為連續 24 個月。
- 490 金額 **630,972,428** 保留，地圖為 SQL NULL，對帳 unresolved。Fact 不含 World，真實 World 在隔離驗證前後未改變。
- Fixture 恢復後 **PASS=70**，完整 fact 與其 baseline 一致。
- dbt docs generate 成功，產生 [manifest](day08/manifest.json) 與 [catalog](day08/catalog.json)；catalog 包含 9 個模型／seed 節點。
- [欄位型別](day08/column-types.json) 共 68 個欄位：代碼 STRING，金額／重量／數量 NUMERIC，revision INT64。
- 離線 seed 重建前後位元組一致；Python 腳本 Ruff 檢查與格式檢查通過，pip check 通過，git diff --check 通過。

## 執行環境

Python 3.11、dbt Core 1.12.5、dbt BigQuery 1.12.1；[完整依賴](day08/requirements-python311.txt)。GCP Project：trade-analytics-508604，location：asia-northeast1。

| 用途 | Dataset |
|---|---|
| 真實來源，僅讀取 | trade_raw |
| 真實開發模型 | trade_analytics_dev |
| Day 8 隔離來源副本 | trade_raw_day08_fixture |
| Day 8 隔離輸出 | trade_analytics_day08_fixture |

反例未修改真實 raw，測試完成後已恢復隔離 baseline，專用 Dataset 保留供檢查。本次所有程式及文件在獨立工作目錄內完成，未覆寫主專案工作目錄中的未提交檔案。

## 執行證據

以下時間為各 dbt artifact 的 UTC。負面測試的 fail 是預期結果；驗收腳本確認指定測試確實 fail 且沒有資料庫 error。

| 階段 | 產生時間（UTC） | 結果 |
|---|---|---|
| [dev-seed](day08/dev-seed-run-results.json) | 2026-09-20T07:50:51.116240Z | success=2 |
| [dev-seed-tests](day08/dev-seed-tests-run-results.json) | 2026-09-20T07:50:58.088197Z | pass=20 |
| [dev-build](day08/dev-build-run-results.json) | 2026-09-20T07:51:18.204331Z | success=9、pass=61 |
| [dev-rebuild](day08/dev-rebuild-run-results.json) | 2026-09-20T07:51:39.728218Z | success=9、pass=61 |
| [fixture-baseline](day08/fixture-baseline-run-results.json) | 2026-09-20T07:52:36.264720Z | success=9、pass=61 |
| [fixture-missing-country-tests](day08/fixture-missing-country-tests-run-results.json) | 2026-09-20T07:52:47.091892Z | pass=3 |
| [fixture-duplicate-country-test](day08/fixture-duplicate-country-test-run-results.json) | 2026-09-20T07:53:01.214331Z | pass=9、fail=1 |
| [fixture-fanout-test](day08/fixture-fanout-test-run-results.json) | 2026-09-20T07:53:09.420505Z | fail=1 |
| [fixture-other-hs-version-tests](day08/fixture-other-hs-version-tests-run-results.json) | 2026-09-20T07:53:23.716019Z | pass=2 |
| [fixture-missing-month-preserved](day08/fixture-missing-month-preserved-run-results.json) | 2026-09-20T07:53:37.214597Z | pass=1 |
| [fixture-missing-month-detected](day08/fixture-missing-month-detected-run-results.json) | 2026-09-20T07:53:40.493885Z | fail=1 |
| [fixture-missing-hs-preserved](day08/fixture-missing-hs-preserved-run-results.json) | 2026-09-20T07:53:53.990385Z | pass=1 |
| [fixture-missing-hs-detected](day08/fixture-missing-hs-detected-run-results.json) | 2026-09-20T07:53:56.980453Z | fail=1 |
| [fixture-unreviewed-special-tests](day08/fixture-unreviewed-special-tests-run-results.json) | 2026-09-20T07:54:33.247235Z | pass=2 |
| [fixture-restored-build](day08/fixture-restored-build-run-results.json) | 2026-09-20T07:54:56.033246Z | success=9、pass=61 |

## 隔離反例的實際結果

| 反例 | 驗證結果 |
|---|---|
| 移除 partner 32 的維度列 | fact 保留該列及金額，country_mapping_found=false、類型 unknown；audit 有 missing_reference；3 項相關測試通過 |
| 重複 partner 32 的維度 key | unique 測試預期 FAIL；刻意生成 fact 後，筆數／金額保真測試也預期 FAIL |
| 同商品碼另加 H5 | H6 只匹配 H6；fact 全部欄位與 baseline 相同，2 項測試通過 |
| 移除 202301 月份維度 | 原始欄位保真通過；匹配契約預期 FAIL |
| 移除 H6／8542 商品維度 | 原始欄位保真通過；匹配契約預期 FAIL |
| 新增未審特殊碼 999999 | 交易仍存在，類型 special、地圖 NULL，audit 有 classification_needs_review；保真及 fact 契約通過 |
| 恢復所有 fixture | 全部 70 項通過，fact 與初始 baseline 完全一致 |

## 尚未解決的 audit

真實資料共有 2 列問題，都是 partner 490：`map_unavailable` 與 `reconciliation_unresolved`。每列記錄相同交易金額 630,972,428，不可將這兩列金額加總為缺漏總額。

490 的 `classification_status=verified` 僅代表已依專案契約確認特殊類型，不代表地圖或互斥對帳已確認。沒有 missing_reference 或 classification_needs_review 的真實資料列。

## 實作期間修正

- 初次保真測試使用無 FROM 的條件 SELECT，BigQuery 拒絕；改用單列 UNNEST 後完整 build 通過。[初次失敗證據](day08/initial-build-sql-error-run-results.json) 留存。
- 驗收工具的 World 前後比較起初未帶分區條件，raw 的 require_partition_filter 拒絕查詢；補上 2023～2024 日期範圍。
- 摘要查詢起初使用保留字 rows 作別名；改為 row_count。此錯誤未改變已通過的模型結果。
- 修正後透過 `--resume-fixtures` 接續驗證；先核對已保存的 dev fact SHA-256 確認未變更，再執行反例。
- docs generate 有 table_owner RuntimeWarning，catalog 仍成功產生；詳細見 [日誌](day08/docs-generate.log)。

## 範圍限制與下一步

真實驗收只涵蓋 202301；其餘 23 個月份尚未回填。490 地圖及對帳角色留到 Day 10 考證，地圖幾何覆蓋也需在視覺化階段驗證。未宣稱正式對帳、全期間分類或公開 HHI 的發布門檻已完成。

設計與操作：[Day 8 模型紀錄](../day08-modeling-record.md)。人工唯讀查核：[day08-verification.sql](day08-verification.sql)。本次技術驗收完成，不以執行起訖時間代填使用者學習工時。
