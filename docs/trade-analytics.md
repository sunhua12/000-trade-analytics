[ 資料源層 Data Sources ]
├── UN Comtrade Data API（免費 API Key）
│   ├── 美國半導體月度進口明細
│   ├── reporterCode=842
│   ├── flowCode=M
│   ├── frequency=M
│   └── 固定 HS 分類版本，查詢 8542 及所需 6 碼細項
├── USITC DataWeb／HTS 資料
│   └── 美國 HTS 8～10 碼代碼與關稅稅率
└── UN M49 國家與區域代碼
    └── 國家、ISO 代碼及地理區域維度
                │
                ▼
[ 排程與流量控制層 Orchestration ]
└── Apache Airflow（Docker／Astronomer Cosmos）
    ├── Monthly DAG：每月檢查並同步最新資料
    ├── Availability Sensor：透過 getDA／getLiveUpdate 確認新期數
    ├── Backfill DAG：依月份回填 2015～2025 年資料
    ├── Airflow Pool：限制 UN Comtrade 每秒最多 1 次請求
    ├── 每個 Task 僅處理一個 period
    ├── retries=3、exponential_backoff=True
    └── Slack／LINE 失敗告警
                │
                ▼
[ 資料擷取層 Ingestion ]
└── AWS Lambda（Python 3.11／Container Image）
    ├── 使用正式端點：
    │   └── /data/v1/get/C/M/{HS_VERSION}
    ├── API Key 存放於 AWS Secrets Manager
    ├── 明確指定：
    │   ├── reporterCode=842
    │   ├── flowCode=M
    │   ├── partner2Code=0
    │   ├── customsCode=C00
    │   └── motCode=0
    ├── 分開擷取：
    │   ├── Partner Detail：各夥伴國進口資料
    │   └── World Total：partnerCode=0
    ├── 每次最多 100,000 筆，超過時依商品碼拆分
    ├── Schema Validation 與空資料檢查
    ├── HTTP 限流、429／503 重試與指數退避
    └── 結構化 Logging：
        ├── run_id
        ├── period
        ├── query_type
        ├── row_count
        ├── primary_value_sum
        └── request_duration
                │
                ▼
[ 原始資料層 Raw Storage ]
└── Amazon S3
    ├── Immutable Raw JSON
    │   └── s3://trade-raw/un_comtrade/
    │       └── period=202401/query_type=partner_detail/
    ├── manifest.json
    │   ├── request_parameters
    │   ├── checksum
    │   ├── schema_version
    │   ├── hs_version
    │   ├── row_count
    │   └── ingested_at
    └── Processed Parquet／Bronze Layer
                │
                ▼
[ 跨雲載入與資料倉儲層 Data Warehouse ]
└── Airflow BigQuery Load Task ──► Google BigQuery
    ├── raw_dataset
    │   ├── un_comtrade_partner_detail
    │   ├── un_comtrade_world_total
    │   ├── usitc_tariff_rates
    │   └── un_m49_countries
    ├── staging_dataset
    ├── analytics_dataset
    ├── Partition：period_start_date（DATE）
    └── Cluster：partner_code、cmd_code
                │
                ▼
[ 資料轉換與建模層 Transformation ]
└── dbt Core ＋ Astronomer Cosmos
    ├── Staging Models（stg_）
    │   ├── stg_un_comtrade__partner_trades
    │   ├── stg_un_comtrade__world_totals
    │   ├── stg_usitc__tariff_rates
    │   └── stg_un__country_m49
    │
    ├── Intermediate Models（int_）
    │   ├── int_semiconductor_imports_enriched
    │   ├── int_hs_code_crosswalk
    │   ├── int_unit_values_calculated
    │   │   └── 僅在 quantity／net_weight > 0 時計算
    │   ├── int_partner_market_share
    │   │   └── 排除 World 後計算各國市占率
    │   └── int_market_concentration_hhi
    │
    └── Dimensions／Facts／Marts
        ├── dim_countries
        │   └── 國家、ISO 代碼與地理區域
        ├── bridge_country_groups
        │   └── 貿易同盟與地緣政治群組的有效期間
        ├── dim_hs_codes
        │   └── HS 版本、層級與細項分類
        ├── fct_monthly_semiconductor_imports
        │   └── Grain：period × partner_code × hs_code
        └── mart_us_semiconductor_supply_chain
            ├── 進口金額
            ├── 市占率
            ├── 年增率
            ├── 單位價格
            ├── HHI
            └── World 對帳差額
                │
                ▼
[ 資料品質與稽核層 Data Quality & Governance ]
├── dbt Tests
│   ├── unique
│   ├── not_null
│   ├── accepted_values
│   └── relationships
├── API 完整性檢查
│   ├── row_count < 100,000
│   ├── period 正確
│   ├── flow_code=M
│   └── 無重複 Grain
├── Reconciliation Audit
│   └── 各夥伴國進口金額加總 vs partnerCode=0 World
│       ├── 記錄差額與差異率
│       └── 容許誤差預設 ≤ 0.5%
├── API Key 不寫入 Log、Git 或 S3 Manifest
└── GitHub Actions CI
    └── PR 建立暫時 BigQuery Dataset，執行 dbt build 與 pytest
                │
                ▼
[ 分析與服務層 Analytics & Serving ]
├── Streamlit Dashboard
│   ├── 美國半導體進口來源國地圖
│   ├── 核心來源國市占率趨勢
│   ├── HS 細項與進口單價分析
│   ├── 月增率與年增率
│   ├── HHI 供應鏈集中度
│   └── World 對帳與資料新鮮度狀態
└── Trade Alert Bot
    ├── 特定國家進口額年減超過 30%
    ├── 市占率顯著轉移
    ├── HHI 突然上升
    └── 資料延遲或對帳失敗時通知