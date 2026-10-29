> 歷史文件：此處保留重構前的設計與驗收紀錄。現行入口、排程與發布方式以 [操作手冊](runbook.md) 及根目錄 README 為準；舊命令可能已退役。

# 靜態分析網站遷移計畫

狀態：六個階段均已實作，首次私人網站發布成功。資料管線的正式排程啟用與後續網站版本發布由操作者依 runbook 執行。下文保留整體遷移設計，已實作部分以資料契約與操作手冊為準。

已交付：

- `docs/frontend-data-contract.md`、`docs/dashboard-wireframe.md` 與 `docs/design/dashboard-wireframe.svg`。
- `mart_dashboard_monthly`／`mart_dashboard_partners` dbt views、資料測試與單元測試。
- `trade_analytics.export` 匯出／離線驗證工具與 `docs/schemas/` 機器可讀契約。
- `frontend/` 靜態互動網站、批次 writer lock、網站 release builder 與 Airflow 串接。
- [網站與流程驗收](validation/static-website.md)，包含首次 Sites 私人發布紀錄。
- 實際匯出採 `data/frontend/<snapshot_id>/` 完整版本及 `current.json` 原子指標；內部證據另放 `audit/`，不直接寫入前端公開目錄。

## 目標與範圍

將美國半導體進口分析的 Streamlit 展示，改為讀取 JSON 快照的靜態互動網站。保留 Comtrade、Lambda、S3、BigQuery Raw 與 dbt 資料處理，新增資料匯出與發布層。網站訪客的篩選在瀏覽器內完成。

第一版沿用美國、HS 8542／H6、2023-01 至 2024-12 的展示範圍。擴展月份另由匯出設定控制。第一版不包含使用者上傳、即時 BigQuery 查詢或後端 API。

## 現況

| 位置 | 現有責任 | 調整方向 |
|---|---|---|
| `src/trade_analytics/ingestion/`、`lambda_handler.py` | 取得資料、驗證與保存來源 | 沿用 |
| `src/trade_analytics/warehouse/` | S3 驗證與 BigQuery Raw 載入 | 沿用 |
| `dbt/models/intermediate/` | 市占、MoM、YoY、單位價值與 HHI | 保留既有指標定義 |
| `dbt/models/marts/analytics/mart_us_semiconductor_supply_chain.sql` | 月份 × 夥伴的分析資料，附重複的月份級數值 | 保留，另建前端專用模型 |
| `src/trade_analytics/dashboard/queries.py` | 根據使用者選擇執行多次 BigQuery 查詢 | 抽出匯出所需的設定、參數化查詢與處理量限制 |
| `src/trade_analytics/dashboard/app.py` | 篩選、少量計算、Streamlit／Plotly 呈現 | 以靜態前端取代；遷移期間保留核對 |
| `dags/trade_pipeline/common.py` | 串接最多三個月份的 ingest → load → dbt build | 增加批次完成後的匯出關卡 |
| `.github/workflows/ci.yml` | Python、DAG 與 Docker 檢查 | 補上 JSON 契約與前端建置檢查 |

現有 README 已記錄：dbt 失敗不會回復已建立的模型，Streamlit 可能讀到部分更新。新網站改成只發布驗證成功的資料快照，可保留上一版網站；這不等於 BigQuery 模型也有 rollback。

## 目標資料流

```text
Comtrade → Lambda → S3 → BigQuery Raw
                              ↓
                       dbt build + tests
                              ↓
                      前端專用展示模型
                              ↓
                    Python 匯出至暫存目錄
                              ↓
                  JSON 契約與數據一致性驗證
                              ↓
                   前端建置與展示功能檢查
                              ↓
                   發布完整網站與同版 JSON
```

## 一、dbt：拆開資料粒度

建議新增兩個模型，放在 `dbt/models/marts/presentation/`：

1. `mart_dashboard_monthly.sql`：粒度為月份 × HS code × HS version。包含 World 金額、World YoY、國家合計、國家數、覆蓋率、HHI 與 HHI 狀態。從月份維度、World staging 與現有 HHI intermediate 組合，保留只有 World 或缺少來源國的月份，避免單純從現有 partner mart 去重而漏月。
2. `mart_dashboard_partners.sql`：粒度為月份 × partner × HS code × HS version。從既有分析模型挑選國家名稱、地圖碼、金額、市占、YoY／MoM 及必要狀態；沿用已確認國家／地區的範圍。

World YoY 目前在 Streamlit 的 `world_yoy()` 計算，移到 dbt，使用去年同月對應。去年資料不存在或基期無效時輸出 NULL。若展示起始月份也需要 YoY，必須實際載入前一年資料，不能只延伸日期條件。

新增粒度唯一性、月份關聯、World 去重與 HHI 狀態契約檢查。不要讓前端再用 partner 列推算 World 或重新定義 HHI。

## 二、Python：新增匯出層

建議結構：

```text
src/trade_analytics/export/
  __init__.py
  settings.py       # BigQuery 與匯出範圍設定
  queries.py        # 固定展示模型的參數化讀取
  schemas.py        # JSON 資料契約
  service.py        # 序列化、驗證、輸出
  cli.py            # 可由本機或 Airflow 呼叫
```

匯出器只做讀取、格式轉換與驗證。商業指標仍由 dbt 負責。沿用現有日期範圍驗證、BigQuery location 與 maximum bytes billed；移除展示端快取 TTL 的依賴。

首版每次匯出整個展示範圍，以同一快照為單位，避免月份更新留下新舊混合資料。匯出時禁止與其他 dbt writer 交錯，直到快照完成；目前單 task 的 Airflow Pool 無法保證跨整個批次互斥，需另加涵蓋 build 至 export 的批次鎖，或明確採單一執行入口並禁止其他寫入。

先寫暫存目錄，所有檢查通過才交給前端建置。任一查詢或驗證失敗都不得覆蓋已發布版本。

### JSON 契約

```text
frontend/public/data/
  manifest.json
  monthly.json
  partners.json
```

| 檔案 | 主要內容 |
|---|---|
| `manifest.json` | schema_version、snapshot_id、generated_at、資料月份範圍、幣別、HS 分類、各檔案筆數與 checksum |
| `monthly.json` | 每月 World 金額、World YoY、覆蓋率、HHI 與狀態 |
| `partners.json` | 各月份、各國的金額、市占、YoY／MoM、名稱與地圖碼 |

先量測實際筆數與壓縮後大小，再決定是否按年份分檔。不要只匯出固定 Top 10，否則日期篩選後無法得到正確排名。

契約規則：

- 月份使用 `YYYY-MM-01`，時間戳使用含時區的 ISO 8601。
- partner code 使用字串，保留代碼原貌。
- BigQuery NUMERIC／Decimal 使用十進位字串，避免序列化或 JavaScript Number 損失精度；前端以十進位運算處理總額，繪圖時才轉 Number。
- 比率以小數比例表示，例如 0.25，畫面格式化為 25%。
- 缺值使用 JSON null，不填 0、不輸出 NaN，也不在資料中放「資料不足」。
- 只挑選展示需要的欄位。BigQuery job ID、S3 路徑與內部執行資訊保存在內部匯出紀錄。

## 三、前端：呈現與可控的互動

新增獨立 `frontend/` 目錄，與 Python 專案分開管理依賴及建置。採可輸出 HTML／CSS／JavaScript 靜態資源的前端工具；正式實作時再確定框架、圖表套件與託管平台。

首版頁面順序：

1. 主視覺與分析問題：美國半導體進口來自哪裡，來源結構如何變化？
2. 日期、國家與 Top N 篩選。
3. 期間 World 金額、已確認國家合計與最新資料月份。
4. 月度趨勢、來源國排名與市占。
5. YoY、覆蓋率與可用時的 HHI。
6. 來源國地圖與最新選定月份的金額／YoY 散佈圖。
7. 資料來源、指標定義、資料限制與更新時間。

前端的允許計算：日期／國家過濾、金額加總、排序、Top N、期間國家金額除以期間 World 總額。這些是使用者選擇造成的展示聚合。

固定語意：

- World 總額不隨國家選擇變動；選定國家合計另有標籤。
- 月度市占、YoY、MoM、覆蓋率與 HHI 使用 dbt 的值。不可直接加總或平均比率。
- 單國 YoY 顯示該國指標；多國或全部時沿用現有 World YoY，清楚標示其範圍。
- HHI 與覆蓋率保持整體月份指標，不因國家多選而重算。HHI 僅在狀態為 ok 時顯示。
- 缺月保留斷點；空結果、JSON 載入失敗與無去年同期都有明確畫面。
- 散佈圖沿用所選結束月份，不在缺值時偷偷改用另一個月份。
- 地圖排除未確認特殊代碼，無地圖碼的國家仍計入適用的總額並揭露未映射金額。

## 四、排程與發布

分兩階段導入：

1. 先保留現有 DAG，手動執行 dbt → export → 前端 build → 發布，完成真實資料驗收。
2. 再將匯出接到 monthly 與 backfill 共用流程，整批選定月份成功完成後匯出一次；網站發布另設明確步驟。

`wire_months()` 目前固定建立三組 task。Monthly 的未使用月份會 skip，Backfill 則回傳 unused。接續匯出時需依 plan 的實際選定數與 build 結果判定：至少一個月份成功、所有選定月份完成、沒有失敗，才可匯出。不能直接接最後一個 build，也不能僅用 all_done 而忽略失敗。

網站程式碼與 JSON 作為同一個版本發布，使用託管平台的完整部署切換機制；禁止逐檔覆蓋正式網站。部署失敗保留上一版。manifest 的 generated_at 表示匯出時間，畫面另顯示 latest_data_month，避免誤認為即時資料。

第一版可將驗證過的公開 JSON 提交到 repository，讓網站建置不需雲端憑證；未來自動化時可改以版本化 artifact 傳遞。repository 政策與託管平台在實作時選定。

## 五、實作順序與驗收

| 階段 | 交付物 | 驗收條件 |
|---|---|---|
| 1．指標契約 | 欄位、粒度、篩選語意與頁面草圖 | 每個圖表可追溯 dbt 欄位 |
| 2．dbt 展示模型 | monthly／partners 模型與測試 | BigQuery 真實 build／tests 通過，World 每月唯一，缺月及 World-only 情況可解釋 |
| 3．JSON 匯出 | CLI、schema、同版快照與匯出紀錄 | 真實資料成功匯出；型別、精度、NULL、checksum 正確；失敗不更新可發布資料 |
| 4．前端網站 | 響應式頁面、圖表、篩選與狀態 | 固定期間、單國、多國、跨年篩選與 BigQuery 對照一致 |
| 5．發布 | 可開啟的網站與更新流程 | 全新環境可建置；網站與 JSON 同版；失敗保留上版 |
| 6．遷移收尾 | 移除 Streamlit、更新文件與 CI | 新網站功能驗收完成後，才移除舊展示依賴與測試 |

必要的代表性測試：World 不重複加總、跨年 YoY 與缺月、HHI 狀態、Decimal／null 序列化、日期與國家篩選聚合、匯出或發布失敗保留上版，以及 DAG 未使用月份不誤擋／失敗月份不誤放行。沿用現有資料層測試，避免為每個 UI 元件新增重複測試。

最後更新 `pyproject.toml`、`.github/workflows/ci.yml`、`tests/unit/test_dashboard.py`、`.env.example`、`.gitignore`、`README.md`、`docs/runbook.md` 與資料契約。`dashboard` optional dependencies 待新網站驗收後移除，BigQuery SDK 留在匯出／warehouse 依賴中。

## AI 協作證據

保存初始 wireframe、設計需求、AI 產出的第一版與修改理由；另保存一組從 BigQuery 到 JSON 再到畫面的數字核對紀錄。面試時可以具體說明自己如何定義資料契約、限制 AI 的計算範圍、發現重複加總或篩選語意問題，以及驗證最後成品。
