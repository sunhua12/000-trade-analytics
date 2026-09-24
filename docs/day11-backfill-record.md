# Day 11：24 個月回填與修訂驗證紀錄

| 項目 | 結果 |
|---|---|
| 執行日期 | 2026-09-24（台北時間；雲端證據使用 UTC） |
| 範圍 | 202301～202412，24 個連續月份；美國進口、H6／8542、`partner_detail` 與 `world_total` |
| 技術結果 | 48 份來源齊全且已驗證；48 個 raw 分區來源已接受；24 個月份品質 PASS 並正式發布 |
| 個人學習工時、雲端帳單 | 使用者未提供實際學習工時；未取得 AWS／GCP 帳單金額，不以執行時間或 job 數推算費用 |
| 執行方式 | AI 協助撰寫與執行；不代表使用者已親自完成理解測驗 |

## 流程與載入方案

先以既有 Day 10 單月發布 gate 作前置，再串行處理缺少的月份。AWS Lambda 取得兩種查詢並寫入不可變的 S3 `revision=1` 原檔與 manifest；載入前對原始位元組驗證 SHA-256、manifest、固定維度、筆數、金額及 grain。每種來源獨立判斷 revision、checksum 與載入狀態。來源原檔盤點見 [48 份來源](evidence/day11/source-inventory.json)，Lambda 執行狀態見 [擷取結果](evidence/day11/ingest/results.json)。

Day 5 的 S3 Data Transfer Service 單月 PoC 保留為歷史紀錄。Day 11 多月份的實際操作入口改為 `scripts/load_day11_range.py`：Python adapter 透過 AWS CLI 讀取已驗證的 S3 原檔，在 BigQuery 建立暫存資料並以交易式分區替換寫入 raw，同時保存 load audit 與 BigQuery job ID。這是目前手動回填的單一作業方案；沒有並行維護 24 個月的 Transfer 設定。`RawLoader` 使用單一 writer，拒絕同 revision 不同內容及舊版回放；新版完整快照可移除舊版已刪除的夥伴列。這項實作偏離原規格預設的「Transfer → landing → MERGE」，已同步記入[總規格](trade-analytics-spec.md)。

執行順序及重新開始的入口：

```bash
.venv/bin/python scripts/ingest_day11.py
.venv/bin/python scripts/load_day11_range.py
.venv/bin/python scripts/sync_day11_sources.py
.venv/bin/python scripts/attest_day11_range.py
.venv/bin/python scripts/review_day11_sources.py
.venv/bin/python scripts/build_day08_seeds.py
DBT_RAW_PROJECT=trade-analytics-508604 .venv-dbt/bin/dbt build --project-dir dbt --profiles-dir dbt/day11-profile --target day11
.venv/bin/python scripts/publish_day11_range.py --run-suffix final-v1 --evidence docs/evidence/day11/release-final.json
.venv/bin/python scripts/verify_day11.py
```

以上命令須從專案根目錄開始，並具備既有 AWS 與 GCP 身分。`ingest_day11.py` 跳過 S3 已存在的雙檔；`load_day11_range.py` 對相同已接受版本回報 `already_loaded`；`sync_day11_sources.py` 把原檔下載至 git 排除的 `data/` 供獨立查驗與分類審查。每個腳本逐項保存狀態，重啟時先看來源與 audit，避免盲目追加。dbt build 僅更新開發候選表；發布須另經 Day 10 品質 audit 與 gate。兩類來源沒有共用一個可被相互覆蓋的 landing table。

## 試批、回填與分類審查

試批使用 202301、202302、202401：202301 對照 Day 10 已發布基準；202302 檢查連續月份與 MoM；202401 檢查跨年 YoY。[試批載入](evidence/day11/load-pilot.json)與[試批發布](evidence/day11/release-pilot.json)保留逐項 job。202302 初次品質檢查因 18 個來源夥伴碼缺維度對應而 FAIL，未直接放寬規則。比對既存的 Comtrade partnerAreas 與 UN M49 官方快照後，對 24 個月出現的 140 個夥伴碼完成盤點；其中新增 73 個代碼均為有效、非群組且有 M49 對應，審查結果見[夥伴審查](evidence/day11/partner-review.json)。`country_reference.csv` 從 69 列增至 142 列，並由 `scripts/build_day08_seeds.py` 重現。490 按既有 Day 10 規則保留為 special 對帳明細，不當作單一國家。

擴充階段的[48 個載入結果](evidence/day11/load-range.json)為 42 個新載入、6 個 `already_loaded`，無失敗項目；48 份來源均有原檔對 raw 的獨立查驗。最終 dbt build 的 [88 項結果](evidence/day11/final-build-run-results.json)均成功，隨後[23 個新增月份的品質與發布紀錄](evidence/day11/release-final.json)均為 PASS／published；202301 延用 Day 10 已發布版本。先前 202401 試批發布在完整歷史資料建置後重新檢查及發布，確保 MoM 的 202312 基期存在。202302 第一次 raw 載入遇到既有 audit 表缺少新欄位，交易未寫入；補齊欄位後重跑成功。該初次失敗未留下獨立 JSON 檔，不能把它算成具備完整失敗證據的案例。

## 24 個月驗收

[覆蓋清單](evidence/day11/coverage.csv)由固定月份 spine 開始，再接來源、raw、品質及 published，因此缺整月也會留下列。[覆蓋摘要](evidence/day11/coverage-summary.json)及[查核 SQL](evidence/day11-coverage.sql)顯示恰有 24 列，狀態皆為 `published_pass`；每月明細與 World 金額一致，最大差異率 0。正式表與凍結候選表均為 1,560 列，雙向內容差異、重複 grain、無效品質發布各為 0；正式發布月份 24。完整性另由[發布比對 SQL](evidence/day11-publication-check.sql)檢查。逐月最新 run ID、來源 checksum／revision 數、查驗次數與發布時間可從覆蓋清單追溯；load job IDs 保存在載入結果中。

[逐月指標](evidence/day11/metrics.json)與[指標查核 SQL](evidence/day11-metrics.sql)顯示，MoM 非 NULL 1,265 列，YoY 641 列，有效重量單位價值 1,304 列。202301 的 MoM／YoY 均無基期；202302 有 MoM；202401 有 MoM 與 YoY。各月國家覆蓋率為 63.01%～82.92%，未達既定 HHI 顯示門檻，因此 24 個月的可顯示 HHI 均為 NULL，狀態 `insufficient_coverage`。品質 PASS 表示已驗證的明細與 World 可對帳，不代表國家集中度可顯示；本次沒有調整品質或 HHI 門檻。

## 修訂與失敗保留

在自動建立、完成後刪除的隔離 BigQuery Dataset 中執行[修訂 fixture](evidence/day11/revision-fixture.json)：首次載入、同版冪等、同版內容衝突拒絕、交易中故意失敗後回滾、新 revision 刪去一個夥伴、舊版回放拒絕全部通過。新版結果只留下仍存在的夥伴，audit 同時保存 revision 1 與 2。Day 10 的品質 gate 另已驗證 FAIL 不覆蓋正式表。**真實來源此次沒有 revision 2**；真實修訂後的重新建置與發布仍須在發生時再驗收，不能將合成 fixture 當成真實來源修訂。

驗證命令：

```bash
.venv/bin/python scripts/verify_day11_revision_fixture.py
.venv/bin/pytest -q
.venv/bin/ruff check src scripts tests ingest.py
.venv/bin/ruff format --check src scripts tests ingest.py
.venv/bin/mypy src/trade_analytics/warehouse/backfill.py src/trade_analytics/warehouse/gate.py scripts/attest_day11_range.py scripts/ingest_day11.py scripts/load_day11.py scripts/load_day11_range.py scripts/publish_day11_range.py scripts/review_day11_sources.py scripts/sync_day11_sources.py scripts/verify_day11.py scripts/verify_day11_revision_fixture.py
```

本次 Python 測試結果為 194 passed、2 skipped；Ruff check、format check 與 Day 11 檔案的 mypy 檢查通過。專案整體 `.venv/bin/mypy .` 仍因既有舊腳本缺少 `google.cloud` stub、重複模組路徑而失敗，本次未擴大修改舊腳本。Day 12 可直接使用已發布的 24 個月份建置 Dashboard；Day 16 仍須另行實作及驗證 Airflow backfill DAG。
