# 操作手冊索引

先確認 target、目前來源／發布版本及身分，再執行寫入操作。以下連結沿用已實測入口；2026-10-02 monthly 已恢復，43 月資料及真實 scheduled 發布驗證完成。日常採 [手動檢查清單](continuous-operations-checklist.md)，實測範圍見 [營運紀錄](continuous-operations-record.md)。

| 情境 | 入口與所需身分 | 判斷／證據 |
|---|---|---|
| 乾淨安裝／重建 | [重建手冊](day19-recovery-manual.md)；Python 3.11、Docker、Terraform，重新登入既有 AWS／GCP 身分 | clean CI／容器 smoke／隔離 plan、apply、無 drift；共享 bootstrap 範圍明列 |
| AWS bootstrap／接管 | [AWS 管理流程](../infrastructure/aws/README.md)；受控 bootstrap 身分 | backend／OIDC 先建立；核對 state key、saved plan target，不以正式 destroy 證明重建 |
| CI／OIDC 部署 | [CI／CD 手冊](day17-cicd-manual.md)及 [復原紀錄](day19-run-record.md)；受限 GitHub main subject | 遠端 CI、digest 對應、apply 與獨立無 drift；main 自動部署已啟用，push 驗證成功 |
| 本機 Dashboard | [README](../README.md#本機-streamlit-dashboard)；ADC 與 BigQuery query／published 唯讀 | 頁面／固定 SQL 一致；空資料、授權錯誤與 HHI 狀態明確 |
| Cloud Run 部署／停止 | [Cloud Run 手冊](day18-cloud-run-manual.md)；GCP 部署身分與專用 runtime SA | immutable digest、revision、流量、Live UI；停止與清理依服務手冊 |
| 單月流程 | [Airflow 手冊](day14-airflow-manual.md)、[排程手冊](day15-operations-manual.md)；本機 AWS profile／ADC 唯讀掛載 | 來源配對 → load → attest → dbt → audit → gate → publish，task 與 job 可追溯 |
| 歷史積欠 | [Backfill 手冊](day16-backfill-manual.md)；pipeline 身分 | 每批最多三個連續完整月份，共用單 slot Pool；手動回填前先暫停 monthly，完成獨立查核後再恢復 monthly |
| 告警定位 | [告警手冊](day15-operations-manual.md)、[故障復原手冊](day19-recovery-manual.md)；CloudWatch／SNS 讀取權 | Alarm／時間／函數 → request ID／run ID → manifest／load／audit；SNS action 與實收分開核對 |
| 品質 FAIL | [發布紀錄](day10-quality-publish-record.md)、[回填紀錄](day16-run-record.md) | 正式版本不變，查 reason_codes／來源／seed；修正根因後新 attempt，不放寬 gate |
| 載入回報遺失 | [Backfill 手冊](day16-backfill-manual.md) | 先查 job／audit／raw grain；already_loaded 復原，未知交易結果不能假設回滾 |
| 同月安全重跑 | [Day 19 正式重跑證據](day19-run-record.md#3-品質停損與正式完整重跑) | 使用原發布 ID；raw grain／金額／published_run_id／published_at 不變 |
| 來源修訂 | [資料契約](data-contract.md)、[24 月紀錄](day11-backfill-record.md) | 新 revision 保留原檔、重新 load／attest／品質 gate；不覆寫 S3 舊版 |
| Lambda／Cloud Run 回復 | [重建復原手冊](day19-recovery-manual.md) | Lambda 以 Terraform 回復舊 digest；Cloud Run 舊 digest 新 revision 並切流量，不能宣稱撤銷資料發布 |

首次設定與日常操作分開。個人 profile／ADC、SNS endpoint、state／plan 不提交 Git。資料 lineage 的 run_id、image 的 Git SHA／digest 與雲端 revision 是不同身分，追查時不可互換。

## 展示前與故障後的順序

1. 開 [Live Demo](https://trade-dashboard-898093147725.asia-northeast1.run.app)，先看月份範圍與正式發布時間，再看最新品質嘗試。
2. 篩選固定期間，必要時「重新讀取已發布資料」清快取；日期範圍由 runtime env 決定，缺月份先查正式發布與邊界。
3. 問題若為服務錯誤，查 revision／流量／runtime logs／IAM；資料錯誤查發布摘要、來源配對、load／audit，勿直接修改正式資料。
4. 寫入重跑前保存正式版本基準；完成後獨立核對 grain、精確金額、run ID 與時間，不只看 task 綠燈。
5. 需停止展示或清理時沿用 Cloud Run／AWS 手冊；保留正式 state、來源與仍需回復的 digest。
