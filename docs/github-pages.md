> 歷史文件：此處保留重構前的設計與驗收紀錄。現行入口、排程與發布方式以 [操作手冊](runbook.md) 及根目錄 README 為準；舊命令可能已退役。

# GitHub Pages 發布

公開網址：https://sunhua12.github.io/000-trade-analytics/

## 單一版本來源

網站程式 `frontend/src/`、地圖 `frontend/assets/` 及正式資料 `frontend/public/data/` 都由 `main` 管理。工作流程只 checkout 本次提交，不從其他分支或固定的外部提交下載資料。

正式 JSON 包含 `manifest.json`、`monthly.json`、`partners.json`。目前快照為 `65e478c3765d4c3f836115b1f5b5e529`，有 222,959 筆來源明細。`manifest.json` 記錄版本、筆數、檔案長度及 checksum，建置驗證失敗便停止發布。

## 修改與合併

1. 從最新 `main` 建立功能分支。
2. 修改程式或同批更新三份正式 JSON。
3. 執行 `node --test frontend/tests/*.test.mjs` 與 `node frontend/build.mjs`。
4. 自行提交、推送分支並建立 PR。
5. 檢查通過後手動合併至 `main`，觸發 Pages 部署。

回歸測試使用 `frontend/tests/fixtures/` 的獨立資料；本機預覽及正式建置使用 `frontend/public/data/`，兩者不互相覆蓋。不需要雲端憑證或 Comtrade API Key。

此版本合併且部署成功後，`gh-pages` 不再有用途，可以刪除，不需將其獨立提交歷史合併回 `main`。資料內容已隨本次變更納入版本管理。

## GitHub 設定

- Settings → Pages → Build and deployment → Source：GitHub Actions。
- Settings → Environments → github-pages → Deployment branches and tags：允許 `main`。
- 工作流程僅在 `main` 部署；PR 只執行測試與建置。

## 更新正式資料

資料發布與 Airflow 更新尚未自動串接。接受新快照後，將該完整網站版本的三份 JSON 一起複製至 `frontend/public/data/`，執行建置驗證，再隨 PR 合併。不要混用不同快照的檔案。

只提交公開資料，不提交 `.env`、雲端憑證、資料庫、原始快取或本機執行紀錄。
