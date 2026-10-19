# 靜態前端資料契約 v1

本契約對應美國半導體進口分析。資料來源固定為 UN Comtrade，reporter 842、進口、HS 8542／H6；幣別 USD。機器可讀的 JSON Schema 位於 `docs/schemas/`，由 `src/trade_analytics/export/schemas.py` 產生。

## 資料邊界

- dbt 定義月度指標，Python 負責匯出與驗證，前端負責呈現與使用者選擇造成的聚合。
- 預設展示 2023-01 至 2024-12；匯出日期採 `[start_month, end_exclusive)`，皆為每月第一天，最多 180 個月；多市場 v2 目前涵蓋自 2016 年起的範圍。
- 月份摘要保留完整月份日曆；月份有資料與否由 `has_world`、`has_countries` 判斷，不能把摘要列數當成有效資料月份數。
- 國家資料只包含 `partner_type = country` 且 `classification_status = verified`。特殊代碼 490 保留於原資料管線，但不進入前端國家集合。
- 無資料的月份仍有摘要列；各國缺月不製造明細，不補零。繪圖應使用月份日曆補出 null 斷點。
- 不承諾國家合計等於 World；兩者差距是覆蓋率資訊，不能強制將國家市占重新正規化為 100%。

## 檔案與版本

```text
data/frontend/                       # 本機產物，已由 /data/ 規則忽略
  current.json                       # 原子切換的目前版本指標
  <snapshot_id>/
    manifest.json                    # 此版本的公開 metadata
    monthly.json                     # 此版本的月份資料
    partners.json                    # 此版本的各國資料
  audit/<snapshot_id>.json            # 內部 dbt artifact checksum 與 BigQuery job 紀錄
```

`monthly.json` 與 `partners.json` 都有 `schema_version`、`snapshot_id` 與 `rows`。讀取者先讀 `current.json`，再按該版本的相對路徑讀 manifest 及資料。版本 ID 為 32 位十六進位字串。此目錄是匯出產物，不是已部署的網站。

網站建置時只取已驗證版本目錄的三個公開檔案，一起放入靜態資源；不得把整個 `data/frontend/`、`audit/` 或 dbt artifacts 複製到公開網站。建置時可保留版本子路徑，或將三檔複製到同一個公開 data 目錄，但不可混用版本。

manifest 包含產生時間、起訖範圍、最新實際資料月份、幣別、reporter、HS code/version、Decimal 編碼、HHI 覆蓋容許差，以及兩個資料檔的 SHA-256、位元組大小與筆數。`current.json` 另外保存 manifest checksum。版本更換必須升級 schema_version，前端遇到不支援版本應停止載入。

## 型別與精度

| 類型 | JSON 格式 | 說明 |
|---|---|---|
| 月份 | `"2024-01-01"` | 固定每月第一天，不含時間 |
| 時間 | ISO 8601，含 UTC offset | `generated_at` 是匯出時間，不是資料所屬月份 |
| 代碼 | 字串 | 保留前導零；不可轉為數字 |
| 金額、比率、HHI | 十進位字串或 null | 禁止 float 輸入、NaN、Infinity、指數形式；輸出去除小數尾零 |
| 筆數 | 整數 | country_count 與 row_count |
| 有無來源 | 布林值 | 不得使用字串或 null |
| 缺值 | JSON null | 畫面才轉成「資料不足」，不得改為 0 |

所有比率使用小數比例，`"0.25"` 表示 25%。前端加總與期間市占需使用十進位運算；繪圖才轉 JavaScript Number。BigQuery NUMERIC 本身有 9 位小數精度；匯出器不再額外截斷。HHI 的既有計算使用 FLOAT64 的 POWER，展示模型明確轉成 NUMERIC，這不代表能還原原本浮點運算的精度。

## monthly.json

粒度：月份 × cmd_code × hs_version；目前固定單一商品與版本。

| 欄位 | 型別／可空 | 用途 |
|---|---|---|
| month | 日期 | 月份主鍵與圖表橫軸 |
| cmd_code、hs_version | 固定字串 | `8542`、`H6` |
| world_value | Decimal／可空 | 當月 World 金額，每月只出現一次 |
| previous_year_world_value | Decimal／可空 | 去年同月 World 金額，可能來自展示範圍外 |
| world_yoy | Decimal／可空 | 當月 World／去年同月 World − 1 |
| country_value | Decimal／可空 | 已確認國家合計，無國家資料時為 null |
| country_count | 整數 | 已確認國家列數 |
| country_coverage | Decimal／可空 | country_value／world_value，分母須 > 0 |
| hhi | Decimal／可空 | 僅 hhi_status = ok 時提供 |
| hhi_status | 狀態字串 | HHI 不可用的原因 |
| has_world、has_countries | 布林值 | World 存在、至少有一筆國家資料 |

HHI 狀態：`ok`、`missing_world`、`invalid_world`、`no_countries`、`missing_country_value`、`negative_country_value`、`unreviewed_country`、`insufficient_coverage`。只有狀態為 ok 且覆蓋差距不超過 0.005 才可展示 HHI。來源品質測試通過不代表 HHI 可用。

## partners.json

粒度：月份 × partner_code × cmd_code × hs_version。

| 欄位 | 型別／可空 | 用途 |
|---|---|---|
| month、cmd_code、hs_version | 日期與固定字串 | 對應月份摘要 |
| partner_code | 字串 | 國家／地區識別，不以名稱作 key |
| source_name | 字串／可空 | 顯示名稱；缺少名稱時仍保留代碼 |
| map_iso3 | ISO alpha-3／可空 | 地圖位置；沒有地圖碼不代表沒有交易金額 |
| import_value | Decimal／不可空 | 當月來源國進口金額，允許 0 |
| market_share | Decimal／可空 | 當月來源國金額／World |
| market_share_status | 狀態字串 | ok、missing_world、invalid_world、missing_value |
| previous_month_value | Decimal／可空 | 上個日曆月該國金額 |
| previous_year_value | Decimal／可空 | 去年同月該國金額 |
| mom、yoy | Decimal／可空 | 對應基期 > 0 時才提供成長率 |

`missing_value` 是上游共用狀態，但目前展示契約要求 import_value 非空，因此正常匯出不會產生此狀態。匯出器會拒絕狀態與資料不一致的列。

## 圖表與篩選語意

日期與國家影響如下；Top N 只限制來源國排名，不影響 KPI、趨勢、World 分母或地圖總額。

| 畫面 | 使用欄位 | 日期篩選 | 國家篩選 |
|---|---|---|---|
| 期間 World KPI | monthly.world_value | 所選月份的 World 合計，逐月只計一次 | 不變 |
| 已選國家合計 KPI | partners.import_value | 所選期間加總 | 只加總選定國家；未選表示全部 |
| 最新資料月份 | monthly 的來源旗標、month | 取所選期間最後有來源的月份 | 不變 |
| 月度趨勢 | monthly.month、partners.import_value | 每月加總並保留缺月 | 隨選定國家改變 |
| 來源國排名 | partner_code、source_name、import_value | 各國期間加總、降冪；同額按代碼升冪 | 先篩選國家，再取 Top N |
| 期間市占 | 各國期間金額、期間 World 金額 | 加總金額後相除；World 合計 > 0 才顯示 | 分子改變，分母不變 |
| YoY | partners.yoy 或 monthly.world_yoy | 顯示選定月份的月度 YoY | 單國使用該國；多國／全部使用 World 並標示 |
| 覆蓋率、HHI | monthly.country_coverage、hhi、hhi_status | 顯示選定月份的整體數值 | 不變，不重算選定國家的 HHI |
| 來源國地圖 | map_iso3、import_value | 各國期間金額合計 | 隨選定國家改變，揭露無地圖碼金額 |
| 跨年度月度比較 | month、import_value | 按市場、商品及來源國精確加總；每年度一條線，橫軸固定 1 至 12 月 | 依日期與國家篩選，缺月斷線，不受 Top N 限制 |

期間 World 合計沿用 SQL SUM 的可用值語意，但只要所選月份有缺 World，畫面必須顯示缺月提示與有效月份數；全部缺值時顯示資料不足。期間市占也必須揭露分母缺月，不可把不完整期間說成完整覆蓋。

比率不可直接加總或平均。月度 YoY 不隨日期區間重新計算，基期資料保留在匯出欄位中；資料倉儲沒有前一年來源時必須維持 null。

## 發布前驗證與一致性邊界

匯出必須提供同次 dbt build 的 manifest 與 run_results。工具檢查執行時間在 24 小時內、target 一致、兩個展示模型成功、所有直接依賴展示模型的 data tests 通過，且整次執行沒有 fail／warn／skip。只執行 dbt run 或 compile 不符合條件。

兩個展示 view 在同一個 BigQuery SELECT 中讀取，避免兩次查詢各自取得不同時間的資料。匯出後再次驗證月份完整、grain 唯一、每月國家合計與筆數、覆蓋率、市占、成長基期及 HHI 可用性。比率比對容許 1e-9，HHI 因上游浮點運算容許 1e-4。

dbt artifacts 是建置證據，不是 warehouse lock。執行 build 至 export 期間仍須禁止其他 ingestion／dbt writer；單一讀取陳述式不能修復先前已交錯更新的不同基礎表。後續實作已將 DAG 改為整批占用單 slot Pool，並為支援的本機入口加入 advisory flock。直接 dbt／BigQuery 操作仍須暫停排程；不同主機或不支援 flock 的檔案系統不受本機鎖保護。

驗證完成後先寫完整版本目錄，再以同檔案系統 os.replace 切換 current.json。查詢、驗證或版本切換失敗時保留舊指標。若失敗發生於版本目錄完成之後，可能留下未被指標引用的版本與 audit，不能將它誤認為已發布；本階段不自動刪除舊版本，也不宣稱斷電情境的完整耐久性。

`--verify-only` 可離線驗證 checksum、檔案大小、筆數、型別、版本與跨檔一致性。網站發布將前端程式與 JSON 作為同一版本部署。


## JSON v2：多市場積體電路

v1 繼續相容；v2 的正式 JSON Schema 位於 `frontend/schemas/v2/`。
月度粒度為月份 × 報告市場 × 商品；來源明細另加入來源代碼。流向固定為進口 M，
HS 版本保留於資料列，並先選定完整的接受修訂，不把歷史副本相加。

每列新增 `reporter_code`，`cmd_code` 限定五類積體電路子類。
Manifest 新增 `markets`、`products`、`availability`、`valid_detail_count`、
`positive_amount_count` 及 `row_target_met`，不再以單一市場或 H6 描述全部資料。
金額／比率仍為精確十進位字串，缺月及缺基期維持 null；來源實際申報的 0 仍保留。

兩份資料以同一 BigQuery SQL 敘述的逐列 STRUCT 結果讀取並分頁，保留 DATE／NUMERIC 型別。
檔案、manifest 與 current pointer 均驗證版本、筆數、bytes 及 SHA-256。
多商品圖表重新加總同範圍分子與分母；明細及 CSV 保留商品與原始 HS 版本。
跨市場比較取實際可用月份交集。未達 100,000 筆的預覽明確標示回補中；正式輸出另有筆數門檻。
