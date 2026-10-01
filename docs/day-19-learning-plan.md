# Day 19：乾淨重建、故障告警與復原驗收

| 項目 | 內容 |
|---|---|
| 對應計畫 | [20 天實作規格](trade-analytics-spec.md)的 Day 19；補齊 M5 的重建與故障復原證據 |
| 前置成果 | [Day 17](day17-run-record.md)完成 CI／OIDC／Terraform 部署；[Day 18](day18-run-record.md)完成 Cloud Run 展示與單月正常路徑安全重跑 |
| 預計投入 | 約 7～9 小時；依賴下載、雲端部署、告警等待與收件確認另記，超時明列未完成項 |
| 核心目標 | 從乾淨環境重現部署，完成真實失敗 → SNS 實收 → run_id 定位 → 修正重跑，驗證失敗不發布、復原不重複資料及版本回復 |
| 今日交付物 | 重建／故障／回復操作手冊、執行紀錄、去敏驗收證據與學習日誌 |
| 目前狀態 | 技術驗收完成；Cloud Run 直接舊 revision 回切失敗，以舊 digest 新 revision 復原，詳見[執行紀錄](day19-run-record.md) |

MVP 維持美國月度進口、`8542／H6`。今天用於整合與驗收，不追加圖表、GCP Terraform、WIF 或新技術。正式 monthly DAG 保持暫停，剩餘積欠另行處理；不刪除正式 AWS 資源、remote state、S3 原始來源或 BigQuery 資料來證明重建。

## 1. 凍結基準與演練範圍

**預計時間：35～45 分鐘。**

- [x] 核對實際 Git 提交、CI 結果、Lambda digest、Cloud Run revision／digest、Terraform state key 與 Airflow DAG 狀態，建立演練前基準。
- [x] Day 18 image 含當時未提交內容；先核對來源清單與目前提交，從完整已提交來源重建，不能只以當時的 base SHA 宣稱可重現。
- [x] 列出隔離資源名稱、S3 prefix、BigQuery Dataset、IAM／OIDC trust 與預計費用；確認與正式資源及 state 無名稱衝突、無寫入交叉。
- [x] 選定失敗不發布的測試月份與 run ID，保存 raw grain、正式資料筆數／金額、`published_run_id`、`published_at` 及品質狀態；若使用隔離發布表，明列測試 target。
- [x] 確認 SNS 收件端點與訂閱狀態；個人 email 不提交 Git。需要本人點擊訂閱確認信或提供實收時間時，列為待本人完成的外部步驟。

沿用 [AWS 管理流程](../infrastructure/aws/README.md)、[CI／CD 手冊](day17-cicd-manual.md)、[告警手冊](day15-operations-manual.md)及 [Cloud Run 手冊](day18-cloud-run-manual.md)，先查實際設定再產生操作命令。

## 2. 從乾淨環境重建與驗證部署

**預計時間：120～150 分鐘，加上建置與雲端等待。**

- [x] 由固定提交建立新的 checkout／工作目錄與虛擬環境，不複製既有 `.venv`、`.terraform`、ADC、`.env`、state 或 saved plan；依文件安裝 application、Airflow、dbt 與 Terraform 的必要依賴。
- [x] 依既有入口執行離線 CI、兩個 DAG 真實 import、容器 smoke 與 Terraform fmt／validate；記錄缺漏的安裝或設定步驟，修正文檔後重做受影響部分。
- [x] 區分「乾淨 checkout 連接既有 remote state」與「隔離 AWS application 資源新建」；前者只能證明接續管理，不能代替資源重建證據。
- [x] 在獨立 state key／命名空間依 bootstrap → ECR → image → application 流程新建隔離資源；帳號既有 OIDC provider 引用或匯入，不重複建立。Bootstrap／state bucket 的共用與未重建範圍明列。
- [x] 先檢視 saved plan 的資源範圍，再 apply 同一份 plan；使用 Git SHA 與不可變 digest，等待 Lambda 可用，完成無寫入 smoke，後續 plan 無預期外差異。
- [x] 核對現有 OIDC trust 與部署角色限制。隔離資源若超出日常角色權限，以受控 bootstrap 身分建立所需設定；不擴張正式部署角色或使用本機 profile 冒充 OIDC。
- [x] 從乾淨來源執行真實 GitHub CI／OIDC 部署，保存 run URL、subject／角色、Git SHA → ECR digest → Lambda digest 證據；只通過本機檢查時，遠端驗收保留未完成。
- [x] 依 GCP 指令重現 Dashboard 建置、部署與唯讀 runtime 設定；可使用隔離服務，記錄共享 registry／Dataset。驗證 PORT、健康檢查、Live UI 與固定 SQL，不假設兩次 build 的 digest 必然相同。

重建只修復阻礙既有契約的問題。授權、配額或預算阻擋時，保存已完成範圍與原因，不以 Terraform validate 代替 apply，不刪除正式環境求取成功。

## 3. 完成真實告警與 run ID 追查

**預計時間：90～120 分鐘，加上 Alarm 評估與收件等待。**

- [x] 核對三類 JSON Metric Filters（`ComtradeResponseError`、`ResponseTruncatedError`、`StorageConflictError`）、Errors／Duration Alarms、SNS policy 與已確認訂閱；沿用分類 Sum ≥ 1、Errors Sum ≥ 1、Duration Maximum > 150000 ms、`notBreaching` 契約。
- [x] 盤點 Day 15 已保存證據，補缺口；用真實日誌樣本驗證三類 filter，不將單純樣本匹配當成完整通知鏈成功。
- [x] 在隔離函數／prefix 觸發可重現的真實 handler 失敗，保存 invocation、錯誤分類、run ID 與 CloudWatch 日誌；故障入口只存在隔離環境。
- [x] 等待真實 metric 使 Alarm 進入 ALARM，確認 history 中 SNS action 成功，並取得收件者實際通知與接收時間；不能以手動設定 Alarm state 或 SNS publish 代替。
- [x] 由通知的 Alarm／時間／函數找到日誌，再依 run ID 追查 Airflow、S3 manifest、load／品質紀錄，寫下定位順序與根因。
- [x] 核對既有 Errors 與超過 150 秒的真實耗時證據，必要時補隔離演練；標明沿用及新增證據。記錄重複通知與持續 ALARM 不保證每次重發的限制。

原生 Alarm 通知不自動包含 run ID。SNS topic 動作成功、訂閱已確認與 email 實收是三個不同驗收點；未取得實收證據時保持未完成。

## 4. 驗證失敗不發布與修正重跑

**預計時間：100～130 分鐘，加上真實管線等待。**

- [x] 在隔離端到端流程設計可重現的來源／載入失敗或品質 FAIL，沿用現有入口與 gate；保存 failed task、audit／reason code 及 publish 未執行證據。
- [x] 失敗後比對演練前基準，確認正式發布版本與資料不變；若只驗證隔離發布表，結果標為隔離 E2E，不冒稱正式月份失敗演練。
- [x] 修正真正原因，不移除 gate、放寬品質門檻或手動補正式資料；沿用 revision／checksum／run ID 契約，品質修正建立可追溯的新 attempt。
- [x] 以原入口重跑 ingest → load → attest → dbt build／audit → gate → publish，保存同一鏈路的 task、manifest、BigQuery job、品質與發布結果。
- [x] 核對復原後 raw grain 無重複、來源配對正確、金額與預期一致；既有發布版本安全重跑時，run ID 與發布時間不得改變。
- [x] 再做一次安全重跑，驗證 `already_exists`／`already_loaded`／`already_published` 的適用結果；使用獨立 SQL 核對並保存前後比較。

Lambda 告警演練與品質 gate 演練可能是不同案例。以案例表列出各自證明的範圍，不把不同 run ID 串成一次完整事故；至少一個 handler 真實失敗案例須完成通知、定位與修正重跑。

## 5. 演練版本回復與清理

**預計時間：45～60 分鐘，加上部署等待。**

- [x] Cloud Run 目前只有首次 revision；先從已提交來源建立第二個可用 revision，保存兩者 digest／設定與固定條件查核，再嘗試回切已驗證 revision 並重新操作 UI。直接回切實測失敗，已改用舊 digest 新 revision 復原並核對原 Live URL；不宣稱直接回切通過。
- [x] Lambda 在隔離環境以 Terraform 回復已驗證舊 digest，使用已檢視的 saved plan；核對 resolved digest、smoke 與後續無 drift，不只記錄回復指令。
- [x] 區分服務流量／image 回復與資料復原；本次 image 回復不宣稱能撤銷已發布資料。
- [x] 保存證據後檢視隔離資源清理 plan，移除測試 Alarm／subscription、函數、臨時服務／Dataset 與無共用者的資源；保留需要的 digest、共用 provider、正式 state 與來源。
- [x] 清理後確認正式 Live Demo、發布資料與 monthly DAG 暫停狀態，記錄未清理資源、到期時間及費用風險。

## 6. 交付紀錄與學習檢查

**預計時間：30～40 分鐘。**

| 交付物 | 最少內容 |
|---|---|
| `docs/day19-recovery-manual.md` | 乾淨環境安裝、bootstrap／OIDC／Terraform 順序、故障定位、重跑、版本回復及清理入口 |
| `docs/day19-run-record.md` | 實際日期、提交／digest、隔離範圍、重建／告警／復原／回復結果、共用與未驗證項 |
| `docs/evidence/day19/` | 去敏 plan／apply 摘要、無 drift、CI／部署 URL、invocation／logs、Alarm history、實收時間、SQL 與前後比較 |
| [學習日誌](learning-log.md) | 本人實際投入、根因與決策、理解檢查；未提供工時及帳單不代填 |
| 總規格狀態 | 證據齊全後才勾選 Day 19；SNS 缺口連同 Day 15 驗收重新核對，M5 留待 Day 20 |

通知截圖與日誌先去敏；憑證、email、state、完整 plan 與敏感設定不提交 Git。證據時間標示時區，通知時間與故障發生時間分開記錄。

完成後用自己的話回答：

1. 乾淨 checkout、連接既有 state 與新建隔離資源，各能證明什麼？Bootstrap 與 OIDC 為何有建立順序？
2. SNS action 成功為何不足以證明收件成功？沒有 run ID 的通知如何追查根因？
3. 暫時錯誤、永久錯誤與品質 FAIL 應如何選擇重試或修正？
4. 載入已提交卻失去成功回報時，如何確認重跑不增加重複資料？
5. Cloud Run 流量回切、Lambda digest 回復與資料復原的範圍有何差異？

- [x] 固定提交能在乾淨環境安裝與驗證，隔離 AWS 資源真實建立且後續無預期外 drift；共享／未重建範圍明列。
- [x] 真實 handler 失敗觸發 Alarm → SNS 並實際收到通知，可依 run ID 定位及修正重跑。
- [x] 三類 filters、Errors 與 Duration 契約均有對應證據，失敗不發布、復原與安全重跑無重複有效資料。
- [x] Cloud Run 舊 digest 新 revision 復原與 Lambda digest 回復實測通過，隔離資源完成清理或明列保留理由。
- [x] 手冊、紀錄與學習日誌完成；未完成項可追蹤，不追加功能，不提前宣稱 M5 完成。

Day 20 接續 README、架構圖、資料字典、限制與 5 分鐘展示稿，展示三項分析、一次故障復原與一次安全重跑，依總規格逐項最終驗收。
