# Day 17：CI／CD、OIDC 與 Terraform 部署

| 項目 | 內容 |
|---|---|
| 對應計畫 | [20 天實作規格](trade-analytics-spec.md)的 Day 17；建立 M5 所需的品質檢查與可追溯部署 |
| 前置成果 | [Day 16](day16-run-record.md)已完成 M4 技術驗收；AWS application 已由 Terraform 管理，bootstrap／application 使用分離的 remote state |
| 預計投入 | 約 7～9 小時；GitHub 設定、雲端部署等待與權限排障另記 |
| 核心目標 | PR 自動執行離線檢查；受信任的手動部署以 OIDC 臨時憑證推送 ECR，再經 Terraform 更新 Lambda，保存 Git SHA、digest 與部署證據 |
| 今日交付物 | CI workflow、OIDC bootstrap 與最小權限部署角色、AWS 部署 workflow、手動 dbt 雲端測試入口、操作手冊與執行紀錄 |
| 目前狀態 | 尚未實作；目前沒有 `.github/workflows/`，OIDC provider／部署角色仍待補入 bootstrap |

MVP 維持美國月度進口、`8542／H6`。本日部署 ingestion Lambda，不部署 Airflow 或 Dashboard；Cloud Run 展示屬 Day 18。正式 monthly DAG 維持暫停，剩餘積欠與 Day 15 的 SNS email 實收缺口另行追蹤，不因 CI 成功而視為完成。

## 1. 盤點檢查範圍與部署契約

**預計時間：35～45 分鐘。**

- [ ] 核對 GitHub repository、預設分支、部署 environment、AWS 帳號／Region、ECR repository、Lambda 名稱及兩組 state key；從實際設定取得值，不預填推測的 repository 或 branch。
- [ ] 盤點 `pyproject.toml`、Dockerfile、Airflow 固定版本與 dbt 環境，確認 application、DAG 與 dbt 的依賴隔離方式；不將 Airflow 套件硬塞進 application 測試環境。
- [ ] 列出必要檢查與既有測試入口：Ruff format／lint、mypy、pytest／coverage、DAG import／結構、Lambda Docker build，以及兩組 Terraform fmt／validate。
- [ ] 定義觸發政策：PR／push 執行離線 CI；AWS 部署採受信任來源的 `workflow_dispatch`，必須先通過同一提交的必要檢查。PR 檢查不取得 AWS 憑證。
- [ ] 定義證據欄位與保存方式：Git SHA、workflow run URL、角色 ARN、ECR digest、plan／apply 摘要、Lambda 實際 digest 與驗證結果；敏感 state／plan 不提交 Git。

先確認 GitHub environment 的保護設定與帳號可用功能，再選 branch 或 environment 型 `sub`。使用 environment 型 `sub` 時，須另限制該 environment 可部署的分支，不能以 environment 名稱取代來源分支管制。

## 2. 建立不依賴雲端憑證的 CI

**預計時間：90～110 分鐘。**

- [ ] 建立 `.github/workflows/ci.yml`，使用 Python 3.11 與明確版本的工具／Actions；第三方 Actions 固定完整 commit SHA，註明對應版本。
- [ ] 執行 Ruff format／lint 與 strict mypy；範圍涵蓋正式程式、scripts、DAG 與專案測試，保留 `tests/TEST/` 的既有排除理由。
- [ ] 執行離線 pytest，確認不使用 `--run-integration`，不呼叫 Comtrade、AWS 或 BigQuery。整體 coverage 至少 80％、ingestion／manifest 至少 90％、新增 load 核心至少 85％；檢查各門檻有獨立且有效的量測。
- [ ] 在隔離 Airflow 環境驗證兩個 DAG 的真實 import／無 import error，並跑月份、三期上限、Pool、相依、失敗停損與重跑契約測試；純 mock 結構測試不能取代真實 import。
- [ ] 建置 `linux/amd64` Lambda image，沿用 `--provenance=false` 的既有建置契約；以非法事件做 handler 載入 smoke test，確認不需要雲端憑證。
- [ ] 對 bootstrap／application 執行 `terraform fmt -check`、`init -backend=false` 與 `validate`，沿用已提交的 provider lock file。檢查工作目錄不讀取本機 backend／tfvars 或既有 `.terraform/`。
- [ ] 用一個刻意的 lint 或 DAG 錯誤驗證 CI 會失敗，再修正並取得綠燈；保存失敗及成功 run，確認失敗檢查阻擋部署。

Terraform 與 Docker 檢查可以下載公開依賴，但不需雲端登入。CI 不以移除失敗測試或放寬品質門檻換取綠燈；若發現既有問題，記錄原因並修復。

## 3. 補齊 OIDC bootstrap 與最小權限

**預計時間：90～120 分鐘。**

- [ ] 以既有授權短期身分檢查帳號是否已有 GitHub OIDC provider；存在時引用或匯入，不建立重複 provider。
- [ ] 在 `infrastructure/aws/bootstrap/` 加入 provider 管理／引用與部署角色。Trust policy 精確限制 `aud=sts.amazonaws.com` 及指定 repository 的 branch 或 environment `sub`，不允許任意 repository／分支。
- [ ] 部署角色與 Lambda execution role 分離；依实际 Terraform 資源與 provider 操作整理 ECR push、application 資源管理及 state／lockfile 權限。需使用 `Resource=*` 的 API 個別說明原因，其餘限制專案資源。
- [ ] `iam:PassRole` 僅允許指定 Lambda execution role，並限制傳給 Lambda；application 部署角色不得修改自己的 OIDC trust 或接管 bootstrap 管理權。
- [ ] State 權限限定 application state key 與 `.tflock`；保留既有 backend locking，不授予日常部署刪除 state object 的權限。
- [ ] 先執行 bootstrap fmt／validate，檢視 plan 後 apply，確認 remote state 與既有資源無意外替換；記錄 bootstrap 首次登入與新環境建立順序。
- [ ] GitHub 僅設定必要的 role ARN、Region、資源名稱與非敏感設定；不新增 `AWS_ACCESS_KEY_ID`／`AWS_SECRET_ACCESS_KEY` 靜態 secrets。日誌不輸出 token 或 credential。

Bootstrap 必須由已授權的身分完成，不能假設尚未存在的 OIDC role 能建立自己。既有資源依 [AWS Terraform 管理流程](../infrastructure/aws/README.md)接續，不刪除重建。

## 4. 建立 ECR → Terraform → Lambda 部署流程

**預計時間：110～140 分鐘，加上雲端等待。**

- [ ] 建立手動 AWS 部署 workflow；檢查來源 ref 與必要 CI 結果，部署 job 使用 `id-token: write`、`contents: read`，透過 OIDC 取得臨時憑證並核對 AWS 帳號。
- [ ] 同環境設定部署 concurrency，避免平行 plan／apply；部署進行中不因新 run 任意取消 apply，並沿用 remote state lock。
- [ ] 建置 Lambda `linux/amd64` image，以 Git SHA 標記推送 ECR；取得實際 digest，將 `image_uri` 設為 `repository@sha256:...`，不使用可漂移的 tag 部署。
- [ ] 初始化 application remote backend，注入必要設定並保留既有 Lambda 環境與告警參數；使用 ECR digest 產生 plan。首次新環境先建立 ECR，日常更新不使用 `-target`。
- [ ] 檢視 plan 的資源變動及 image digest，確認無意外 destroy／replace／權限擴張；apply 必須使用同一次已檢視的 saved plan，不在 apply 階段重新產生另一份計畫。
- [ ] 若 plan／apply 分 job，使用受控的短期 artifact 傳遞 saved plan，限制存取與保留時間；不將完整 plan、state 或敏感變數寫入公開證據。
- [ ] 等待 Lambda 更新完成，核對實際 resolved image digest；做不寫資料的 handler 載入 smoke test，再執行 Terraform plan，確認無預期外 drift。
- [ ] 保存成功 CI 與真實 OIDC 部署 run，記錄 Git SHA → ECR digest → Lambda digest 的對應；不以本機 AWS profile 部署冒充 GitHub OIDC 驗收。
- [ ] 記錄失敗階段的處置與回復入口：保留舊 digest，回復也經 Terraform plan／apply；若 apply 結果不明，先查 state／Lambda 狀態，不盲目重跑或解除 lock。

Lambda image 由 Terraform 單一管理。部署成功不等於資料管線或告警鏈重新驗收；本日 smoke test 的範圍須明列。

## 5. 整理手動 dbt 雲端測試入口

**預計時間：60～80 分鐘，加上 BigQuery 等待。**

- [ ] 建立可重做的手動腳本或 workflow 入口，明確指定 BigQuery project、location、專用測試 Dataset、run ID、測試範圍與費用限制；PR 不自動執行雲端測試。
- [ ] 本機入口沿用 ADC；若提供 GitHub 雲端入口，須另建立 GCP Workload Identity Federation 與專用測試身分，不把 AWS OIDC 成功當成 GCP 認證已完成，不儲存 JSON key。
- [ ] 檢查 dbt models／macros 的 Dataset 設定，確保測試 target 不寫入正式 raw、candidate 或 published Dataset；來源資料如需讀取，明確限制為唯讀。
- [ ] 執行既有 dbt unit tests 與 data tests，涵蓋缺失／零分母、缺月 YoY、HHI 與 World 排除等已定義案例；確認 unit tests 仍需 warehouse，不標成完全離線。
- [ ] 保存去敏的 `manifest.json`／`run_results.json`、命令、job ID、測試結果與查詢費用／處理量；失敗時保留證據並讓入口回傳非零狀態。
- [ ] 記錄測試 Dataset 的保留期限與清理方式。若權限或來源不足，明列未完成項，不以 fixture 或 dbt parse 代替真實雲端測試成功。

## 6. 交付紀錄與學習檢查

**預計時間：35～45 分鐘。**

| 交付物 | 最少內容 |
|---|---|
| CI workflow | Ruff／mypy／pytest／coverage、真實 DAG import、Docker build、兩組 Terraform 檢查及成功／失敗 run |
| OIDC bootstrap | 精確 trust 條件、部署角色政策、state 權限與首次建立順序 |
| AWS 部署 workflow | 受信任來源、臨時憑證、concurrency、ECR digest、saved plan／apply 與部署核對 |
| 手動 dbt 入口 | 身分前置條件、隔離 Dataset、測試命令、artifacts 與費用限制 |
| 操作手冊與執行紀錄 | 建議新增 `docs/day17-cicd-manual.md`、`docs/day17-run-record.md`；記錄部署、失敗處置、回復與待辦 |
| [學習日誌](learning-log.md) | 實際日期、本人投入時間、設計理由、驗收結果與未解問題；未提供的工時與帳單不代填 |

完成後用自己的話回答：

1. OIDC 的 `aud` 與 `sub` 各限制什麼？environment 型 `sub` 為什麼仍需分支保護？
2. Bootstrap、部署角色與 Lambda execution role 為什麼分開？`iam:PassRole` 如何避免傳入其他角色？
3. Git SHA、image tag 與 digest 有何差異？如何確認 Lambda 正在執行本次部署映像？
4. 為什麼 apply 要使用已檢視的 saved plan？concurrency 與 state lock 分別解決什麼問題？
5. 哪些檢查可離線執行？dbt unit tests 為什麼仍需要 BigQuery，如何避免寫到正式資料？

- [ ] PR／push 的必要 CI 成功，且刻意錯誤確實被攔截；檢查不依賴雲端憑證。
- [ ] OIDC trust 限定指定 repository 與受信任來源，部署只使用臨時 AWS 憑證。
- [ ] 真實 GitHub run 完成 ECR push 與 Terraform Lambda 更新；Git SHA、digest、plan／apply 及更新後無 drift 可追溯。
- [ ] 手動 dbt 雲端測試入口可重做，隔離正式寫入，保存真實測試結果與 artifacts。
- [ ] 操作手冊、執行紀錄與學習日誌完成；證據齊全後才勾選總規格的 Day 17。

Day 18 接續 Streamlit Cloud Run 部署與線上查詢核對；Day 19 再完成乾淨重建及含 SNS 實際接收的故障演練。
