# Day 3 驗證紀錄

離線複驗日期：2026-09-11。真實 API smoke 日期：2026-09-10。

| 指令 | 結果 |
|---|---|
| `.venv/bin/mypy .` | 通過，24 個來源檔案 |
| `.venv/bin/ruff check src tests ingest.py` | 通過 |
| `.venv/bin/ruff format --check src tests ingest.py` | 通過，23 個檔案格式符合 |
| `.venv/bin/pytest tests/unit -q --cov=trade_analytics.ingestion --cov-report=term-missing --cov-fail-under=90` | 134 passed，ingestion 覆蓋率 97.02%，超過 90% 門檻 |

Ruff 排除 `tests/TEST` 的個人字典轉換檔案；正式單元與整合測試未排除。此紀錄未宣稱使用者已逐項理解測試。

## 驗證範圍

- H6、固定維度、必要金額、World 正值驗證；缺少重量與 ISO、特殊夥伴 490 及明細 0 值保留。
- 原始 HTTP JSON 小數精確解析、序列化與重新讀取，超過 Decimal 預設 28 位精度的金額合計。
- Schema 2.0.0、十進位字串正規化、穩定 checksum。
- 本機與假 S3 client 的重跑不改檔、衝突拒絕、部分檔案恢復、Manifest 身分核對、商品隔離及 revision 保留。
- CLI／Lambda revision 驗證與傳遞。

## 真實 API 與本機輸出

[完整 smoke 證據](day03-smoke.json) 保存命令、輸出路徑、checksum、Manifest、首次及重跑狀態。

| 月份／商品 | 類型 | 筆數 | 金額合計 | 首次／重跑 |
|---|---|---:|---:|---|
| 202301／8542 | partner_detail | 67 | 2,799,575,181 | success／already_exists |
| 202301／8542 | world_total | 1 | 2,799,575,181 | success／already_exists |

兩組皆為 H6、schema 2.0.0；已核對 checksum、金額字串、筆數、合計，以及重跑前後檔案內容與修改時間不變。Day 1／Day 2 的既有輸出保持不變。

真實 S3／Lambda 部署屬於 Day 4；本次不代表雲端驗收完成。儲存採單 writer，兩個檔案不構成整體原子交易。24 個月完整回填與國家映射亦不在本次驗收範圍。
