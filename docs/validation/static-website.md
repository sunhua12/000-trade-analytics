> 歷史文件：此處保留重構前的設計與驗收紀錄。現行入口、排程與發布方式以 [操作手冊](../runbook.md) 及根目錄 README 為準；舊命令可能已退役。

# 靜態網站與後續流程驗收

## 交付內容

- `frontend/`：原生 HTML／CSS／ES modules，Apple／Notion 方向的研究工作台，無前端套件依賴。
- 真實公開快照：2023-01 至 2024-12，24 筆月份摘要與 1,536 筆國家月份明細。
- 日期、國家、Top N、趨勢、排名、YoY、覆蓋率／HHI、地圖、散佈圖、分頁搜尋、CSV 及方法頁。
- 移除 Streamlit app、舊查詢與專用依賴／測試，更新 CI、README、runbook 與環境範本。
- Airflow 改為前置檢查與 process_batch；整批占用單 slot Pool，月份依序處理，全部成功才匯出一次並建置網站產物。
- 新增共享 advisory flock、本機批次入口與完整網站版本 builder。鎖只保護合作入口與支援 flock 的共享檔案系統，無法限制直接 dbt／BigQuery 操作。

## 已完成驗證

- Python：Ruff format／lint、mypy 通過；42 tests passed，1 個外部 Preview API integration test 依設定 skipped。
- 前端：5 個 Node tests 通過，涵蓋大額精度、World 分母、日期／國家／Top N、缺月、期間市占、YoY 與 CSV。
- 真實 Docker Airflow 匯入：兩個 DAG 均成功，確認各為 2 個 task，process_batch 的 Pool、重試與依賴正確；未執行正式雲端管線。
- 網站 builder 使用真實快照成功產生完整 release，失敗保留上一版的測試通過。
- 瀏覽器本機檢查：1440px 桌面與 390px 手機；手機 scrollWidth 與 viewport 均為 390，無水平溢位。
- 單國 Malaysia：World 維持 76.45B、選定金額 19.28B、YoY 使用 Malaysia。
- 明細分頁顯示 25 筆，搜尋 Malaysia 為 24 筆；錯誤日期顯示提示並停用匯出。
- 方法頁可開啟，瀏覽器 error logs 為空。
- 依使用者修訂後的文案已完成 HTML 結構與靜態文字檢查，移除勵志與協作口號；精簡版前端測試與建置再次通過。

前期瀏覽器檢查與手機 screenshot 屬初稿紀錄，完成後另依使用者要求精簡文案。不得將初稿畫面當成最終文案證據。

## Sites 發布

- URL：https://silicon-atlas-trade-observatory.honest-badge-7365.chatgpt.site
- Audience：owner-private；未擴大公開存取。
- Project：appgprj_6ad1c7c5d85c819187e1ffecc4a9d2b1
- Source commit：ca50bf54b8c2c7ed0a06d6057c69af498a119de3
- Saved version：appgprj_6ad1c7c5d85c819187e1ffecc4a9d2b1~appgver_28762f57dbf48191bc737eb47e0ef986
- Deployment：appgdep_6ad24b90c0b88191af66b88049fe2a2c
- Native deployment result：succeeded。

來源在獨立的清理過 checkout 中同步，僅含前端與公開快照；短效憑證由 stdin 傳入，未寫入 Git 或檔案。原專案未提交或推送，保留使用者審閱空間。

線上瀏覽器確認私人登入頁正常出現，但當前瀏覽器沒有擁有者登入狀態，因此未宣稱完成線上內容互動驗證。部署成功由 Sites 原生回傳確認；功能驗證來自本機相同前端與快照。

## 執行邊界

本次未啟用或觸發正式 monthly／backfill 排程，也未更新正式 Raw 資料。升級既有 Airflow worker 前，須暫停舊 run、重新 build Compose、確認 data 寫入權限與 Pool 為 1。後續資料更新會產生新的 JSON／網站 release，仍需獨立發布 Sites 版本。
