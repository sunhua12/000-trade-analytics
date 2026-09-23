# Day 10 驗收摘要

完成日：2026-09-23（Asia/Taipei）。分支：`quality-release`。以下是實際 S3／BigQuery 操作結果，不是僅離線 fixture 推估。

## 真實資料與發布

| 項目 | 結果 |
|---|---|
| 範圍 | 202301／8542／H6，美國進口 |
| 來源查驗 | 明細 67 筆與 World 1 筆；S3 bytes、Manifest、raw 每筆數值與 lineage 核對成功 |
| 全體互斥明細／World | 均為 2,799,575,181 USD |
| 差異／差異率 | 0／0，品質 PASS |
| 66 個國家／地區合計 | 2,168,602,753 USD |
| 國家覆蓋率 | 0.774618509，約 77.46% |
| 特殊代碼 490 | 630,972,428 USD，保留 special 與 NULL 地圖；對帳角色為 detail |
| 正式發布 | `trade_analytics_published.mart_us_semiconductor_supply_chain`，67 列 |
| 批次／品質 run ID | `real-202301-quality-v1` |
| 發布時間 | 2026-09-23 04:52:24.953 UTC（臺灣時間 12:52:24.953） |
| 正式表與固定候選批次 | 雙向逐欄差異 0；grain、金額、品質狀態與批次皆正確 |
| HHI | 67 列顯示值皆 NULL；覆蓋不足不顯示完整市場 HHI |
| MoM／YoY | 缺少真實比較月份，皆保留 NULL |

[原檔查驗證據](day10/source-verification.json)、[真實 audit 執行](day10/real-audit-jobs.json)、[正式發布執行](day10/real-publication-jobs.json)、[發布後逐欄核對](day10/published-verification.json)、[完整查詢與 job IDs](day10/published-verification-jobs.json)。人工展示查詢：[day10-verification.sql](day10-verification.sql)。

## 修正發現的舊 World metadata

原 raw World checksum 為佔位字串，來源時間為舊載入時間。先保存 `trade_analytics_published.legacy_world_lineage_backup`，核對所有其他欄位與原檔一致，再以交易修正 checksum 與 ingested_at。沒有修改金額、重量、數量或其他來源識別。

[修正前後及 Manifest](day10/world-lineage-repair.json)、[備份／條件檢查／交易 job IDs](day10/world-lineage-repair-jobs.json)。原載入 audit 不覆寫；新的查驗紀錄使用 `snapshot_verified`，不假造歷史 load job。

## 技術驗證

- 完整 dbt build：**92 項成功、WARN=0、ERROR=0、SKIP=0**，包含 11 個模型、2 個 seeds、74 項 data tests、5 組 unit tests。[日誌](day10/final-build.log)、[run results](day10/final-build-run-results.json)。
- 全專案離線 pytest：**173 passed、2 skipped**；2 項既有即時 API 測試預設略過，本日另有實際 S3／BigQuery 驗證。[pytest](day10/pytest.log)。
- Ruff lint／format、完整 mypy、Git whitespace 檢查通過。[lint](day10/ruff.log)、[format](day10/ruff-format.log)、[mypy](day10/mypy.log)。
- Seed 離線重建前後 SHA-256 一致；CSV 統一 LF，避免新修改產生 CRLF whitespace 警告。[seed 重現](day10/seed-reproduction.json)。
- 品質規則測試包含門檻、缺／零／負／重複 World、重複 grain、缺金額、未審分類、來源不符、過期查驗與等總額置換；不只核對 CASE 公式。
- 隔離 BigQuery **36 個不同案例全部通過**，另以獨立 Dataset 完成 **10 個交易案例複驗**：[完整案例](day10/fixtures.json)、[SQL／參數／job IDs](day10/fixture-jobs.json)、[交易複驗](day10/transactions/fixtures.json)、[交易複驗 job IDs](day10/transactions/fixture-jobs.json)。

## 重要發布反例

| 情境 | 已驗證行為 |
|---|---|
| 0.5%／2% 邊界 | 0.5% 為 PASS；2% 為 WARN 並允許發布；超過 2% 阻擋 |
| World 缺失或資料違約 | 保存 FAIL audit，不更新正式表 |
| 整個月份缺資料 | 仍有 audit；首次失敗月份沒有正式資料 |
| 特殊項目補足明細、國家覆蓋不足 | 對帳可 PASS，但 HHI 維持 NULL |
| 已審重疊群組 | 原列保留，對帳合計排除並記錄數量與金額 |
| 已發布批次重試 | 全部資料與發布時間不變 |
| DELETE 後刻意失敗 | 交易回滾，正式表全欄位、版本與時間和原先完全一致 |
| 通過 audit 後修改固定 candidate | 全批 hash 核對失敗，不發布 |
| 成功修訂少一個夥伴 | 舊列不殘留，不影響其他月份 |
| 缺 audit 或分區不一致 | Gate 拒絕，不更新正式資料 |
| 上游 candidate 不存在 | 仍保留 `upstream_snapshot_failed` 品質紀錄 |
| 客戶端逾時 | 離線測試確認記錄 unknown，不冒稱交易已回滾 |

保存的文字日誌已移除 ANSI 色碼及行尾空白；時間、結果與內容保留。

初次隔離測試曾因 INSERT 的無 FROM 條件查詢遇到 SQL 錯誤，已補單列 FROM 並重新驗證。[原始錯誤證據](day10/initial-fixture-sql-error.json) 保留。長時間驗證曾中斷，以逐案例 checkpoint 接續；最終 JSON 的案例結果與 SQL job IDs 為驗收依據，不把日誌中的重複執行次數當成額外案例。

## 範圍

本日完成單月品質與發布技術驗收；未回填其餘 23 個月、未部署 Dashboard 或 Airflow。未測驗使用者本人理解程度，未代填個人學習工時，M1 與先前未完成事項維持原紀錄。下一步 Day 11 先回填 3 個月，再擴至 24 個月，沿用原檔查驗與品質 gate。
