# 美國半導體進口分析平台：20 天學習與實作規格

| 項目 | 內容 |
|---|---|
| 專案名稱 | U.S. Semiconductor Import Intelligence |
| 文件版本 | 2.1，2026-09-12；納入 AWS IaC、OIDC 部署與維運告警 |
| 計畫長度 | 從現有程式接續的 20 個實作日，不含已完成工作的投入時間 |
| 投入假設 | 每日約 3～4 小時，合計約 60～80 小時；含學習、實作、除錯與驗收 |
| 適用目標 | 從企業 ETL／BI 經驗延伸至資料工程與 Analytics Engineering，完成可展示作品 |
| 主要技術 | Python、SQL、AWS Lambda／S3、Terraform、GitHub Actions OIDC、CloudWatch／SNS、BigQuery、dbt Core、Airflow、Streamlit、Docker |
| 第一次展示 | Day 10 完成可對帳的分析資料，Day 13 完成本機 Dashboard |
| 最終交付 | Day 20 完成可重建、可重跑、可解釋的 MVP |

> 本文件取代原版的 5.5～9.5 天時程與 MVP 範圍。原版保存在 `archive/trade-analytics-spec-before-20-day-plan.md`。`trade-analytics.md` 與舊設計文件保留作為歷史參考；若範圍或順序不同，以本版為準。本文件描述待完成工作，不代表功能已實作。

## 1. 計畫目的與學習方式

運用既有的 SQL、ETL、資料品質、報表與維運經驗，完成一套從公開貿易資料擷取、雲端落地、倉儲建模，到互動分析的資料流程。

完成後應能自行回答：

- 為什麼如此定義資料粒度、主鍵與分區？
- API 限流、空資料、欄位異動與資料修訂時，流程如何處理？
- 同一月份重跑，為什麼不會增加重複資料？
- 市占率、年增率與集中度的分母及適用限制是什麼？
- 如何從 Dashboard 的異常數字追查到來源檔案及執行紀錄？

### 每日時間分配

| 活動 | 建議時間 | 方法 |
|---|---:|---|
| 讀文件與理解概念 | 30～45 分鐘 | 只讀當天實作所需章節 |
| 實作與除錯 | 90～120 分鐘 | 延伸既有程式，完成一個可驗收的成果 |
| 測試與結果核對 | 30～45 分鐘 | 檢查成功流程與至少一個重要失敗情境 |
| 學習紀錄 | 15～30 分鐘 | 記錄設計理由、證據與未解問題 |

每天在 `docs/learning-log.md` 記錄日期、Day 編號、實際工時、學到的概念、驗收結果、證據位置與阻礙。可以使用 AI 協助，但必須自己解釋程式，並至少獨立完成一次參數修改或故障排查。

本版新增 Terraform、OIDC 與告警驗收，60～80 小時仍為原始投入估計，不代表新增範圍已可容納。Day 1 重新估算；若超時則增加實作日，不挪用 Day 19～20 的整合與驗收時間。

20 天指實際投入日，不預設起始日期。若每日只能投入 1～2 小時，應延長日曆時程，不刪除核心驗收來宣稱完成。

## 2. 已有成果與起跑點

以下為 2026-09-06 的本機檢查結果。

| 項目 | 狀態 | 新計畫的處理方式 |
|---|---|---|
| Preview API client、query、schema、retry、CLI | 已有實作 | 保留；Day 1 理解與驗證 |
| 本機 NDJSON、Manifest、checksum | 已有實作 | 保留；補強分類版本與金額精度 |
| Lambda handler、S3 adapter、重跑與部分檔案復原 | 已有實作 | 保留；驗證新路徑及真實雲端執行 |
| Dockerfile、AWS Console 部署文件 | 已存在 | 檢查與更新，不視為部署成功證據 |
| 單元測試 | 68 個通過 | 作為起始基準，不要求測試數量只能增加 |
| Ingestion 覆蓋率 | 96.19% | 僅代表 ingestion 模組，不代表全專案 |
| Ruff、mypy | 本機通過 | 持續維持 |
| AWS／GCP 真實資源、API 最新狀態 | 本次未查驗 | Day 1～5 補證據 |
| BigQuery、dbt、Airflow、Dashboard、CI | 尚無對應實作 | 本計畫主要新增範圍 |

起始缺口：目前 query 沒有固定 HS 分類版本欄位；S3 key 未包含商品碼；金額欄位先經過 float；Preview 欄位可能缺少重量及國家描述。這些問題要在擴充資料前處理或明確限制。

## 3. MVP 範圍與優先順序

### 3.1 必須完成

- Reporter 固定美國 `842`，月度進口 `M`，商品先固定 HS `8542`。
- 分開擷取 `partner_detail` 與 `world_total`。
- 選定並驗證一個明確的 HS 分類版本；拒絕未說明的混用。
- 以 `202301～202412` 共 24 個月為預設展示期間；先驗證單月，再回填 3 個月，最後完成 24 個月。
- Lambda → S3 → BigQuery → dbt → Streamlit 的完整資料流程。
- 金額、市占率、MoM、YoY、HHI、對帳狀態與資料最新月份。
- Airflow 本機容器排程、手動回填、重試、執行紀錄及失敗復原。
- GitHub Actions 的離線品質檢查，以及可手動執行的雲端整合驗證。
- Cloud Run 展示部署、操作文件、架構圖、資料字典與成果說明。
- Terraform 管理 AWS 基礎設施與最小權限 IAM；GitHub Actions 透過 OIDC 臨時憑證完成 AWS 部署，不使用靜態 AWS Access Key。
- CloudWatch Metric Filters、Alarms 與 SNS 通知；完成「刻意失敗 → 收到告警 → 依 run_id 追查 → 重跑復原」的真實演練。

### 3.2 有條件呈現

- 單位價值與重量散佈圖：只有有效重量資料才呈現；缺值不補成 0，無資料時顯示原因及覆蓋率。
- 地理地圖：僅呈現成功對應 ISO 的資料，另列無法對應項目。
- 正式 Comtrade API：若 Preview 無法滿足分類版本、完整性或必要欄位，於 Day 2 決定切換，使用 Secrets Manager 管理 Key。

### 3.3 延至 MVP 之後

USITC 關稅整合、HTS crosswalk、HS 6 碼擴充、2015 年起完整回填、國家群組有效期間、Trade Alert Bot、Slack／LINE 通知、Cosmos、非同步 Availability Sensor、自訂網域、GCP IaC、多環境自動發布、每個 PR 建立雲端 Dataset。

這些項目不列入 Day 20 驗收。先完成原生 dbt CLI 與基本 Airflow 編排，再評估是否導入 Cosmos。

## 4. 20 天每日安排

下表的勾選只在交付物與驗收證據都齊全後更新。

| 完成 | 日期 | 學習重點 | 當天實作與交付物 | 驗收條件 |
|---|---|---|---|---|
| [ ] | Day 1 | 現有 Python 分層、依賴注入、fixture | 執行既有檢查；畫出呼叫流程；確認 AWS／GCP、Docker 與 API 存取條件 | 能解釋 query → client → service → storage；列出可用環境與阻礙 |
| [x] | Day 2 | API 契約、HS 分類、資料完整性 | 抽查起訖月份的兩類查詢；確定 endpoint、分類版本、24 個月範圍及重量可用性；建立資料契約 | 有真實回應摘要；若改範圍或切換正式 API，記錄理由及代價 |
| [x] | Day 3 | 冪等、版本與數值精度 | 補 query 分類驗證、商品碼／版本儲存路徑、Decimal 處理、重跑政策及 regression tests | 相同輸入 checksum 穩定；不同商品不撞路徑；不覆寫修訂資料 |
| [ ] | Day 4 | Terraform、Lambda container、IAM、S3 | 完成 AWS bootstrap／remote state；以 Terraform 建立 S3、ECR、Lambda、IAM、Log Group；部署 image 並執行同月兩類查詢與重跑 | 保存 plan／apply、image digest、invocation、S3 URI、筆數與 checksum；重跑無新增有效資料；不以 Console 建置代替 IaC |
| [ ] | Day 5 | BigQuery schema、分區、跨雲載入 | 完成一個月份的 S3 載入 PoC、landing／raw schema 與載入設定；確定單一載入方案 | 真實 BigQuery 查詢成功；明細與 World 均入倉 |
| [ ] | Day 6 | 載入稽核、MERGE、失敗重跑 | 完成正規化、load audit、raw MERGE 與單月重跑；先核對 Manifest 筆數與金額 | 連跑兩次 raw grain 不重複；錯誤可定位至檔案與 job |
| [ ] | Day 7 | dbt source、staging、型別轉換 | 建立 dbt project、source、兩個 staging models、日期 spine 與 model descriptions | 開發 Dataset 可 build；日期、金額、代碼與 metadata 正確 |
| [ ] | Day 8 | 維度與事實表、國家代碼 | 建立國家 seed／dimension、HS dimension、fact；標示 World、國家與特殊代碼 | fact grain 唯一；未對應資料可追查，不靜默丟棄 |
| [x] | Day 9 | SQL 指標、window function | 完成金額、市占率、MoM、YoY、HHI 與有效重量單位價值；補固定資料測試 | 手算結果一致；缺月、缺分母及 0 分母處理正確；見 [驗收紀錄](day09-metrics-record.md) |
| [ ] | Day 10 | 對帳、PASS／WARN／FAIL、發布門檻 | 建立 audit model 與品質 gate；展示單月完整分析 SQL | 真實單月對帳可追溯；人工異常 fixture 能阻擋發布；里程碑 M2 |
| [ ] | Day 11 | 小批次回填、覆蓋率與資料修訂 | 先跑 3 個月，再完成 24 個月；核對每月兩類資料、版本與品質狀態 | 月份覆蓋清單完整；無靜默漏月；異常月份附原因 |
| [ ] | Day 12 | Streamlit 查詢、參數化 SQL、快取 | 建立 Dashboard 篩選、趨勢、Top N 與品質摘要；先使用已驗證 mart | 篩選生效；查詢有日期限制；空結果不 crash |
| [ ] | Day 13 | 視覺化與指標解讀 | 完成來源國圖表、YoY／HHI、資料新鮮度；依資料可用性加入地圖與散佈圖 | 本機展示完整；列出 3 項有數據支持的觀察與限制；里程碑 M3 |
| [ ] | Day 14 | Airflow DAG、task 邊界與 logical date | 建立 Docker Compose、固定版本與 monthly DAG；包裝已完成的 ingestion／load／dbt 操作 | DAG 無 import error；單月可完成；XCom 只含 metadata |
| [ ] | Day 15 | 排程、限流、CloudWatch／SNS | 完成月度執行、有限期數檢查與重試；補結構化失敗日誌；以 Terraform 建立 Metric Filters、Alarms、SNS 並確認訂閱 | 缺資料有明確狀態；驗證三類錯誤 filter 與耗時門檻；真實失敗觸發 SNS，依 run_id 找到日誌 |
| [ ] | Day 16 | 參數化回填、復原 | 建立獨立 backfill DAG；回填 3 個月；故意中斷載入後重跑 | 不混用原生 Backfill 語意；復原後無重複 grain；里程碑 M4 |
| [ ] | Day 17 | CI/CD、OIDC、Terraform | 加入 Ruff／mypy／pytest、DAG、Docker 與 Terraform 檢查；以 OIDC 推送 ECR 並經 Terraform 更新 Lambda；整理手動 dbt 雲端測試入口 | 有成功 CI 與 AWS 部署 run；trust policy 限定來源；無靜態 AWS Key；保存部署 digest 與 plan／apply 證據 |
| [ ] | Day 18 | Cloud Run、Service Account、查詢成本 | 部署 Streamlit；限制資料存取與查詢量；核對線上圖表 | Live URL 可開啟；與 BigQuery 固定條件查詢結果一致；完成正常路徑 E2E |
| [ ] | Day 19 | 整合緩衝、故障與重建驗證 | 依 Terraform／OIDC runbook 乾淨重建；完成失敗 → SNS → run_id 追查 → 重跑復原；驗證失敗不發布 | 保存重建、告警接收、定位與復原證據；未完成項目明列；不追加功能 |
| [ ] | Day 20 | 技術敘事與最終驗收 | 完成 README、架構圖、資料字典、runbook、限制與 5 分鐘展示稿 | 依第 11 節逐項驗收；展示 3 項分析、1 次故障復原及 1 次重跑 |

### 里程碑與依賴

| 里程碑 | 日期 | 必須具備的證據 |
|---|---|---|
| M1：單月可信入倉 | Day 6 | 真實 API／Lambda／S3／BigQuery 證據與重跑結果 |
| M2：可解釋的分析資料 | Day 10 | dbt models、手算核對、品質 gate |
| M3：可展示的資料產品 | Day 13 | 24 個月覆蓋清單、本機 Dashboard、分析說明 |
| M4：可復原的自動流程 | Day 16 | Monthly DAG、3 個月 backfill、故障復原 |
| M5：可交付作品 | Day 20 | CI、Live Demo、乾淨環境重建、文件與驗收紀錄 |

前置里程碑未通過時，不把後續 fixture 展示算成真實整合成功。可以先用 fixture 學習後續模型／UI，但必須標記測試資料，並在 Day 19 補真實驗證。

## 5. 目標架構與載入決策

```text
UN Comtrade
    ↓ 單一 period × query_type × cmd_code × hs_version
AWS Lambda → S3 immutable data + manifest
    ↓ 載入 adapter，等待載入完成並記錄 job／run
BigQuery landing → 驗證／正規化 → raw MERGE
    ↓
dbt staging → dimensions／fact → candidate marts／audit
    ↓ 品質 gate 通過後發布該月份
Published marts → Streamlit → Cloud Run

Airflow：編排擷取、載入、dbt、品質檢查與發布
GitHub Actions：品質檢查 → OIDC 臨時憑證 → ECR image → Terraform 部署 Lambda
Terraform：管理 AWS 資源、IAM、OIDC、remote state 與告警設定
Lambda logs → CloudWatch Metric Filters → Alarms → SNS
Lambda Errors／Duration → CloudWatch Alarms → SNS
```

### Day 5 必須確定單一載入方案

預設使用 BigQuery Data Transfer Service 的 Amazon S3 connector，先以明確檔案範圍載入專用 landing table；不得把 manifest 當成資料檔匯入。Transfer 完成後才執行正規化與 MERGE。

若在 Day 5 的投入時間內無法完成可用的 Transfer PoC，記錄阻礙並改用 Python adapter：讀取已驗證的 S3 object，透過 BigQuery load job 載入 landing。MVP 只維護選定的一種方案。切換時同步更新依賴、權限、測試與 runbook。

兩種方案必須提供相同結果：`run_id`、`period`、`query_type`、來源 URI、checksum、載入 job／run ID、筆數、金額合計、狀態。重試要能查詢既有 job 或以不重複的執行識別恢復，不可盲目 append。

來源檔案名不能假設會自動出現在 Transfer 匯入資料中；透過單次明確檔案集合及 load audit 連結來源，正規化時補上 lineage 欄位。一次只執行一個載入 partition，避免共用 landing table 相互覆蓋。

BigQuery 的 S3 Transfer 支援排程載入，但其檔案匹配與寫入行為仍須依選定設定驗證。[官方介紹](https://docs.cloud.google.com/bigquery/docs/s3-transfer-intro)

## 6. 資料契約與儲存規格

### 6.1 固定查詢與資料限制

| 欄位 | 規則 |
|---|---|
| reporterCode | `842` |
| frequency／flowCode | 月度 `M`／進口 `M` |
| partner2Code／customsCode／motCode | `0`／`C00`／`0` |
| cmd_code | MVP 僅 `8542`；介面與路徑保留單一商品碼參數 |
| hs_version | Day 2 依實際 API 支援設定明確值；回應必須符合該版本 |
| partner_detail | 排除 World；保留特殊代碼並在建模階段分類 |
| world_total | 僅 `partnerCode=0`，每個月份與商品恰一筆 |

Preview 目前程式以 500 筆為截斷警戒；Day 2 確認 endpoint 實際限制後寫入設定。達上限即失敗，不將疑似截斷結果當成完整資料。固定 HS 8542 若仍超限，須切換可滿足完整性的來源方式，不靠截斷或刪除夥伴國繼續。

跨年度資料必須逐月核對 classification code。若預設 24 個月不能在同一分類版本下完整取得，記錄並更換為可驗證的連續 24 個月；不得混版本後宣稱可直接比較。

金額從 JSON 解析開始避免經過 binary float，使用 Decimal 或保留十進位字串，倉儲使用 NUMERIC。序列化需確定且可 round-trip；相應更新 fixture、schema version 與舊檔相容策略。

### 6.2 S3 key 與 Manifest

```text
s3://<raw-bucket>/un_comtrade/v2/
  hs_version=<version>/cmd_code=8542/period=202401/
    query_type=partner_detail/revision=1/data.ndjson
    query_type=partner_detail/revision=1/manifest.json
    query_type=world_total/revision=1/data.ndjson
    query_type=world_total/revision=1/manifest.json
```

原路徑資料保留，新流程使用 `v2` prefix，不自動搬移或覆寫。IAM policy 及部署說明必須跟隨路徑更新。

Manifest 至少包含 request parameters、source、schema_version、hs_version、cmd_code、period、query_type、revision、row_count、primary_value_sum、checksum、ingested_at。API Key 不得出現在其中。

| 情境 | 行為 |
|---|---|
| 相同內容重跑 | 驗證完整 data／manifest 後回傳 `already_exists` |
| 只有其中一個檔案 | 核對現有內容吻合後，只補缺檔；不吻合則失敗 |
| 相同 revision 的來源內容改變 | 回報 conflict，不覆寫 |
| 正式來源修訂 | 操作者明確指定下一個 revision，保存前版；新版本驗證成功後才入倉發布 |
| ingestion 併發 | Lambda reserved concurrency 為 1，Airflow ingestion Pool 為 1；不宣稱已支援多 writer 的原子寫入 |

MVP 允許重跑時重新呼叫 API 後比較 checksum；「略過 API、直接復用現存檔案」不列為必要功能。

### 6.3 BigQuery raw 與稽核

Raw 分成 `un_comtrade_partner_detail` 與 `un_comtrade_world_total`；來源 JSON 欄位先在 landing 保留，再明確轉換。

| 欄位 | 型別／用途 |
|---|---|
| period、reporter_code、partner_code、flow_code、cmd_code、hs_version | STRING |
| period_start_date | DATE，分區欄位 |
| primary_value、net_weight、quantity | NUMERIC，依來源允許 NULL |
| ingested_at | TIMESTAMP |
| source_file、checksum、run_id | STRING，來源追蹤 |
| revision | INT64，來源修訂版 |

- Cluster 使用 `partner_code`、`cmd_code`。
- Raw 的有效 grain 為 `period_start_date × partner_code × cmd_code × hs_version`。
- `MERGE` 僅處理本次 partition；先檢查 staging grain 唯一，並防止較舊 revision 蓋過新版。
- 來源修訂若刪除舊資料列，必須同步刪除該 partition 中新版已不存在的 grain，或採交易式整個 partition 替換；僅 upsert 不足以保證快照一致。
- Raw 保存最新已接受版本，S3 保存歷史原檔；MVP 不建立完整 warehouse history table。
- `audit_ingestion_runs` 追加保存各執行的來源、revision、job ID、筆數、金額及失敗原因。
- 載入筆數與金額應與 Manifest 一致；若來源精度超出 NUMERIC，必須先定義轉換與容許誤差，不能靜默四捨五入。

## 7. dbt 建模、指標與發布

### 7.1 最小模型集合

| 層級 | 模型 | 職責 |
|---|---|---|
| Staging | `stg_un_comtrade__partner_trades`、`stg_un_comtrade__world_totals` | 命名、日期、型別與來源 metadata |
| Dimensions | `dim_countries`、`dim_hs_codes`、`dim_months` | 國家分類、商品版本、完整月份 spine |
| Fact | `fct_monthly_semiconductor_imports` | 有效 grain、金額、重量、revision 與來源 |
| Intermediate | `int_partner_market_share`、`int_market_concentration_hhi` | 指標運算與覆蓋狀態 |
| Audit | `audit_world_reconciliation` | 全體明細對帳、實際國家覆蓋率與品質狀態 |
| Candidate mart | `mart_us_semiconductor_supply_chain_candidate` | 待驗證的分析資料 |
| Published mart | `mart_us_semiconductor_supply_chain` | Dashboard 唯一可用的正式分析來源 |

國家 seed 必須附來源及取得日期，區分實際國家、World、區域／群組與特殊未分配代碼。未對應代碼列入 audit，不直接刪除。MVP 不建立國家群組有效期間 bridge。

### 7.2 指標口徑

| 指標 | 定義 | 邊界與限制 |
|---|---|---|
| 進口金額 | `primary_value` | 幣別與來源口徑記錄於資料字典 |
| 市占率 | partner value／相同月份、商品與版本的 World value | 分母缺少或 ≤ 0 時為 NULL，並觸發品質檢查 |
| MoM | 本月／上一日曆月 − 1 | 以前一日曆月 join；缺月或前期為 0 時為 NULL |
| YoY | 本月／去年同月 − 1 | 以去年同月 join；不可在有缺月時直接使用第 12 筆前的資料 |
| USD／kg 單位價值 | primary value／net weight | 僅重量 > 0 時計算；不是晶片單顆售價 |
| HHI | `SUM(POWER(country_share * 100, 2))` | World 為分母，只計實際國家，尺度 0～10,000 |
| 國家覆蓋率 | 實際國家金額合計／World value | 伴隨 HHI 顯示，不把缺漏資料視為低集中度 |

MVP HHI 採 World 分母，未分配貿易會造成國家市占率合計不足 100%。覆蓋差距大於 0.5% 時，Dashboard 的 HHI 顯示 NULL／資料不足，仍保存內部計算值以供稽核。不得同時改成「已知國家重新正規化」卻沿用相同指標名稱。

不混加 HS 4 碼總類與其 6 碼細項。對供應鏈韌性的描述限於來源集中與轉移，不能單憑貿易 HHI 推斷實際產能、替代能力或因果關係。

### 7.3 對帳與品質 gate

先辨識明細中的實際國家、互斥特殊未分配項目與重疊 aggregate。`partner_sum` 包含可與 World 對應的互斥明細，排除 World 與重疊群組；另外計算只含實際國家的 `country_sum`。不得因排除未分配項目而把正常覆蓋差異誤判成載入損失。

```text
difference = partner_sum - world_total
difference_rate = ABS(difference) / ABS(world_total)
```

| 情境 | 狀態與動作 |
|---|---|
| 差異率 ≤ 0.5% | PASS |
| 0.5% < 差異率 ≤ 2% | WARN，允許發布並顯示品質標記 |
| 差異率 > 2% | FAIL，不發布該 partition |
| World 缺少／≤ 0、重複 grain、必要金額缺值、分類不符、疑似截斷 | FAIL，不發布 |
| 重量或 ISO 缺少 | 保留金額分析，對相關視覺模組顯示限制 |

閾值集中於設定，以上為專案初始規則，不代表來源服務保證；Day 11 檢視歷史分布，調整必須記錄理由，不能只為讓測試通過。

Audit 以 `run_id × period × cmd_code × hs_version` 保存結果，包含差異、覆蓋率、status、tested_at。先持久化 audit，再執行阻擋測試，避免失敗時沒有紀錄。

Candidate build 與正式發布分開。只有 gate 通過的 partition 才以交易式替換／MERGE 更新 published mart；FAIL 保留上一個成功版本，首次失敗則不新增該月份。Dashboard 顯示已發布資料時間與最近一次嘗試狀態，避免把舊資料當成最新成功結果。

## 8. Airflow 與操作規格

- Day 14 選定相容的 Airflow／provider 版本並固定依賴，記錄 Docker 啟動方式。
- 本機 Docker Compose 啟動；MVP 不部署常駐雲端 Airflow。排程只有在本機服務運行時才會執行，此限制須出現在 README。
- Monthly DAG 使用明確 time-based schedule，每月一次；依 logical date 計算上一完整月份，檢查最多 3 個候選月份的資料可用性，補齊可用且尚未成功的期數。
- 尚未發布屬於 `not_available`，不等同 HTTP／驗證失敗；最多檢查固定範圍，不無限等待。記錄最近檢查時間，下一排程或人工執行再查。
- Monthly 與 Backfill 共用單 slot pipeline Pool，避免同時操作共用 landing 或同一 partition；各 DAG 的 `max_active_runs=1`。
- Backfill 使用 `schedule=None` 的獨立 DAG，輸入 start／end period，逐月展開 task；先以 3 個月 smoke test 驗證。此方案不使用 Airflow 原生 Backfill 指令。
- ingestion 工作粒度為單一月份、查詢類型、商品與分類版本；XCom 只傳 URI、row count、checksum、run ID 等 metadata。
- 編排順序：availability → ingest detail／world → load／raw audit → dbt candidate／audit → gate → publish。
- 可重試暫時性 429、5xx、timeout，最多額外重試 3 次並退避；永久驗證、認證與 checksum conflict 不應盲目重試。文件需說明 HTTP 層與 task 層的總請求上限。
- API request 間隔由 client 控制；Airflow Pool 控制併發，不等同每秒請求限制。
- 故障紀錄包含 DAG、task、period、run_id、錯誤類別與 log 位置；不包含 credential。

Airflow 原生 Backfill 依賴 DAG 的時間排程語意；本 MVP 明確採獨立參數化 DAG，避免混用兩套回填方式。[官方說明](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/backfill.html)

## 9. Dashboard、部署與 CI

### Dashboard

- 篩選日期區間、Partner、Top N；商品與分類版本在 MVP 固定顯示。
- 必要畫面：來源國金額與市占率、月度趨勢、YoY、HHI／覆蓋狀態、對帳及最新成功發布月份。
- 地圖與散佈圖依資料可用性提供；缺 ISO／重量顯示缺值數與原因。
- UI 只讀 published marts 及允許的品質摘要 view，不直接讀 raw。
- SQL 使用參數、日期 partition filter、`maximum_bytes_billed`；快取 TTL 可設定，預設 1 小時。
- 固定條件下至少人工核對一組 Dashboard 結果與 BigQuery SQL。

### Cloud Run 與雲端操作

- 綁定 `0.0.0.0` 與 `PORT`；`min-instances=0`，設定最大 instances 與查詢限制。
- 專用 Service Account 具必要的 query job 權限與發布資料集唯讀權限，不在 image 放 JSON Key。
- 使用預設展示 URL；記錄部署 image 的 Git SHA、region、設定及停止／清理方式。
- Day 1 記錄個人可接受的雲端預算；Day 4／5 建資源前配置預算通知與具體服務限制。預算通知不視為硬性費用上限。
- AWS 資源改由 Terraform 管理，Console 僅用於檢視與排障，不再作為建置流程。既有 AWS 資源先 import 並核對 plan，不直接刪除重建。GCP 維持可重做的部署指令與設定，GCP IaC 延後。

### AWS Terraform 與 OIDC 部署

- Terraform 管理 raw S3 bucket、ECR repository、Lambda、最小權限 IAM、CloudWatch Log Group，以及 Metric Filters、Alarms、SNS topic／subscription；OIDC provider 若帳號已有則匯入或引用，不重複建立。固定 Terraform／provider 版本並提交 dependency lock file。
- S3 啟用 Block Public Access、加密與版本控制；Log Group 設定 retention；ECR 設定保留部署／回復所需 image 的 lifecycle policy。資料 bucket 與 state bucket 預設防止誤刪，清理流程明列保留資料與刪除資源的步驟。
- 分離 bootstrap 與 application state。首次以 AWS SSO／其他授權的短期登入執行 bootstrap，建立 state bucket、OIDC trust 與部署角色，再將 bootstrap state 遷移到受控 remote backend；記錄全新帳號與既有帳號的前置條件。不得假設尚未建立的 OIDC role 已能部署自己。
- Remote state 使用獨立 S3 bucket，啟用版本控制、加密、最小存取權與 `use_lockfile` state locking；不將 state、plan 或 credential 提交 Git，敏感 artifacts 限制存取與保留時間。參考 [Terraform S3 backend](https://developer.hashicorp.com/terraform/language/backend/s3)。
- GitHub Actions 部署 job 設定 `id-token: write`、`contents: read`；IAM trust policy 限定 `aud=sts.amazonaws.com` 與指定 repository 的 branch 或 environment `sub`。不使用 repository secrets 儲存靜態 AWS Access Key，也不把憑證寫入 image、Terraform variables 或日誌。參考 [AWS OIDC role](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-idp_oidc.html)。
- Lambda execution role 與部署角色分離：前者只取得所需 S3 prefix、Logs 及條件式 Secrets Manager 權限；後者限制本專案資源，`iam:PassRole` 僅允許指定 Lambda role。Bootstrap 的高權限不沿用為日常部署權限。
- 首次部署先以獨立 Terraform 階段建立 ECR，再建置／推送 image，最後以不可變 image digest 部署 Lambda；日常更新沿用相同流程。Lambda image 設定由 Terraform 單一管理，避免另外呼叫更新指令造成 drift。
- PR 執行不需 AWS 憑證的檢查；AWS plan／apply 與 image push 僅在受信任分支／environment 執行，MVP 可用 `workflow_dispatch`。同環境部署序列化，apply 使用該次已檢視的 plan；保存 Git SHA、image digest、workflow run 與部署結果。回復版本也經 Terraform 更新。

### CloudWatch Metric Filters、Alarms 與 SNS

現有 handler 只有成功日誌，且 `run_id` 可缺省；需先補足失敗事件，不能只建立 filter 就宣稱告警可用。

- 每次 invocation 開始時記錄 `event=ingestion_started`、`run_id`、`aws_request_id` 與可用的查詢參數；未傳 `run_id` 時產生識別碼。終止失敗記錄一筆 JSON `event=ingestion_failed`，包含 `error_type`、`error_category`、`period`、`query_type`、`revision` 與去除敏感資訊的訊息，再重新拋出例外，讓 Lambda 原生 Errors 指標計數。驗證日誌實際可被 JSON filter 解析，不以文字前綴包住 JSON。
- `error_type` 保留具體例外名稱；`error_category` 依下表分類。`ResponseTruncatedError` 繼承 `ComtradeResponseError`，必須先判斷子類，避免同一失敗被兩個 filter 重複分類。其他回應驗證子類歸入 `ComtradeResponseError`；其他未分類失敗仍由 Lambda Errors 告警涵蓋。

| Metric Filter | JSON filter pattern | 發布值 |
|---|---|---|
| ComtradeResponseError | `{ $.event = "ingestion_failed" && $.error_category = "ComtradeResponseError" }` | 1 |
| ResponseTruncatedError | `{ $.event = "ingestion_failed" && $.error_category = "ResponseTruncatedError" }` | 1 |
| StorageConflictError | `{ $.event = "ingestion_failed" && $.error_category = "StorageConflictError" }` | 1 |

- 自訂 metrics 使用專案／環境專屬 namespace，不把 `run_id` 或其他高基數欄位當 dimension。使用無 dimensions 的 filters，default value 設為 `0`；沒有 log ingestion 時仍可能無資料，不能把無資料解讀成流程成功。參考 [Metric Filter 語法與限制](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/FilterAndPatternSyntaxForMetricFilters.html)。

| Alarm | 統計值與門檻 | 評估設定 |
|---|---|---|
| Lambda Errors | `AWS/Lambda`、指定 FunctionName，Sum ≥ 1 | 60 秒 period，1 個 period 中 1 個超標 |
| Lambda Duration | `AWS/Lambda`、指定 FunctionName，Maximum > 150000 ms | 60 秒 period，1 個 period 中 1 個超標 |
| 三個自訂錯誤 metrics | 每個 metric 各建 Alarm，Sum ≥ 1 | 60 秒 period，1 個 period 中 1 個超標 |

- Lambda timeout 初始設為 `180 秒`，耗時門檻設為 `150 秒`；參數集中管理，調整 timeout 時同步檢視告警門檻與 API 重試總耗時。Duration 單位為毫秒，且指標在 invocation 結束後送出，這是事後耗時告警，不是執行中第 150 秒的即時通知。硬逾時可能來不及寫入自訂失敗事件，需以 Errors 與開始事件的 request ID／run_id 追查。參考 [Lambda metrics](https://docs.aws.amazon.com/lambda/latest/dg/monitoring-metrics-types.html) 與 [指標送出時機](https://docs.aws.amazon.com/lambda/latest/dg/monitoring-metrics.html)。
- 所有 Alarm 的 `treat_missing_data=notBreaching`，適用低頻月度執行；本組告警不涵蓋「排程完全沒啟動」。Alarm 進入 ALARM 時通知 SNS；SNS topic policy 限制指定帳號／Alarm 來源。Email endpoint 由部署參數提供並完成訂閱確認，不將個人聯絡資訊提交 Git。
- SNS 通知提供 Alarm 名稱、時間與指標資訊；原生 Alarm 不自動附帶 `run_id`。Runbook 說明依通知時間／函數定位失敗日誌，再使用 `run_id` 串接 Airflow、S3 與載入紀錄。同一次失敗可能同時觸發 Errors 與分類 Alarm，文件註明此行為；Alarm 持續 ALARM 時不保證每次失敗都重發通知。
- 在隔離測試函數／prefix 驗證三類錯誤 filters、原生 Errors 與超過 150 秒的耗時 Alarm，至少一次由真實 handler 失敗一路觸發 SNS 並實際收到通知；不得只用手動設定 Alarm state 代替驗收。故障注入限測試環境，不修改正式來源資料或開放正式事件任意注入錯誤。
- 保存 invocation、Alarm history、SNS 接收時間、對應 `run_id`、修正步驟與重跑結果；確認重跑無重複資料，並保留失敗不發布的 E2E 驗收。告警與自訂 metrics 的費用納入預算，runbook 附停用與清理方式。

### CI

PR／push 的必要檢查：Ruff format／lint、mypy、pytest、DAG import／結構測試、Docker build、terraform fmt -check 與 terraform validate（以 init -backend=false 初始化）。使用隔離依賴避免 Airflow 與 application 套件衝突。

dbt unit／data tests 在專用開發或測試 BigQuery Dataset 執行並保存 artifacts；不宣稱 dbt unit tests 完全不需 warehouse。Day 17 提供手動入口，不要求每個 PR 自動建立雲端資源。dbt 的 unit tests 用固定輸入檢查 SQL 邏輯，data tests 檢查實際模型資料。[官方文件](https://docs.getdbt.com/docs/build/unit-tests)

## 10. 測試、文件與進度管理

### 必要測試矩陣

| 層級 | 重要案例 | 執行方式與證據 |
|---|---|---|
| Python unit | retry、schema、Decimal、分類版本、checksum、路徑、部分檔復原 | 完全 mock；pytest 與 coverage |
| Ingestion integration | 真實單月兩類資料、重跑、S3 checksum | 手動；API／Lambda／S3 摘要，不含金鑰 |
| AWS IaC／部署 | bootstrap、remote state、OIDC trust、image digest、重建後無預期外差異 | Terraform 檢查、plan／apply 摘要、GitHub Actions run 與 Lambda 設定 |
| AWS 告警 | 三類錯誤 filter、Errors、Duration > 150000 ms、SNS、run_id 追查與復原 | filter pattern 樣本測試，加隔離環境真實失敗／耗時演練；保存 Alarm history、通知與復原結果 |
| Load integration | 同月份載入兩次、舊 revision、金額／筆數不符 | BigQuery SQL 與 job ID |
| dbt unit | 分母 0／缺失、缺月 YoY、兩國各 50% 得 HHI 5000、排除 World | 固定輸入與預期結果 |
| Data tests | unique、not_null、relationships、對帳邊界 0.5%／2%、版本 | dbt artifacts、audit table |
| DAG | import、task 依賴、日期跨年、Pool、回填參數、無資料狀態 | 離線 unit，加真實 3 個月 smoke |
| Dashboard | 空結果、篩選、缺重量、無 ISO、只讀發布資料 | AppTest／純函式測試，加人工核對 |
| E2E | 正常單月、失敗不發布、修正後復原、乾淨重建 | Day 18～20 驗收紀錄 |

Python 整體覆蓋率至少 80%；ingestion 與 manifest 至少 90%，新增 load 核心模組至少 85%。覆蓋率不能替代重要情境；不為追求測試數量撰寫只重複實作的斷言。

### 目標交付檔案

保留現有 `../src/trade_analytics/ingestion`、`lambda_handler.py`、`../ingest.py` 與 Dockerfile。逐步新增：

```text
src/trade_analytics/warehouse/    # 載入、正規化、稽核與發布
dbt/                            # models、seeds、tests、設定
dags/                           # monthly、backfill 與共用函式
app/                            # Streamlit 與查詢
tests/                          # 延伸既有 unit／integration，新增 DAG／app 測試
infrastructure/aws/bootstrap/   # Terraform state bucket 與 OIDC／部署角色起始資源
infrastructure/aws/application/ # S3、ECR、Lambda、IAM、Logs、Metric Filters、Alarms、SNS
infrastructure/airflow/          # Compose 與固定版本設定
infrastructure/gcp/              # schema／部署設定與指令
.github/workflows/               # CI
docs/data-contract.md
docs/data-dictionary.md
docs/architecture.md
docs/runbook.md                  # 含 AWS bootstrap、OIDC 部署、告警定位、復原與清理
docs/evidence/aws/               # 去識別化的 IaC、部署與告警驗收證據
docs/learning-log.md
docs/acceptance.md
docs/analysis-findings.md
```

新增 dashboard Dockerfile 使用明確名稱，例如 `Dockerfile.dashboard`，不覆蓋既有 Lambda image 用途。

### 超時與阻礙處理

1. 每日記錄實際投入，不用計畫日期代替完成狀態。
2. 外部帳號／權限受阻時先完成 fixture、模型或文件，真實整合維持未驗收。
3. 優先縮減地圖、散佈圖與 UI 修飾；進階項目不提前加入。
4. Day 19 與 Day 20 的部分時間用於整合緩衝，不拿來增加新技術。
5. 核心資料完整性、金額精度、重跑及失敗不發布不可刪減。若仍未完成，列明差距與剩餘工時，不以 mock 取代真實成功證據。

## 11. Day 20 最終驗收

- [ ] 能從乾淨環境依 README 安裝依賴，啟動必要元件；依 bootstrap／Terraform 流程重建 AWS 資源，保存 plan／apply 證據，後續 plan 無預期外差異。
- [ ] GitHub Actions 透過受限 OIDC role 取得臨時憑證，完成 ECR 推送與 Terraform 部署 Lambda；無靜態 AWS Access Key，部署 image digest 可追溯至 Git SHA。
- [ ] 三類錯誤 Metric Filters、Lambda Errors／Duration Alarms 與 SNS 均經驗證；完成真實失敗 → 收到通知 → run_id 定位 → 重跑復原，且無重複有效資料。
- [ ] 固定分類版本與連續 24 個月份均有覆蓋清單；無靜默漏資料或混版本。
- [ ] 真實 Lambda／S3／BigQuery 流程完成，來源筆數與金額可追溯。
- [ ] 同月重跑不產生重複有效 grain；來源修訂保留歷史原檔。
- [ ] 市占率、MoM、YoY、HHI 與條件式單位價值的測試和手算抽樣一致。
- [ ] PASS／WARN／FAIL 行為正確；失敗 partition 不更新 published mart。
- [ ] Monthly DAG 與 3 個月 Backfill 完成，故障後可復原；本機排程限制已註明。
- [ ] Dashboard 本機與 Cloud Run 均可展示；缺值與資料新鮮度明確呈現。
- [ ] CI 成功，雲端整合及 dbt 驗證證據已保存，repository 無 credential。
- [ ] README、架構圖、資料字典、runbook、已知限制與 Live URL 齊全。
- [ ] 能以 5 分鐘說明設計取捨、展示 3 項有查詢證據的觀察，並解釋一次重跑或故障復原。
- [ ] 履歷敘述只使用實測月份、資料量、執行時間與完成狀態，不把規劃當成果。

完成定義：上述必要項目全部通過，才稱為本版 MVP 完成。若僅本機可展示或尚缺雲端驗證，應明確標示目前交付層級與未完成項目。
