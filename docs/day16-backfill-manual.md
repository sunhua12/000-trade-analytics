# Day 16：參數化回填與復原操作

## 執行邊界

`trade_backfill_pipeline` 是 `schedule=None` 的手動 DAG。每次指定 `start_period` 與 `end_period`，最多三個連續完整月份；商品與分類固定為 `8542／H6`。DAG 先查正式發布狀態與兩類來源，再開始任何 ingest／load。若任一待處理月份來源未就緒或檢查失敗，整個 run 在預檢停止。已發布月份預設略過。

Backfill 和 `trade_monthly_pipeline` 共用單 slot `trade_pipeline` Pool，兩者都限制一次一個 task；回填期間 monthly DAG 應保持暫停。每個月依序完成兩類來源的 ingest／load、attest、dbt build、quality audit、gate、publish。前一月的 publish 成功後才選下一月。已發布／未使用的 slot 會回傳狀態 metadata，不執行雲端寫入。

## 觸發與參數

先依 [Airflow 啟動指南](day14-airflow-manual.md)檢查容器、身分、DAG import error、Pool 與 monthly DAG 暫停狀態。確認來源可用、正式表尚未發布及雲端成本後，再觸發：

```bash
docker compose -f docker-compose.yaml -f compose.aws.yaml exec airflow-worker \
  airflow dags test trade_backfill_pipeline \
  -c '{"start_period":"202501","end_period":"202503"}'
```

兩類來源預設 revision 1。如需指定修訂，`revisions` 必須同時包含 `partner_detail`、`world_total` 的正整數。已發布月份只有在 `replay_run_ids` 明確給出該月原發布 ID 且兩者吻合時才會重跑；DAG 不傳 `--allow-republish`，不會以新 ID 替換既有正式版本。

```json
{
  "start_period": "202501",
  "end_period": "202501",
  "revisions": {"partner_detail": 1, "world_total": 1},
  "replay_run_ids": {"202501": "原本的 published_run_id"}
}
```

預檢會拒絕非法月份、未完成月份、反向或超過三個月的範圍、未知參數與不合法 revision。`run_id` 由 Airflow DAG run ID 和月份穩定推導；同一 DAG run 清除失敗 task 後重試時不變。另開 DAG run 會產生新的 ID，因此中斷後應先續跑原 run，不能直接以新的 run 代替。

受控復原演練可對**尚未發布**的單月指定 `"recovery_probe":{"period":"202504","kind":"partner_detail"}`。該 load 首次成功提交後，task 刻意丟失成功回報並進入 retry；第二次沿用同一月份與 `run_id`，應得到 `already_loaded`，再進入品質與發布。此參數只用於明確標記的演練，正常回填勿加入。

## 載入中斷後的查核

1. 在 Airflow Grid 找到失敗 task、月份、`run_id`、stderr 與對應 log。前一月未發布成功時，後續月份不得有寫入。
2. 核對 S3 該月兩種來源的 `data.ndjson`／`manifest.json` 成對存在、身分與 checksum 一致；半套來源不能續跑。
3. 查 BigQuery job history、`trade_raw.audit_ingestion_runs` 及 raw partition，辨認 transaction 尚未提交、已提交但 task 回報遺失，或結果未知。結果未知時先查 job，不能盲目追加。
4. 若來源與 raw 版本相同，重新執行原 task；`RawLoader` 會比對完整來源快照並回傳 `already_loaded`。不同 checksum、舊 revision 或混合版本會失敗，需先查明原因。
5. 兩類載入及 attest 通過後，才讓 dbt、品質 audit／gate 與 publish 繼續。FAIL 不發布；發布結果不明時查 `publication_attempts` 與正式 `published_run_id`／`published_at`。
6. 續跑後核對兩類 raw 的 grain 唯一性、筆數、金額合計、checksum、正式版本和時間；保存 DAG／task／BigQuery job ID。清除 task 前記下原日誌，避免遺失中斷證據。

本機 Docker Compose 關閉時不會排程。三月 smoke test 僅驗證指定區間，不能代表所有積欠月份已處理。SNS email 收件驗證仍依 [Day 15 操作手冊](day15-operations-manual.md)另外完成。
