# Silicon Atlas：設計與 AI 協作決策

## 設計方向

面向面試官與資料分析讀者的研究工作台。以 Apple 式留白和字體層級、Notion 式側欄與可掃讀結構呈現真實數據。暖白底、石灰色中性色與單一陶土橘強調；不使用背景影片、游標特效或無限動畫。

版面以分析任務為主：期間總額 → 趨勢／排名 → 成長／品質 → 地理／散佈圖。資料探索與方法說明分成獨立導覽，保持主要畫面聚焦。手機版改單欄，表格自身捲動，圖表依容器寬度重畫，避免縮小 SVG 後標籤不可讀。

實作採原生 HTML／CSS／ES modules。互動範圍不需要伺服器框架；所有資料與地圖隨網站部署，不依賴 CDN。數值層使用 BigInt 固定小數精度，圖表繪製才轉 Number。網站啟動時檢查 SHA-256、筆數、資料版本與快照 ID。

## 使用者提供的參考

- [Superdesign](https://github.com/superdesigndev/superdesign)：參考從 wireframe 到可運作介面的迭代方向，未安裝 IDE extension。
- [Better Design](https://github.com/marvkr/better-design)：查看公開 Apple／Notion 設計系統方向。MCP 未連線，未執行 MCP 主題安裝或審查。
- [Design Taste](https://github.com/madebymustafa/design-taste/blob/main/skills/design-taste/SKILL.md)：實際讀取核心規範，採用克制配色、清楚字體層級、結構留白與減少動態效果。
- [Canvas UI](https://github.com/DavidHDev/canvas-ui)、[Paper Shaders](https://github.com/paper-design/shaders)：查看用途後，判斷 WebGL／shader 效果不適合主要資料閱讀任務，未加入依賴。
- [UI Layouts](https://github.com/ui-layouts/uilayouts)：參考版面與組件的用途，實作維持專案自己的靜態結構。
- [Motion Primitives](https://github.com/ibelick/motion-primitives)：參考克制的互動方向；只使用 CSS 頁面淡入，支援 prefers-reduced-motion，未安裝 React 動態套件。
- [Cursify](https://github.com/ui-layouts/cursify)：游標效果與數據探索目的不符，未使用。
- 使用者提供的 Hyperiux 與 Trickle GitHub 連結本次未能取得內容，因此未宣稱採用或審查這兩套實作。

以上為參考與取捨紀錄，不代表十套工具都已安裝。程式碼為本專案實作，地圖資料另外標示 Natural Earth 來源。

## 可在面試說明的具體協作

1. 人先定義資料粒度與篩選語意；AI 實作時不得重複加總 World 或任意平均比率。
2. 將頁面草圖轉成工作台，再用真實快照驗證：World USD 76,449,272,983、已確認國家 USD 57,765,515,044。
3. 瀏覽器測試發現窄螢幕 SVG 標籤需要依容器重畫，調整為響應式座標，而非單純縮小整張圖。
4. 單國 Malaysia 篩選後，World 維持 76.45B、該國合計為 19.28B，YoY 切成 Malaysia 指標。
5. HHI 無效時維持資料不足；來源覆蓋限制進入產品畫面，未為了畫面完整而虛構數值。
6. 以測試涵蓋篩選、金額精度、缺月、匯出、批次失敗及上一版保留，再進行版本發布。

## 文案修訂

依使用者要求，正式網站移除勵志標語、宣傳式說明與 AI 協作口號。首頁使用「美國半導體進口分析」，各區塊直接標示圖表與資料功能。協作過程保留在專案文件，網站只顯示分析所需資訊。

## 緊湊深色版修訂

依使用者要求，改為預設深色介面、單行小標題與桌面三欄兩列。移除品牌名稱、Logo、側欄、頂部麵包屑與右側資訊；以同列文字分頁切換總覽、明細與方法。HHI 不再出現在介面，保留國家覆蓋率；warehouse 與 JSON 契約未改動。明細縮小列高，每頁 50 筆，表頭固定。

本機瀏覽器檢查約 1280 × 720 時六個區塊的底部約為 700px，可完整顯示於首屏。390px 手機檢查無水平溢位，明細 50 筆正常。前端 5 項測試通過。更新後的單檔預覽仍為專案根目錄 index.html；本次調整以本機預覽為範圍。

後續依使用者要求將桌面總覽改為每列兩個圖表，共三列；手機仍為單欄。保留既有深色配色與緊湊間距。

依使用者後續回饋，保留每列兩個圖表，將主要繪圖高度由 165px 增為 280px、地圖由 153px 增為 270px。圖表標題增為 17px，座標文字增為 11px，排名列與金額同步放大；首頁標題仍維持單行，避免佔用額外空間。

後續將主要內容最大寬度由 1920px 收斂至 1080px 並置中，避免兩欄圖表隨寬螢幕過度拉長。圖表間距改為 8px，收緊卡片內距，保留放大後的文字與繪圖高度。
