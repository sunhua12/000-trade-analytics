# AWS Terraform 管理

Day 4 的既有資源接管入口。`bootstrap/` 管理 state bucket；`application/` 管理 raw S3、ECR、Lambda execution role／policy、Lambda 與 CloudWatch Log Group。兩組使用不同 state key。

使用 Terraform **1.16.2**、AWS provider **6.64.0**；兩組 `.terraform.lock.hcl` 都需提交。工具可用版本管理器安裝；本次助理驗證用的 `/tmp/trade-terraform-tools/terraform` 是暫存執行檔，不是永久安裝。

## 1. 身分與本機設定

在 repository 根目錄執行。先用授權的 AWS profile／SSO 登入，`aws sts get-caller-identity` 確認帳號；不要將金鑰放入 tfvars 或 backend。Provider 的 `allowed_account_ids` 防止錯誤帳號操作。

首次複製範本；若本機已有檔案，先讀取比對，不覆寫：

```bash
cp infrastructure/aws/bootstrap/terraform.tfvars.example infrastructure/aws/bootstrap/terraform.tfvars
cp infrastructure/aws/bootstrap/backend.hcl.example infrastructure/aws/bootstrap/local.backend.hcl
cp infrastructure/aws/application/terraform.tfvars.example infrastructure/aws/application/terraform.tfvars
cp infrastructure/aws/application/backend.hcl.example infrastructure/aws/application/local.backend.hcl
```

填入真實帳號、Region、state bucket、現有資源名稱及目前解析的 image digest。`lambda_environment` 可保留額外既有環境變數；raw bucket／prefix 由專用變數設定。兩個 backend bucket 相同、key 不同，`encrypt=true` 與 `use_lockfile=true`。

本機 tfvars、backend 設定、`.terraform/`、state、plan 均忽略；`.example` 與 dependency lock file 必須保留。State 可能含敏感資訊，不能提交 Git 或貼出完整內容。

## 2. 建立與遷移 bootstrap state

僅在 state bucket 尚未建立時，從 local state 起始：

```bash
terraform -chdir=infrastructure/aws/bootstrap init
terraform -chdir=infrastructure/aws/bootstrap plan -out=bootstrap.tfplan
terraform -chdir=infrastructure/aws/bootstrap show bootstrap.tfplan
terraform -chdir=infrastructure/aws/bootstrap apply bootstrap.tfplan
```

Bucket 建立後，新增 backend 宣告並遷移已有 state：

```bash
cp infrastructure/aws/bootstrap/backend.tf.example infrastructure/aws/bootstrap/backend.tf
terraform -chdir=infrastructure/aws/bootstrap init -migrate-state -backend-config=local.backend.hcl
terraform -chdir=infrastructure/aws/bootstrap plan -detailed-exitcode
```

`backend.tf` 是本機啟用檔，已忽略。其他 Worktree／新電腦若接手**已存在的 remote state**，必須先複製這個 backend 宣告，再直接 `init -backend-config=local.backend.hcl`，不可重走 local-state apply。`-migrate-state` 用於有既有 local state 的首次遷移。

State bucket 啟用版本控制、AES256 加密、封鎖公開存取與拒絕 HTTP。Backend 權限限於該 bucket 與各自 key：state 需 GetObject／PutObject，`.tflock` 另需 DeleteObject；不需刪除 state object 的權限。官方 [S3 backend 文件](https://developer.hashicorp.com/terraform/language/backend/s3) 說明鎖定與權限。

## 3. 接管既有 application 資源

```bash
terraform -chdir=infrastructure/aws/application init -backend-config=local.backend.hcl
terraform -chdir=infrastructure/aws/application validate
terraform -chdir=infrastructure/aws/application plan -out=adoption.tfplan
terraform -chdir=infrastructure/aws/application show adoption.tfplan
```

`imports.tf` 明確匯入既有物件及獨立管理的 bucket 設定。先確認沒有 destroy／replace；若出現新建同名資源、未知環境變數刪除、映像變更或權限擴張，修正設定並重新 plan。確認後只套用剛才檢視的 plan：

```bash
terraform -chdir=infrastructure/aws/application apply adoption.tfplan
terraform -chdir=infrastructure/aws/application plan -detailed-exitcode
```

Exit code `0` 表示無差異，`2` 表示仍有變更，`1` 是錯誤。保存摘要與時間，完整 state／plan 保存在受控位置。本次匯入不等於重新驗證 Lambda 擷取功能，Day 4 的 invocation、World、重跑證據仍獨立驗收。

## 4. 更新與共同工作

- 更新 Lambda 時只修改 `image_uri` 為已存在的 ECR digest，再 plan／apply；不要同時用 Console 或另一支腳本更新 image。
- 不預設修改既有 ECR tag mutability 或 Lambda concurrency。保留部署及回復 digest 後，才設定 `ecr_lifecycle_policy`；未設定時不自動刪除映像。
- Raw 與 state bucket 使用 `prevent_destroy`／`force_destroy=false`。此保護只作用於 Terraform；不能防止其他 AWS 操作者刪除。
- Logs 預設保留 30 天；期限外日誌會依 AWS retention 行為清理。需要更長稽核期間時先修改變數。
- 每個 Worktree 自行建立本機設定，連到同一個 remote state。不要复制 `.terraform/`，也不要平行 apply 相同環境。Backend lock 防止同時寫入，但不能解決不同任務的設計衝突。
- 不在日常流程使用 `-lock=false`、任意 `force-unlock` 或 `terraform destroy`。

## 5. 全新環境與後續階段

`imports.tf` 專供既有環境；全新帳號需先在新分支移除 import blocks，選不同 bucket 與 state key。先建立 ECR：

```bash
terraform -chdir=infrastructure/aws/application plan -target=aws_ecr_repository.ingestion -out=ecr.tfplan
terraform -chdir=infrastructure/aws/application apply ecr.tfplan
```

接著依 Dockerfile 建置、推送 image，將 digest 填入 tfvars，再執行完整 plan／apply。`-target` 僅用於首次 ECR 先建的 bootstrap 階段，不用於日常更新。

本次範圍是 Day 4 資源接管與 state 管理。GitHub OIDC provider／受限部署角色仍待補入 bootstrap，GitHub Actions 部署在 Day 17；目前不得宣稱 OIDC bootstrap 完成。Metric Filters／Alarms／SNS 在 Day 15；ECR lifecycle 的啟用需先列出保留的映像。這些差距保留在驗證紀錄中。
