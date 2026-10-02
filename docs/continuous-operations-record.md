# 持續營運執行與驗收紀錄

2026-10-02，Asia/Taipei。工作分支 `feature/continuous-operations-validation`，變更見 [PR #19](https://github.com/sunhua12/000-trade-analytics/pull/19)。可立即執行的營運工作已完成，跨週與帳期驗收仍待觀察；原 24 月 MVP 技術驗收與後續營運驗收分開。

## 範圍與本人決策

- 本次補齊來源可用的積欠、恢復 monthly、驗證本機服務重啟、啟用受信任 main 的自動部署及整理資源。
- 使用者選擇維持本機常駐，接受關機／休眠期間不排程；後續保留 [手動檢查清單](continuous-operations-checklist.md)，不設定每日自動檢查。
- 本人講解先跳過；預算通知尚未收到。兩項不代填為通過。
- 跨數週穩定性與完整帳期須等待，不能以本次操作完成代替。

## 現況基準與 CI

原交付已合併為 `94b8af88bc1548cb7df45b24d621c98851f0282f`，[main CI](https://github.com/sunhua12/000-trade-analytics/actions/runs/36940970223)成功，「尚未 push」已不是現況。基準與原 28 月正式發布快照見 [baseline-ci.json](evidence/continuous-operations/baseline-ci.json)與 [baseline.json](evidence/continuous-operations/baseline.json)。

## 來源盤點、品質停損與修復

[來源查核](evidence/continuous-operations/source-availability.json)確認 202505～202607 兩類來源均可用；202608、202609 兩類均未就緒。當前完整月份上界不代表來源已提供。

首批 `202505～202507` 在 202505 品質審計回報 `missing_dimension`、`unresolved_reconciliation`、`unreviewed_classification`，gate 阻擋，沒有發布或開始後續月份。根因為新夥伴 422 未列於 seed，見 [mapping-failure.json](evidence/continuous-operations/mapping-failure.json)。

逐月盤點所有待補來源後，新增 13 個明確審核的單一夥伴經濟體：4、31、60、70、234、266、417、418、422、524、558、584、686。對照既有官方 Comtrade／M49 快照、ISO、isGroup、有效期間，保存 [審核紀錄](evidence/continuous-operations/partner-review.json)。參考表增至 163 筆；seed 產生器讀取此明確審核紀錄，未知代碼仍需審核，490 的特殊分類維持原規則。

品質 FAIL 的 frozen batch 保留作歷史證據。公開文字日誌僅移除 ANSI 色碼與行尾空白，原始日誌另存於不公開的 private 目錄。修正根因後以新品質 attempt／DAG run 重做；已載入來源先比對後回傳 already_loaded，不修改舊發布。各批仍最多三個連續完整月份，monthly 在回填期間暫停。

五個串行批次成功補齊 202505～202606，見 [批次結果](evidence/continuous-operations/backfill-batches.json)。解除 monthly 暫停後，scheduler 建立 `scheduled__2026-09-30T16:00:00+00:00`，11 個 tasks 成功、20 個略過，於台北時間 2026-10-02 10：12：01 自動發布 202607。正式發布 ID 為 `monthly-202607-bffcb8391d44228b`，World 金額 USD 4,396,076,161；202608／202609 因來源未就緒略過，更舊缺月清空，見 [排程結果](evidence/continuous-operations/monthly-scheduled-runs.json)與 [月份判斷](evidence/continuous-operations/monthly-metadata.json)。

[最終獨立 SQL 查核](evidence/continuous-operations/final-verification.json)確認 202301～202607 連續 43 個月、raw／published grain 無重複、來源版本無混用、品質為 PASS／WARN，原 28 月正式發布 ID、時間、筆數與金額不變。monthly 已恢復，backfill 保持暫停；下一次未來排程為 2026-11-01 00：00（Asia/Taipei），見 [DAG 狀態](evidence/continuous-operations/dag-final-status.json)。

Cloud Run 沿用已驗證舊 digest，新 revision `trade-dashboard-continuous-20261002` 承接 100％ 流量，min 0／max 1、快取 3600 秒、單 query 1 GB 維持。日期上界更新為 `2026-08-01`，線上顯示 43 月及 World 合計 USD 150,116,929,964；本機 AppTest 核對單月篩選與 7 月金額，見 [UI 驗證](evidence/continuous-operations/dashboard-ui-verification.json)。固定上界需於未來月份發布後手動更新，不宣稱 Dashboard 無需維護。獨立查詢見 [reference.sql](evidence/continuous-operations/reference.sql)，每 query 上限 1 GB；核對連續月份、raw grain／checksum／revision、金額、品質與原 28 月發布版本。

## 本機服務復原

在第一批品質 FAIL 已停止、無正式 writer 時重啟 scheduler、worker、dag processor、triggerer 與 API server；Postgres／Redis 沒有刪除或重建。重啟後 7 個必要服務均健康，`airflow db check` 成功，原 DAG run IDs 保留。證據為 [重啟後健康](evidence/continuous-operations/compose-after-restart.jsonl)與 [metadata](evidence/continuous-operations/backfill-runs-after-restart.json)。

本次只驗證服務重啟，不宣稱主機重啟、停電恢復或跨數週穩定。觀察期間及下次月排程按手動清單追蹤。

## AWS 自動部署

唯讀核對確認 GitHub `AWS_DEPLOY_REF=refs/heads/main`、OIDC trust 精確限定 main；原 workflow push trigger 還是舊 feature 分支，造成即使打開開關也無法從 main 自動部署。本次將 push trigger 同步為 main，保留 path filter、CI、image-only guard、saved plan、序列化與 digest／無 drift 查核。新工作分支沒有取得正式部署權限。

`AWS_AUTO_DEPLOY_ENABLED=true` 已啟用；[PR #19](https://github.com/sunhua12/000-trade-analytics/pull/19) 合入 main SHA `37dc6008c55f952c45194cc925df718afd301641` 後，[main CI](https://github.com/sunhua12/000-trade-analytics/actions/runs/36953503943)與 [push 自動部署](https://github.com/sunhua12/000-trade-analytics/actions/runs/36953504147)皆成功。Lambda 為 Active／Successful，digest `sha256:f7370058ab3f19906330a0611f59d7d6c275ae5598c9f4854b913166dc8af3f0` 與 artifact 一致，Terraform image-only 更新後無 drift，見 [部署查核](evidence/continuous-operations/deployment/deployment-verification.json)與 [獨立 Lambda 查核](evidence/continuous-operations/lambda-current.json)。

本機 Ruff 與 8 個 deployment plan guard tests 通過；真實回填的 dbt build 各 88 項成功。文件交付 CI 另以本次 PR 檢查為準，純文件變更不符合 AWS deployment path filter。

## 費用與資源整理

- GCP 專案限定 TWD 250 月預算與四個門檻已查驗；使用者確認尚未實收。沒有刻意花費觸發通知。
- AWS Cost Explorer 已讀取 2026 年 9 月與 10 月初費用，但結果均標為 Estimated，且為帳戶服務彙總，不能直接當本專案最終帳單。
- GCP 費用報表已讀取當月累計；9 月憑據頁沒有結果，帳務橫幅顯示自 2026-10-01 起收費。首個完整持續營運帳期為 10 月，待最終帳單核對。
- 帳務明細保留於本機 `docs/evidence/continuous-operations/private/`，由 `.gitignore` 排除，不發布至公開 repository。
- 已刪除 Day 17 隔離測試 dataset `trade_ci_oidc_20261001_v1`（12 個 tables），既有 artifacts 保留；正式 raw／published 未清理，見 [清理紀錄](evidence/continuous-operations/ci-dataset-cleanup.json)。
- 已刪除失敗 OIDC run 產生、無 Lambda 引用的 untagged ECR 映像，見 [ECR 清理](evidence/continuous-operations/aws-image-cleanup.json)；保留正式與可回復映像。五個 CloudWatch alarms 均為 OK，此為觀測時點狀態。
- 已刪除無流量的 `trade-dashboard-00001-glf`，其 digest 與使用中的 recovered revision 相同。使用中 revision 與兩個不同的映像 digest 保留；整理 revisions 不直接宣稱節費。

## 待等待或暫緩的驗收

| 項目 | 狀態／下一步 |
|---|---|
| 202608、202609 | 來源未就緒，後續 monthly 查核；超過最近三期時改 backfill |
| 長期穩定 | 自 2026-10-02 開始手動記錄，跨 2～4 週及未來月排程觀察 |
| 完整費用帳期 | 2026 年 10 月帳單可取得後核對，不以累計或預估代替 |
| 預算通知實收 | 尚未收到；本人收到後記錄門檻／日期 |
| 本人講解與理解 | 使用者要求先跳過，原 Day 20／M5 保留待完成 |

HHI、Cloud Run 舊 digest 新 revision 的復原方式與 GCP IaC／WIF／雲端 Airflow／多 writer 延後範圍維持既有界線。
