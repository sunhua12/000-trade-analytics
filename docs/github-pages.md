# GitHub Pages 發布

公開網址：https://sunhua12.github.io/000-trade-analytics/

## 分支與合併流程

網站原始碼位於 `main` 的 `frontend/`。後續修改從 `main` 開功能分支，透過 PR 檢查及手動合併；不將獨立歷史的 `gh-pages` 合併回 `main`。

`.github/workflows/pages.yml` 在 PR 執行前端測試、驗證資料 checksum 並建置網站，只有合併至 `main` 或在 `main` 手動執行工作流程時才部署。功能分支不會改動公開網站。

## 首次切換至 Actions

1. 手動建立本分支至 `main` 的 PR，確認檢查通過。
2. 在儲存庫 Settings → Pages → Build and deployment，將 Source 改為 **GitHub Actions**。
3. 手動合併 PR。合併後工作流程會部署；若首次執行失敗，完成設定後在 Actions 重新執行 GitHub Pages。
4. 確認公開網站可載入市場、商品、圖表及資料明細。

切換前，既有網站繼續由 `gh-pages` 提供。此分支本身不修改線上 Pages 設定。

## 資料來源

工作流程固定使用部署提交 `1f73c41d00e679ae20b2c964b5d7f22e0e65d12a` 的 `data/`，快照為 `65e478c3765d4c3f836115b1f5b5e529`，包含 222,959 筆來源明細。網站程式使用本次待合併版本，不使用舊的部署程式或 main 中的示範資料。

不需要雲端憑證或 Comtrade API Key。資料發布與 Airflow 更新尚未自動串接；接受新快照後，先將經驗證的公開 JSON 保存至儲存庫提交，再透過 PR 更新工作流程中的固定 SHA。保留該提交可確保後續建置能重現相同資料。

請勿提交 `.env`、雲端憑證、資料庫、原始快取或本機執行紀錄。
