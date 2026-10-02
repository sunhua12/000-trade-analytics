# 本機持續運行檢查清單

2026-10-02 使用者選擇維持本機 Airflow，接受關機／休眠期間不排程；後續採手動檢查，不建立每日自動檢查。本人展示暫緩，預算通知尚未實收。

## 每日與主機恢復後

在專案根目錄執行：

```bash
docker compose -f docker-compose.yaml -f compose.aws.yaml ps
docker compose -f docker-compose.yaml -f compose.aws.yaml exec -T airflow-worker airflow db check
docker compose -f docker-compose.yaml -f compose.aws.yaml exec -T airflow-dag-processor airflow dags list-import-errors --local
docker compose -f docker-compose.yaml -f compose.aws.yaml exec -T airflow-worker airflow pools get trade_pipeline
docker compose -f docker-compose.yaml -f compose.aws.yaml exec -T airflow-worker airflow dags list-runs trade_monthly_pipeline -o json
```

- [ ] 記錄日期與主機是否曾關機／休眠；Compose 全部必要服務健康，資料庫連線成功，無 DAG 匯入錯誤。
- [ ] monthly 未暫停，Pool 維持 1 slot；沒有外部 candidate writer。Backfill 預設保持暫停，手動回填前先暫停 monthly。
- [ ] 失敗 run 查月份、task、run ID、BigQuery job／audit。未知交易結果先查核，依 [runbook](runbook.md)復原。
- [ ] 檢查本機身分仍可用、Docker 磁碟與日誌空間充足。容器 restart policy 不會喚醒休眠主機。
- [ ] 主機／Docker 曾停止時，先 `docker compose -f docker-compose.yaml -f compose.aws.yaml up -d`，再重做以上檢查；不使用 `down -v`。

## 每月排程後

- [ ] 每月 1 日 00：00（Asia/Taipei）排程後查真實 scheduled run。來源未就緒的略過不是新月份發布成功。
- [ ] 比較來源可用月份與正式發布清單；monthly 最多查看最近 3 期，更舊缺月用 [backfill](day16-backfill-manual.md)處理。
- [ ] 核對 raw grain、兩類來源 attestation、品質狀態、published run ID／時間與 Dashboard。
- [ ] 新夥伴代碼先依官方資料審核，補入版本控制的 seed，再產生新品質 attempt；不放寬 gate。
- [ ] 新發布月份超過 Dashboard 上界時，更新 `TRADE_DASHBOARD_AFTER_LAST_MONTH` 為最新月份的下一月第一日。最大展示範圍仍為 60 月。

## 每次合併與部署後

需已安裝並登入 GitHub CLI（`gh`）；若使用暫存安裝，先加入其所在目錄至 PATH。

```bash
gh run list --branch main --limit 5
gh variable get AWS_AUTO_DEPLOY_ENABLED
aws lambda get-function --profile hua --function-name trade-analytics-ingestion \
  --query 'Code.ResolvedImageUri'
```

- [ ] 受信任 main 分支的 CI 成功；部署符合 workflow path filter，自動部署開關為 true。
- [ ] 保存 Git SHA、Actions run URL 與去敏 verification artifact；核對 Lambda digest 與 Terraform 無 drift。
- [ ] Artifact 預設只保留 7 天，及時保存去敏證據。完整 plan、state、credential 不放進 repository。
- [ ] 若回復，依 [復原手冊](day19-recovery-manual.md)使用仍存在的舊 digest；服務回復與資料復原分開處理。

## 每週與帳期結束後

- [ ] 初步觀察自 2026-10-02 起至 2026-10-16～2026-10-30，逐次填下表，不以空白代替沒有中斷。
- [ ] 下一次未來月排程為 2026-11-01 00：00（Asia/Taipei）；持續觀察至來源可用月份確實自動發布。
- [ ] 核對 AWS／GCP 實際帳單、幣別、稅額與 credits；帳戶總費用無專案歸屬證據時不可直接當專案費用。
- [ ] GCP 本專案 TWD 250 月預算，50％／90％／100％ actual 及 100％ forecast 門檻；本人收到後記錄日期與門檻。不刻意增加支出以觸發。
- [ ] 首個完整持續營運帳期為 2026 年 10 月；11 月帳單可取得後再驗收。Cost Explorer 的 Estimated 與當月累計報表不能代替最終憑據。
- [ ] 定期盤點零流量 revisions、映像與測試 datasets；先保留使用中版本、可復原 digest 與證據，再清理無引用資源。

| 檢查時間 | 主機／服務中斷 | 最新 scheduled run／狀態 | 最新正式月份 | 復原或待辦 | 證據 |
|---|---|---|---|---|---|
| 待本人後續填寫 |  |  |  |  |  |

完成紀錄見 [持續營運紀錄](continuous-operations-record.md)。帳務明細保留於本機 `docs/evidence/continuous-operations/private/`，不推送至公開 repository。
