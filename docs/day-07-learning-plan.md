# Day 7：dbt source、staging 與月份 spine

| 項目 | 內容 |
|---|---|
| 對應計畫 | [20 天實作規格](trade-analytics-spec.md) 的 Day 7 |
| 前置成果 | [Day 6 學習計畫](day-06-learning-plan.md) 的兩張 raw 表、load audit 與單月重跑證據 |
| 預計投入 | 約 3～4 小時；環境安裝與前置補課另記 |
| 核心目標 | 建立 dbt project，在開發 Dataset 成功 build 兩個 staging models 與完整月份 spine |
| 今日交付物 | dbt 設定、source 宣告、staging SQL、dim_months、資料測試、模型說明與驗收紀錄 |
| 目前狀態 | 待實作；本文件是學習計畫，不代表 dbt 或前置入倉已驗收 |

Day 6 已將 landing 正規化到 raw，並維護最新已接受 revision。Day 7 將這些表接進 dbt，建立命名清楚、可測試及可追溯的模型介面；不再次處理來源 MERGE，也不在 staging 計算市占率或 HHI。

## 1. 今天要理解的流程

**預計時間：15 分鐘。**

```text
BigQuery trade_raw
  ├── un_comtrade_partner_detail → source() → stg_un_comtrade__partner_trades
  └── un_comtrade_world_total    → source() → stg_un_comtrade__world_totals

獨立日曆範圍 2023-01～2024-12 → dim_months：每月一列，共 24 列

以上模型 → data tests ＋ model descriptions → 開發 Dataset 驗收
                                               ↓ Day 8
                                  ref() → 國家／商品維度與 fact
```

| 概念 | 白話說明 | 本專案用途 |
|---|---|---|
| dbt project | 管理 SQL 模型、依賴、設定與測試 | 讓轉換流程可重建及檢查 |
| Profile／target | 連線身分與輸出環境 | 讀 raw，寫開發 Dataset |
| Source | 宣告由外部流程建立的資料表 | 引用 Day 6 的 raw，不負責載入 S3 |
| Model | 一個以 SELECT 定義的資料結果 | 建立 staging 與月份維度 |
| `source()`／`ref()` | 引用來源表／其他 dbt 模型 | 建立依賴關係，避免硬編碼模型位置 |
| Materialization | 模型實際儲存方式 | 今日 staging 用 view，月份維度用 table |
| Data test | 查出違反規則的資料 | 必要欄位、grain、日期與來源保真檢查 |
| 月份 spine | 不依賴交易資料的連續月份清單 | 未來辨識缺月，支援按日曆月比較 |

Source 宣告不會建立或搬移 raw；`source()` 讓 dbt 解析資料表位置並建立來源依賴。[dbt source 官方文件](https://docs.getdbt.com/docs/build/sources)

## 2. 前置檢查與 dbt 環境

**預計時間：30～40 分鐘。**

- [ ] Day 6 的真實 202301 明細與 World raw 可查詢，兩邊都有成功 audit。
- [ ] 確認兩張表的實際 Project、Dataset、location、schema 與分區設定。
- [ ] Raw 的日期為 DATE、金額為 NUMERIC、代碼為 STRING，lineage 欄位完整。
- [ ] 同檔重跑、grain 唯一及 revision 保護已有證據。
- [ ] 開發 Dataset 與 raw 使用相同 location，名稱例如 `trade_analytics_dev`。

若前置入倉未完成，先使用獨立測試 Dataset 的 fixture 練習，紀錄中明確標示；不把它當成 M1 或真實來源串接通過。

本日採本機 dbt Core 與 `dbt-bigquery` adapter，搭配 SQL models。建立專案內獨立 `.venv-dbt`，避免改動 ingestion 的 `.venv`；安裝時選定彼此相容且支援所用 Python 的穩定版本，保存精確依賴版本及 `dbt --version`。不要將未確認的最新版直接寫成已驗證環境。

連線準備：

1. 沿用 Day 5 已可用的 GCP Application Default Credentials；尚未設定時，再依官方流程執行 `gcloud auth application-default login`。
2. 建立本機 profile，profile 名稱與 `dbt_project.yml` 一致，target 使用 `dev`，threads 先設為 1。
3. 指定實際 Project、開發 Dataset 與 raw 相同的 location；本地使用 OAuth／ADC，不將憑證放進 Git。
4. 確认操作者可讀 raw 資料與 metadata、在開發 Dataset 建立及替換模型，以及在執行 Project 提交 query job。
5. 執行 `dbt debug` 確認連線，再實際查一張帶分區條件的 raw 表；debug 成功不代表所有 source 都可讀。

連線欄位與認證請參考 [BigQuery adapter 官方設定](https://docs.getdbt.com/docs/local/connect-data-platform/bigquery-setup)，並切換至實際安裝的 dbt 版本文件，避免混用不同引擎的設定。

## 3. 建立 project 與 source 宣告

**預計時間：25～30 分鐘。**

建議於專案根目錄下建立以下結構；清單為今日預定產出，並非已存在檔案：

```text
dbt/
  dbt_project.yml
  profiles.yml.example
  requirements.txt
  models/
    staging/un_comtrade/
      _un_comtrade__sources.yml
      _un_comtrade__models.yml
      stg_un_comtrade__partner_trades.sql
      stg_un_comtrade__world_totals.sql
    marts/core/
      dim_months.sql
      _core__models.yml
  tests/
    assert_partner_grain_unique.sql
    assert_world_grain_unique.sql
    assert_staging_matches_raw.sql
    assert_staging_contract.sql
    assert_month_spine_complete.sql
```

Project 名稱建議為 `trade_analytics`，`profile` 使用相同名稱，`model-paths` 為 `models`，`test-paths` 為 `tests`。今日模型全部輸出至 profile 指定的開發 Dataset，先不加入自訂 schema 命名邏輯。

Source YAML 範例：

```yaml
version: 2

sources:
  - name: un_comtrade
    description: "Day 6 接受的最新原始快照；歷史版本保存在 S3。"
    database: "{{ env_var('DBT_RAW_PROJECT') }}"
    schema: trade_raw
    tables:
      - name: partner_detail
        identifier: un_comtrade_partner_detail
        description: "非 World 夥伴明細，保留特殊代碼與來源追蹤欄位。"
      - name: world_total
        identifier: un_comtrade_world_total
        description: "每個月份、商品及分類版本的一筆 World 總額。"
```

執行前設定 `DBT_RAW_PROJECT`，若 Day 5 使用不同 raw Dataset，需同步調整 `schema`。在 BigQuery 的 source 宣告中，database 對應 Project，schema 對應 Dataset；source 的位置與模型輸出的開發 Dataset 分開設定。

將 `.venv-dbt/`、本機 `profiles.yml`、`dbt/target/`、`dbt/logs/` 及可能產生的 `dbt_packages/` 排除於 Git；提交無憑證的 example 與依賴設定。

## 4. 撰寫兩個 staging models

**預計時間：35～45 分鐘。**

兩張 raw 已完成型別轉換，今日先明列欄位並保持型別。若實際 schema 不符，回到 Day 6 查明原因，不使用 `SAFE_CAST` 把錯誤默默轉成 NULL。

在 `dbt_project.yml` 設定模型讀取的預設範圍：

```yaml
vars:
  raw_start_date: '2023-01-01'
  raw_end_date: '2025-01-01'
```

範圍採左含右不含，涵蓋目標 24 個月。明細模型範例：

```sql
{{ config(materialized='view') }}

select
    period,
    period_start_date,
    reporter_code,
    partner_code,
    flow_code,
    cmd_code,
    hs_version,
    primary_value,
    net_weight,
    quantity,
    ingested_at,
    source_file,
    checksum,
    run_id,
    revision
from {{ source('un_comtrade', 'partner_detail') }}
where period_start_date >= date '{{ var("raw_start_date") }}'
  and period_start_date < date '{{ var("raw_end_date") }}'
```

World 模型使用相同投影與日期範圍，source 改成 `world_total`。Raw 的 `require_partition_filter` 已啟用，因此直接查 raw 的驗證 SQL 也要帶明確日期條件。

這個日期條件是模型的資料範圍；記錄於 description。變數在 dbt 編譯及重建 view 時生效，不是查詢者每次查 view 時動態傳入的參數。未來超出 2024 年的資料需要明確擴展範圍並重建。

- [ ] 不使用 `SELECT *`，避免 raw 新欄位無意間改變下游介面。
- [ ] 不用 DISTINCT 或任意選一列處理重複，交由測試揭露。
- [ ] 不加入 partner／H6／金額過濾來掩蓋違約列；用測試確認契約。
- [ ] 不將重量 NULL 補 0，不刪除 490，不將來源代碼直接改成國家名稱。
- [ ] `ingested_at`、`source_file`、`checksum`、`run_id`、`revision` 全部沿用 raw。
- [ ] 不把 `CURRENT_TIMESTAMP()` 寫回來源擷取時間。

今日可在驗證查詢額外使用 `ref('stg_un_comtrade__partner_trades')`，確認 dbt 能解析模型依賴；後續 dimensions／fact 也透過 `ref()` 引用 staging。

## 5. 建立獨立的月份 spine

**預計時間：20～25 分鐘。**

直接建立總規格中的 `dim_months`，避免再維護一張同用途的暫時模型。日期固定涵蓋 2023 年 1 月至 2024 年 12 月，與目前已載入幾個月份無關。

```sql
{{ config(materialized='table') }}

select
    month_start_date,
    format_date('%Y%m', month_start_date) as period,
    extract(year from month_start_date) as year_number,
    extract(month from month_start_date) as month_number,
    date_sub(date_add(month_start_date, interval 1 month), interval 1 day)
        as month_end_date
from unnest(
    generate_date_array(date '2023-01-01', date '2024-12-01', interval 1 month)
) as month_start_date
```

`GENERATE_DATE_ARRAY` 的日期範圍包含終點，以上會產生 24 個月份。[BigQuery 日期陣列官方文件](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/array_functions#generate_date_array)

- [ ] 共 24 列，月份起始日及 `period` 各自唯一且非 NULL。
- [ ] 最小日期為 `2023-01-01`，最大日期為 `2024-12-01`。
- [ ] 相鄰日期相差一個日曆月，每列都是該月 1 日。
- [ ] 2024 年 2 月月底正確為 `2024-02-29`。
- [ ] 即使 raw 只有 202301，spine 仍有 24 列；以 LEFT JOIN 展示其餘月份缺資料。

Spine 完整只代表日曆完整，不代表交易來源完整。缺月保留為缺資料，不補成 0 進口金額；後續 MoM／YoY 依上一日曆月或去年同月比較。

## 6. 加上資料測試與模型說明

**預計時間：35～40 分鐘。**

在兩份 models YAML 中補每個模型的用途、grain、時間範圍與全部輸出欄位說明。至少解釋金額來源、重量 NULL、特殊代碼、revision 及 lineage 的意義。YAML 的測試設定依已固定的 dbt 版本語法撰寫。

| 檢查 | 實作方式與通過條件 |
|---|---|
| 必要欄位 | `not_null`：grain、reporter、flow、金額及全部 lineage 欄位 |
| 明細 grain | Singular SQL test：按日期、partner、商品、分類 GROUP BY，重複列為 0 |
| World grain | 按日期、商品、分類 GROUP BY 應恰一筆，且 partner 必須為 `'0'` |
| 固定契約 | 明細 partner 不得為 `'0'`；Reporter 為 `'842'`、flow 為 `'M'`、商品為 `'8542'`、分類為 `'H6'`，revision 為正整數 |
| 金額 | 明細非負；World 大於 0；重量及數量的 NULL 合法 |
| 日期 | `period` 等於日期格式 `%Y%m`，日期必須是該月 1 日 |
| 原始資料保真 | 相同範圍 raw 與 staging 雙向 `EXCEPT DISTINCT`，逐欄差異為 0；另驗證 grain 與筆數以捕捉重複 |
| 型別 | 以 BigQuery metadata 核對 DATE、NUMERIC、STRING、TIMESTAMP、INT64，不能只靠欄位描述 |
| 月份完整 | 24 列、邊界、唯一、非 NULL、連續月份及閏年月底均正確 |
| 真實單月存在 | 明細至少一筆，World 恰一筆，避免空表讓所有違規列測試都回傳 0 |

Singular data test 的 SQL 應回傳「違規資料列」，通過時回傳 0 列；不要回傳一列 `is_valid=true` 當作成功。[dbt data tests 官方文件](https://docs.getdbt.com/docs/build/data-tests)

Raw／staging 對比與單月存在檢查以 Day 6 已成功的 202301 為範圍，並對兩個 query type 分別執行；不要求尚未回填的 23 個月已有交易資料。必要欄位檢查需獨立處理 NULL，不能只寫 `column != expected`。

在隔離 fixture Dataset 製造重複 grain、非法金額或月份不符，確認測試會失敗，再恢復正常資料。保留真實 raw，不為了展示測試而修改它。

## 7. 執行 build、保存證據與完成條件

**預計時間：20～25 分鐘。**

以下從專案根目錄執行，假設 dbt 已安裝於 `.venv-dbt`，且 profile 位於使用者的預設 dbt 設定位置；若採其他位置，所有命令一致加上 `--profiles-dir`。

```bash
.venv-dbt/bin/dbt --version
.venv-dbt/bin/dbt debug --project-dir dbt --target dev
.venv-dbt/bin/dbt parse --project-dir dbt --target dev
.venv-dbt/bin/dbt build --project-dir dbt --target dev
.venv-dbt/bin/dbt docs generate --project-dir dbt --target dev
```

本日新 project 只包含上述 3 個模型與相關測試，可直接 build 全部。`dbt build` 依依賴圖執行所選資源及測試；parse 成功不等於倉儲 SQL 已執行，build 成功也不等於資料已通過未實作的業務檢查。[dbt build 官方文件](https://docs.getdbt.com/reference/commands/build)

如 build 失敗，先保存當次 `run_results.json` 與錯誤摘要，再修正並重跑。成功後核對 Console 中模型的實際位置、型別及兩類 202301 的筆數、金額與 lineage，並抽查 NULL 重量及 partner 490。

| 建議證據路徑 | 內容 |
|---|---|
| `docs/day07-dbt-record.md` | Python／dbt／adapter 版本、target、來源與輸出 Dataset、實際執行結果 |
| `docs/evidence/day07-verification.sql` | 日期、型別、grain、raw 對比與缺月查詢 |
| `docs/evidence/day07-verification.md` | Build／test 摘要、雲端 job 識別及 fixture 反例結果 |
| `docs/learning-log.md` | Day 7 實際工時、理解、問題及限制 |

依需要保存已檢查內容的 `manifest.json`、`run_results.json` 或其摘要，註明 invocation 與時間。dbt 的 `manifest.json` 描述模型依賴與設定，與 S3 的來源 manifest 是不同檔案。生成文件若有 metadata 查詢錯誤，記錄限制，不影響已完成測試的事實，也不宣稱文件已驗收。

完成後用自己的話回答：

1. Source 宣告與建立 raw table 有什麼差別？
2. 何時使用 `source()`，何時使用 `ref()`？
3. Day 6 已完成型別正規化，Day 7 staging 還提供哪些價值？
4. 為什麼月份 spine 不能從現有交易月份 SELECT DISTINCT 得到？
5. 為什麼 24 列月份維度不等於 24 個月交易資料完整？
6. 為什麼資料測試全過，仍要檢查真實單月是否存在？

- [ ] dbt 及 adapter 版本固定，dev 連線與 raw 讀取成功。
- [ ] Source 正確指向 Day 6 兩張 raw 表，模型寫入開發 Dataset。
- [ ] 兩個 staging models 成功 build，日期、金額、代碼及 lineage 與 raw 一致。
- [ ] Dim_months 具有連續 24 個月份，缺交易月份仍保留。
- [ ] Grain、契約、保真與非空驗證通過，隔離反例能觸發失敗。
- [ ] 模型及欄位說明、驗證證據與實際學習日誌完成。
- [ ] Fixture 與真實來源驗收分開記錄，尚未完成項目明列。

下一步 Day 8 建立國家／商品維度與事實表，釐清特殊代碼 490 的分類及映射；沿用今日的 staging 與 dim_months。
