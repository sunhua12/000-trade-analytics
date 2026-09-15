# Terraform 接管驗證

完成日期：2026-09-14。範圍為 Day 4 的 state 管理與既有 application 接管；非完整 Day 4 功能重驗或 Day 17 CI/CD 驗收。

## 實際執行結果

| 項目 | 結果 |
|---|---|
| Terraform／AWS provider | 1.16.2／6.64.0，官方 provider 簽章驗證成功，兩組 lock file 已產生 |
| CLI 執行檔 | 官方 darwin_arm64 ZIP，對照官方 SHA-256 通過；位於本機暫存目錄 |
| Bootstrap validate | 通過 |
| Application validate | 通過；後續新增的 SSE-C 保護設定亦經真實 plan／apply 驗證 |
| Bootstrap plan／apply | 6 added、0 changed、0 destroyed |
| Bootstrap state 遷移 | local → S3 成功，啟用 `use_lockfile` |
| Application plan／apply | 11 imported、0 added、3 changed、0 destroyed |
| Bootstrap 後續 plan | `No changes`，`-detailed-exitcode` 回傳 0 |
| Application 後續 plan | `No changes`，`-detailed-exitcode` 回傳 0 |
| Lambda 最終狀態 | Active／LastUpdateStatus Successful，image digest 保持一致 |
| Raw bucket versioning | Enabled |
| Git 忽略規則 | tfvars、local backend、state、plan／JSON 與 backend 啟用檔均通過 check-ignore |
| 格式 | `terraform fmt -check -recursive infrastructure/aws` 通過 |

本次登入為既有 AWS CLI IAM user 憑證；沒有建立或將任何 access key 寫入 Terraform。短期 SSO 登入與受限 OIDC 部署仍需後續落實，不能宣稱此次部署使用 OIDC。

## 接管內容與變更

Bootstrap 建立獨立 state bucket，以及 versioning、AES256 encryption、public access block、BucketOwnerEnforced、拒絕 HTTP 的 bucket policy。兩組 state 使用不同 object key；實際列出 S3 objects 確認 bootstrap 與 application state 均存在，完成後沒有殘留 `.tflock` object。

Application 匯入 raw bucket 與其 4 項設定、ECR repository、Lambda role、Logs managed-policy attachment、S3 inline policy、Log Group、Lambda，共 11 個 Terraform resource addresses。

實際差異：

1. Raw bucket versioning 從 Disabled → Enabled。2026-09-13 盤點時未啟用，不能用本次啟用結果反推 Day 4 已有 object version 證據；既有 objects 不會因此自動生成新版本。
2. Logs retention 從無限期 → 30 天；目前 log group 建於 2026-09-12。
3. Lambda 的 environment 加上 Terraform sensitive metadata。以 plan JSON 比對 before／after，環境變數值與 image URI 完全相同；未更換映像或新增權限。

S3 保留既有 AES256、BucketKeyEnabled 與 SSE-C 阻擋；ECR 保留 MUTABLE／scan-on-push；Lambda 保留 x86_64、512 MB、180 秒及未設定 reserved concurrency（Terraform 值 -1）。IAM 沿用原 policy，不在接管中放大權限。

## 追溯與交接

環境為 ap-northeast-1，非 CLI 原預設 ap-east-2。具體帳號、bucket、image URI 保存在各層被 Git 忽略的 `terraform.tfvars`／`local.backend.hcl`，不在此重複發布帳號識別。資源名稱為 `trade-analytics-ingestion`、角色為 `trade-analytics-lambda-role`。

實際映像 digest：

```text
sha256:c8a6df9679b89c0340df8c6fb0e638b493514df74b550accd1ecf4a3fe0a53b4
```

State keys：

```text
trade-analytics/bootstrap/terraform.tfstate
trade-analytics/application/terraform.tfstate
```

本次執行的 saved plans 位於 bootstrap 的 `bootstrap.tfplan` 與 application 的 `adoption.tfplan`，均不提交 Git。完整 plan 可能含敏感值，不做公開 artifacts。本次 Terraform 程式尚未 commit，因此不以目前 Git HEAD 冒充此次 IaC 的版本；映像原建置 Git SHA 亦未能從 ECR tag `day04` 推定。

## 剩餘範圍

- OIDC provider／受限部署角色尚未加入 bootstrap；Day 17 workflow 尚未實作。
- ECR lifecycle 目前可由變數管理，但尚未啟用；現有唯一 image 保留，需先決定部署／回復映像保留規則。
- Logs 權限目前沿用 AWSLambdaBasicExecutionRole，進一步限縮到指定 Log Group 尚待處理。
- Lambda concurrency 保留現況，未達計畫的 1；維持人工串行執行。
- World 原檔核對、真實 invocation、非法事件與重跑 Version ID 證據仍待補。本次沒有重新呼叫 Lambda 或修改 raw data。
- 預算通知、完整乾淨重建與跨 writer lock 競爭演練未在此次驗收。

操作及新 Worktree 接手方式見 [AWS Terraform 說明](../../../infrastructure/aws/README.md)。
