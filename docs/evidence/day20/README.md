# 第 20 天補驗證據

2026-10-02 以正式 published mart 的唯讀查詢與 Live UI 核對交付文件；未執行部署或正式寫入。

| 檔案 | 內容 |
|---|---|
| [reference.sql](reference.sql)／[query-verification.json](query-verification.json) | 三段固定 SQL 與本次真實 job ID、結果、UTC 時間、處理量；每 query 上限 1 GB |
| [published-schema.json](published-schema.json) | BigQuery get_table 取得的正式 mart 型別；HHI／hhi_raw 實際為 NUMERIC |
| [live-annual.txt](live-annual.txt)／[畫面](live-annual.jpg) | 2024 年度、12 月、World 精確值及 Malaysia 第一 |
| [live-historical.txt](live-historical.txt)／[畫面](live-historical.jpg) | 原 24 月範圍、缺基期與 HHI 不可用 |
| [live-partner.txt](live-partner.txt) | Partner 458 單選後 YoY 為同來源國去年同月 |
| [live-top5.txt](live-top5.txt) | Top N 控制改為 5；當時 Partner 458 單選，並非五個來源國結果 |
| [UI 摘要](ui-verification.json) | 上述畫面文字的條件／提示判定；由 AI 操作，非本人展示 |
| [文件檢查](document-verification.json) | 本機連結、fence／架構基本結構、24 月來源覆蓋及可識別敏感模式掃描 |

SQL 可由具 query job 與 published 唯讀權限的既有 ADC／BigQuery Console 分別執行三個 `-- name` 區塊。保留月份 partition 條件，核對 NUMERIC 原值，不以格式化圖表金額作精確比對。

UI 文字為當次 accessibility tree 或其差異，畫面為當時 viewport；完整圖表數字另以 SQL 核對。文件檢查不是完整 Git 歷史 secret audit，Mermaid 只做結構檢查，不聲稱經外部 renderer 測試。

重建／CI／告警／品質 gate／正式完整安全重跑沿用先前版本證據，索引見 [最終驗收](../../day20-final-acceptance.md)。
