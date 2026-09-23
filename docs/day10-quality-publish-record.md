# Day 10：對帳與受控發布

實作分支：`quality-release`。本日以真實 `202301／8542／H6` 驗證，24 個月回填仍屬 Day 11。實際個人學習工時未提供。技術驗收數據見 [驗收摘要](evidence/day10-verification.md)。

## 分類決策與對帳集合

`partner_sum` 納入 `reconciliation_role=detail` 的互斥明細；重疊群組保留於 fact，但不加進對帳總額。`country_sum` 僅計原契約中的實際國家／地區。World 不加入明細。

UN Comtrade [官方說明](https://uncomtrade.org/docs/taiwan-province-of-china-trade-data/) 說明 490 的用途，包括臺灣資料與亞洲未指定地區，且相關資料不計入中國資料；既有 [partnerAreas 參考快照](evidence/day08/reference/partnerAreas.json) 的 `isGroup=false` 提供另一項依據。因此本專案將 490 判定為可對帳的剩餘明細，不是整個亞洲的重疊合計。這是根據來源語意及非群組標記做出的模型決策，不是因金額剛好對平才改分類。

490 繼續保留來源名稱 `Other Asia, nes`、`partner_type=special`、`map_iso3=NULL`，不改名成單一國家，也不加入 HHI 國家集合。官方頁面查閱日：2026-09-23（臺灣時間）。

## 來源驗證及發現的舊資料問題

`verify_publication_sources.py` 唯讀取得 S3 data／Manifest，核對 checksum、固定查詢參數、版本、筆數、精確金額、每筆重量／數量及全部 raw 來源欄位。成功後在發布 Dataset 追加 `source_attestations`，附查詢 job ID 與全列 fingerprint。

既有 raw World 的 checksum 是 `e3b0c442...` 佔位值，`ingested_at` 也是舊載入時間。先保留 `legacy_world_lineage_backup`，再以交易只修正這兩個欄位。原金額、重量、數量、grain、來源路徑與 revision 均與原檔一致，沒有變更。修正腳本限定該月份及該佔位值，並以整列快照防止讀取後被其他寫入改動；它是一次性修復工具，不屬日常發布流程。

既有載入 audit 保持原狀，不捏造歷史 load job ID。新的 `snapshot_verified` 明確表示本次 S3 至 raw 的獨立查驗，不宣稱重現 Day 6 載入流程。M1 及其他先前未完成事項維持原狀。

## 模型與程序

| 位置 | 用途 |
|---|---|
| `trade_analytics_day10_dev` | dbt 開發模型及 candidate；一般 build 只更新這裡 |
| `trade_analytics_published.candidate_batches` | 固定候選批次，含 `candidate_batch_id` |
| `batch_inputs` | 同一 BigQuery 交易保存的 candidate、raw、World、載入／查驗證據快照 |
| `quality_audit_history` | 歷次品質判定，不隨發布交易回滾 |
| `audit_world_reconciliation` | 對帳歷史 view；dbt 提供可選的唯讀 view 與測試 |
| `candidate_quality` | 固定候選批次與其品質狀態、原因的關聯 view |
| `mart_us_semiconductor_supply_chain` | 只由發布程序管理的正式表 |
| `publication_attempts` | 發布成功／失敗嘗試；與品質 PASS／FAIL 分開 |
| `publication_quality_summary` | 已發布版本、最近品質判定及最近發布嘗試，各自有 run ID 與時間 |

固定來源月份、商品與版本後，程序按 `freeze → audit → gate → publish` 執行。品質判斷使用 Decimal，容差集中在 `quality.py`：差異率 ≤ 0.005 為 PASS，≤ 0.02 為 WARN，其餘 FAIL。數值判斷前先檢查固定維度、grain、必要金額、分類、映射、來源證據、截斷警戒與 candidate 指標契約；所有原因保留，不只保存第一個錯誤。

全列 fingerprint 驗證查驗證據仍對應目前 raw，避免只比總額看不出資料被置換。Candidate 同時與 raw 比較全部來源欄位。重量、ISO 缺漏及 HHI 覆蓋不足不單獨阻擋金額發布；指標本身仍須遵守 NULL 規則。

發布交易重新確認 audit 唯一且 PASS／WARN、分區一致、批次存在、全批 hash 未改變、grain 唯一。先刪再插入該業務分區，成功才一起記錄發布時間；中途失敗由 BigQuery 回滾。首次 FAIL 不新增分區；後續 FAIL 保留上一成功版本。相同已發布批次重試不改資料與發布時間；未發布的舊批次不可蓋過較新的成功批次。

品質紀錄先獨立提交；發布錯誤另記 `publication_attempts`。若客戶端逾時而無法確認倉儲交易結果，記為 `unknown`，不可當成已回滾；先以保存的 job ID 與發布紀錄確認，再以同一批次重試。已成功批次的重試另記 `already_published`，不改正式資料時間。上游查詢／snapshot 失敗也保存 `upstream_snapshot_failed`。初次部署需先有 dbt candidate schema 才能初始化發布表；日常既有發布表下可記錄上游失敗。

## 日常操作

從專案根目錄執行；使用 Python 3.11、已配置的 AWS CLI 與 GCP ADC。依 `docs/evidence/day08/requirements-python311.txt` 建立 `.venv-dbt`，或使用已整理到主專案的同版本環境。本機 profiles 不納入 Git。

```bash
mkdir -p dbt/local
cp dbt/day10-profiles.yml.example dbt/local/profiles.yml
export DBT_RAW_PROJECT=trade-analytics-508604
export DBT_SEND_ANONYMOUS_USAGE_STATS=false
.venv-dbt/bin/dbt build --project-dir dbt --profiles-dir dbt/local
.venv-dbt/bin/python scripts/verify_publication_sources.py --period 202301
RUN_ID="$(uuidgen)"
.venv-dbt/bin/python scripts/publish_partition.py --period 202301 --run-id "$RUN_ID"
.venv-dbt/bin/python scripts/publish_partition.py --period 202301 --run-id "$RUN_ID" --publish
```

新嘗試使用新 run ID；修正 FAIL 的資料後不能重用舊 ID，舊 audit 與輸入快照會保留。正式發布可用 `--release` 指定獨立 Dataset；不得與 raw／模型 Dataset 相同。SQL 值使用參數，Dataset 名稱有識別字驗證，每個 job 設定 `maximum_bytes_billed=1 GB`。

發布表初始化後，可執行：

```bash
.venv-dbt/bin/dbt build --project-dir dbt --profiles-dir dbt/local --vars '{enable_publication_audit: true}'
.venv-dbt/bin/python scripts/verify_day10.py
# 中斷後接續隔離案例
.venv-dbt/bin/python scripts/verify_day10.py --resume
```

Fixture 僅寫入 `trade_analytics_day10_inputs_fixture` 與 `trade_analytics_day10_publish_fixture`。回滾故障注入僅允許 `_fixture` 結尾的發布 Dataset。驗收工具保存 SQL、參數、job IDs、預期失敗及逐案例 checkpoint。

## 使用限制

- 單一 writer；之後 Airflow Pool／部署鎖需維持同一發布 Dataset 同時只有一個發布程序。尚未宣稱支援多 writer。
- 來源查驗、candidate build 與發布為人工串接，尚非 Day 14 的排程。
- 真實資料只有一個月；MoM／YoY 缺基期維持 NULL，HHI 不因對帳 PASS 就開放。
- 新來源版本須重新查驗原檔及 raw，不能重用不匹配的 attestation。
- Dashboard 只應取得正式表及品質摘要的讀取權限，不能取得 candidate／raw 的寫入權限。IAM 配置不在本次變更中。
