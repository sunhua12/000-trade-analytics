# Minimal ETL 重構與驗收

基準：`044184778ed85d0e939c0cbd729b574bdc6aefcc`。原有測試 58 通過、1 項雲端測試略過。

## 入口依賴與退役決策

| 原入口／狀態 | 處理 |
|---|---|
| scripts/multi_market_pipeline.py | 僅保留為新版 CLI launcher |
| run_batch 閉包、CachedResponse、IngestionService | 改成工作規劃、完整擷取與純驗證函式 |
| batch-ledger／cloud-ledger／pipeline-state | 不再讀寫，保留既有檔案 |
| RawLoader／BatchRawLoader | 合併多市場 RawLoader |
| 單市場 CLI、monthly／backfill DAG、Lambda | 程式與專用 CI 退役，不刪雲端資源 |
| JSON v1 Python 產生器 | 退役，保留前端歷史 fixture 相容測試 |
| build_website／standalone／重複 frontend builder | 改為驗證後 stage 三個公開 JSON；網站用原 Node build |
| API 錯誤分類、S3 Protocol | 有 Retry 消費者／測試注入用途，保留 |
| dbt 舊模型 | 依計畫保留既有模型／測試，主流程只選多市場 |

資料與契約：既有 Raw 路徑及 JSON v2 欄位不變；現有公開資料不由重構測試改寫。沒有執行雲端 migration。

## 驗收對應

| 場景 | 本機回歸證據 |
|---|---|
| T01 API 正常、World／Partner | test_manifest_resume_and_unchanged_refresh |
| T02 HTTP Retry／Timeout | budget／timeout／retry exhaustion tests |
| T03 截斷拆分／單市場失敗 | truncation split tests |
| T04 冪等重跑 | Manifest resume、Loader metadata skip |
| T05 損毀／半寫入 | corruption、uncommitted、atomic local tests |
| T06 新版移除 Partner | 真實隔離 BigQuery：新版移除舊 Partner、跨 HS 替換均通過 |
| T07 舊 Revision／同版衝突 | Loader revision tests |
| T08 缺來源 | unavailable 與既有 NULL fixture；dbt presentation test |
| T09 額度中斷 | Retry／split budget、Pipeline incomplete gate |
| T10 dbt 失敗 | Pipeline failure gate、current pointer failure test |
| T11 版本／Hash 不符 | snapshot verification、混合快照、Pages rollback |
| T12 CLI／DAG | 真實 Airflow：啟用／停用排程、CLI 日期與退出碼均通過 |

Python 不再驗算 HHI／YoY／Coverage，規則集中在 `assert_multi_market_presentation.sql`，保留原始 dbt 測試；新測試涵蓋市場商品粒度的彙總、calendar join、比率、HHI 與缺資料語意。

## 面試導覽

5 分鐘：來源與範圍 → Extract → Local staging／S3 Manifest → BigQuery → dbt → JSON → Pages。

15 分鐘：`run_pipeline()` → `run_batch()` 的 plan／fetch／save → RawLoader 交易 → dbt Mart／品質測試 → JSON 原子發布。

可靠性例子只取 HTTP Retry／截斷、Manifest 冪等、Revision＋完整替換、dbt quality gate、Snapshot atomic publish。移除 Ledger、多重 Hash 與自動歷史回查後，不再聲稱具備那些 recovery 功能。

## 最終驗證結果（2026-10-29）

- 完整 pytest（`--run-integration`）：**69 項通過、0 項略過**，包含真實 Comtrade IC 六碼商品的唯讀整合測試。
- CI 預設模式不啟用即時 API 測試；CI checks、Ruff format／lint、strict mypy 通過。
- 前端 15 項 regression tests 與正式資料的 Node build 通過。公開資料及 Pages workflow 沒有修改。
- 從基準 HEAD 取出舊版程式，以同一固定 Fixture 執行新舊 Export：資料列、NULL、精確小數字串及四份 JSON v2 Schema 完全一致。Snapshot ID／產生時間不列入比較。
- 真實 Airflow 3.3.2 容器在排程啟用／停用兩種設定下成功匯入；檢查器實際呼叫已攔截外部執行的 task function，核對近 3 個月 CLI 範圍、工作路徑、額度與 `--refresh`，並核對退出碼 2 不重試、75 可重試。
- 真實隔離 S3／BigQuery smoke test：首次載入 4 個來源／6 列、相同來源重跑不寫入、新 Revision 移除 Partner、跨 HS 分類版本替換、舊 Revision 拒收全部通過。
- 兩個獨立 Loader 同時觀察舊版本後競爭提交：僅一個成功，另一個因已確認的交易衝突而被拒絕。
- fixture dataset 的 dbt build：**19 個節點全部通過**，包含新 presentation test 及既有 dbt unit test。從真實 Mart 取得 2 列 monthly／3 列 partners，完成 JSON v2 匯出、驗證與公開目錄 staging。
- 在臨時 dbt 專案刻意加入失敗測試，dbt 確實回傳非零；Export 拒絕失敗 build evidence，舊 current pointer 與已發布 JSON 保持不變。
- 隔離測試 dataset 與本次建立的 S3 測試物件已清理；bucket 啟用版本控制，另已刪除兩輪測試各 32 個物件版本／刪除標記。沒有執行正式資料 migration、正式回補或公開部署。

雲端檢查摘要保存於 [minimal-etl-cloud.json](minimal-etl-cloud.json)；完整 dbt logs／artifacts 保存在本機 `data/validation/minimal-etl-cloud-final/`。這些 smoke tests 證明固定隔離樣本的端到端行為，不宣稱已重新匯入或重新驗收全部正式歷史資料。

原 dbt 模型、分析公式、公開前端資料、Pages workflow 及 4 份未追蹤學習計畫未修改。退役入口的專用測試隨入口移除，新測試集中在保留的不變條件與故障反例。


## 第二輪精簡驗收（2026-10-29）

- 移除 `8542`／Raw v2 相容分支及 World 舊零值規則；Fixture 改為支援的六碼 IC 商品。
- JSON v2 共用模型不再含舊商品／固定 HS 限制；typed document 直接驗證資料，移除欄位覆寫的 type ignore 與未使用筆數門檻。
- S3Storage 接收本機已提交來源路徑，上傳原始 NDJSON／Manifest bytes，不重建 Dataset、不重新序列化、不注入 clock。新增非標準空白 NDJSON 的 bytes 保留測試。
- 每批只掃描一次現有來源；提交成功後更新來源集合；BatchResult 不保留解析資料列。重跑仍驗證來源，損毀與衝突仍直接失敗。
- PipelineConfig 集中解析月份、API key、Raw 設定、dbt executable；下游接收已解析設定。Loader decision 僅接收一筆既有聚合來源；SQL 混版與交易內併發檢查保留。
- pytest：71 項通過、1 項即時 API 測試依預設略過；該 Comtrade 唯讀整合測試另行執行通過。Ruff format／lint、strict mypy 通過。
- 前端 15 項 regression tests、build 與真實 Airflow 3.3.2 DAG 檢查通過。
- 使用第一輪保留的基準 Fixture 再次比對：資料列、NULL、精確小數及四份 JSON v2 Schema 與基準完全一致。
- 真實隔離 S3／BigQuery／dbt smoke test 通過，涵蓋完整來源替換、Partner 刪除、HS 版本變更、舊 Revision、併發衝突、JSON v2 發布及 dbt 失敗保護。S3 上傳資料 bytes 與本機完全一致；測試 dataset 與 S3 物件版本已清理。
- 雲端摘要：[minimal-etl-round2-cloud.json](minimal-etl-round2-cloud.json)；本機完整 logs／artifacts：`data/validation/minimal-etl-round2/`。

`--sync-only` 成功表示既有已接受來源處理成功，不表示指定範圍已完整擷取。正式歷史資料未重新匯入，公開部署未執行。

## 第三輪精簡驗收（2026-10-29）

- JSON v2 完整模型集中於 `export/schemas.py`，移除僅補欄位的繼承層；快照 SHA-256 位於驗證模組，解除發布與驗證的雙向相依。
- 本機來源的 bytes 與路徑驗證集中於 `validate_source()`；S3 上傳每次只讀取一份資料及 Manifest，驗證後直接上傳相同 bytes。Pipeline 每批共用 S3Storage。
- 擷取回應先按 Reporter／World／Partner 分組，單一來源保存集中處理；快照月份檢查與 availability 各自一次分組。
- Loader 透過明確型別對照組裝 SQL 投影，完整替換與交易內併發檢查保留。
- 使用實作前保存的完整 src 與實作後 src，分別執行相同固定 fixture：Raw NDJSON bytes、固定時間 Manifest bytes、JSON monthly／partners（含 NULL 與精確小數字串）、四份公開 JSON Schema，以及 Loader 產生的完整 SQL 均完全一致。JSON 比對排除隨機 snapshot_id。
- Python 單元測試 71 項通過、1 項即時 API 測試依預設略過；Ruff 格式／lint、strict mypy 通過。既有測試涵蓋額度與截斷、刷新與損毀、S3 bytes 保留與衝突、Revision 及發布失敗保護。
- 前端 15 項測試與 Node build 通過。第三輪未重跑即時 API、Airflow 容器或雲端 smoke test；前兩輪雲端證據不視為第三輪重新驗證。
- 未修改正式 Raw 或公開資料，未執行正式載入、部署、commit 或 push。

## 四階段持久化交接（2026-10-29）

- CLI 與 DAG 共用 `extract → load → transform → publish`；Airflow 固定四個 Task，不逐市場／月份展開。
- S3 保存批次來源清單、擷取進度、載入 Job 結果、dbt artifacts、JSON v2 與網站建置成果；XCom 只傳成果 URI。完成描述最後寫入。
- 擷取中斷後同 run id 從 S3 恢復；`--extract-only` 維持本機用途，`--sync-only` 先提交既有 Raw 再接續。
- dbt 各次獨立 target／logs；最新嘗試失敗、Raw watermark 改變或成功證據超過 24 小時均不能發布。重跑接受最新倉儲資料，不提供歷史網站重現。
- Python 單元測試：80 項通過、1 項即時 API 測試依預設略過；Ruff 格式／lint、strict mypy、`git diff --check` 通過。涵蓋無本機上游資料接續、擷取續跑、新批刷新、S3 損毀、Raw 更新、dbt 最新嘗試失敗、建置失敗及成果上傳中斷保護。
- 前端 15 項 regression tests 與既有正式快照的 Node build 通過；沒有改寫公開資料。
- 真實 Airflow 3.3.2 容器在排程停用／啟用兩種模式下通過：四個 Task、依賴、pool、重試、CLI 日期與退出碼檢查；task function 的外部命令已攔截，不執行正式 pipeline。
- 第一輪隔離 S3／BigQuery／dbt 驗收通過，涵蓋版本替換、Partner 移除、併發衝突、四階段成果與真實 Node build；先移除本機 Raw 再 load，證明跨階段不依賴本機 Raw。該輪測試 dataset、S3 物件與版本已清理。
- 第一輪本機摘要：`data/validation/four-stage-etl/summary.json`。最終輪亦通過真實 transform 失敗後阻擋舊成功成果、修正後只重跑 transform／publish；摘要見 [four-stage-etl.json](four-stage-etl.json)，完整本機證據位於 `data/validation/four-stage-etl-final/`。最終輪測試 dataset、S3 物件與版本已清理。

- 驗證用 image `trade-airflow:four-stage-validation` 建置成功（image ID：`045fea59bcd3`）；容器內 Node.js `v22.23.4`、dbt Core `1.12.5` 與 BigQuery adapter `1.12.1` 正常執行。以唯讀掛載的最終程式驗證 CLI，並在容器暫存目錄成功建置既有網站。後續已將五個 Airflow 服務切換至此 image，全部 healthy；PostgreSQL／Redis 與憑證掛載保留。
- CI Python job 明確安裝 Node.js 22，供 publish 的真實建置測試使用。

正式 Raw、公開資料及 Pages workflow 未修改；未執行正式回補、部署、commit 或 push。既有未提交變更保留。

### Airflow 執行環境切換完成

- 五個 Airflow 服務已使用四階段 image；預設標籤 `trade-airflow:3.3.2-python3.11` 指向 `sha256:045fea59bcd3a275633423fe97f47ac8c7c86d4a6a95f9f7b0abfef1174ad196`。回復標籤為 `trade-airflow:pre-four-stage-20261029`。
- 切換前確認沒有 running／queued DAG run；使用現有 Compose 專案與 `docker/compose.aws.yaml`，只重新建立五個 Airflow 服務，沒有重建資料庫或 Redis。
- 更新後 worker 的 Python 從掛載的最終 src 載入 pipeline，Node.js 22 可執行；AWS STS 身分確認與 BigQuery `SELECT 1` 唯讀查詢成功。
- Airflow 資料庫內序列化 DAG 確認為 `extract → load → transform → publish`；實際 Task 列表恰好四個，`trade_pipeline` pool 為一槽。排程為 `NullTimetable`，維持停用。
- 所有服務健康檢查通過；未觸發正式 DAG、正式資料回補或公開網站部署。
