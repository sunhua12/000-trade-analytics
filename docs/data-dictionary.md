# 資料字典與指標口徑

依目前 raw DDL、dbt SQL／schema 與 Publisher 定義整理，核對日期為 2026-10-02；正式 mart 型別另以 [實際 schema](evidence/day20/published-schema.json)查核。此文件描述資料模型；歷史數值見 [最終驗收](day20-final-acceptance.md)，來源接受規則見 [資料契約](data-contract.md)。

## 資料層與粒度

| 資料 | 粒度／鍵 | 用途 |
|---|---|---|
| S3 `data.ndjson`／`manifest.json` | 月份 × 商品 × 分類 × query_type × revision | 不覆寫的來源版本；decimal 字串保留精度 |
| `trade_raw.un_comtrade_partner_detail` | period × reporter_code × partner_code × flow_code × cmd_code × hs_version | 最新已接受明細；固定其他維度；revision 為 lineage，不是重複有效 grain 的額外鍵 |
| `trade_raw.un_comtrade_world_total` | 同上，partner_code＝`0`，每月恰一筆 | 獨立 World 分母 |
| `fct_monthly_semiconductor_imports` | 與明細相同 | 追加國家／商品／月份映射；保留特殊代碼 |
| `int_partner_market_share` | 與 fact 相同 | 市占、前月／去年同月基期、MoM／YoY、單位價值 |
| `int_market_concentration_hhi` | 月份 × 商品 × 分類 | 月份級國家覆蓋與 HHI 狀態 |
| `mart_us_semiconductor_supply_chain_candidate` | 與 fact 相同 | dbt 可重建候選，不供正式 Dashboard 直接讀取 |
| `trade_analytics_published.candidate_batches` | candidate_batch_id × fact grain | 凍結候選快照，供品質查核及發布 |
| `trade_analytics_published.mart_us_semiconductor_supply_chain` | 與 fact 相同 | 通過 gate 的正式 partition；追加發布 metadata |
| `quality_audit_history` | 一次 run_id／candidate_batch_id 的品質嘗試 | 追加 audit／reason codes／tested_at，不覆寫歷史 |
| `publication_quality_summary` | period × cmd_code × hs_version | 最新品質、最新發布嘗試與正式版本分開顯示 |

Raw DDL 見 [raw-tables.sql](../infrastructure/gcp/raw-tables.sql)，正式表由 [Publisher](../src/trade_analytics/warehouse/publish.py)建立。模型 Dataset 依 dbt target／環境設定；不能假設所有歷史 dev Dataset 都是正式 target。

## Raw 與 lineage 欄位

| 欄位 | BigQuery 型別 | 定義／缺值 |
|---|---|---|
| period／period_start_date | STRING／DATE | `YYYYMM`／每月 1 日，查詢使用月份 partition 條件 |
| reporter_code／partner_code | STRING | 固定 `842`／來源夥伴原碼；World 為 `0` |
| flow_code／cmd_code／hs_version | STRING | `M`／`8542`／`H6`；不混用分類 |
| primary_value | NUMERIC | USD；明細有限非負，World 必須大於 0 |
| net_weight | NUMERIC | kg；NULL 保留，非正值不計單位價值 |
| quantity | NUMERIC | 來源數量；不同數量單位不能直接加總比較 |
| ingested_at | TIMESTAMP | 來源寫入時間；安全重跑保留既有來源時間 |
| source_file | STRING | S3 原檔 URI，查找 manifest／revision |
| checksum | STRING | SHA-256 內容校驗，並與 manifest／load audit 查驗 |
| run_id | STRING | raw 載入／來源鏈路身分，與 published_run_id 分別解讀 |
| revision | INT64 | 正整數來源版本；新 revision 保留 S3 歷史 |

來源 landing schema 的金額／重量／數量為 STRING，load 正規化成 NUMERIC；不將早期 Transfer PoC 當目前載入實作。來源固定 `partner2Code=0`、`customsCode=C00`、`motCode=0`，由 ingestion 驗證，未全部保存成 normalized raw 欄位。

## 維度與 fact 追加欄位

| 欄位 | 型別 | 定義 |
|---|---|---|
| source_name／hs_description | STRING | 已保存參考表的來源名稱／商品說明 |
| partner_type | STRING | country／special／group／unknown 等分類；以 seed 為準 |
| classification_status | STRING | verified 或 needs_review 等；未知映射不默認已確認 |
| map_iso3 | STRING | 已確認地圖碼；空字串正規化 NULL；490 無地圖碼 |
| reconciliation_role | STRING | detail／unresolved 等；490 為 detail，仍為 special |
| country_mapping_found／hs_mapping_found／month_mapping_found | BOOL | 維度 join 是否存在，不等同指標可用 |

`dim_countries` 另保存原 ISO／group 標記、source_note、來源 URL、retrieved_at、classification／mapping 依據。世界總額與特殊代碼仍留存；地圖與國家排名只取已確認 country。

## 指標與缺值規則

| 欄位 | 型別／單位 | 計算與條件 |
|---|---|---|
| world_value | NUMERIC／USD | 獨立 World；在每個 Partner 列重複，跨列不得直接 SUM |
| market_share | NUMERIC／比率 | primary_value ÷ World；World 無效時 NULL，百分比由畫面乘 100 |
| market_share_status | STRING | ok／missing_world／invalid_world／missing_value |
| previous_month_value／previous_year_value | NUMERIC／USD | 同 Partner／商品／分類的上一日曆月／去年同月，非上一筆資料 |
| mom／yoy | NUMERIC／比率 | 當期 ÷ 對應基期 − 1；基期缺失或不大於 0 時 NULL |
| unit_value_usd_per_kg | NUMERIC／USD 每 kg | primary_value ÷ net_weight，僅重量 > 0；是條件式單位價值，不是晶片單價 |
| country_value／country_count | NUMERIC／INT64 | country 類金額合計／列數；不含 special／group |
| country_coverage | NUMERIC／比率 | country_value ÷ World；非重量有效比例 |
| hhi_raw | NUMERIC | SUM((country 金額 ÷ World × 100)²)；內部診斷值 |
| hhi／hhi_status | NUMERIC／STRING | 覆蓋與 1 的差距 ≤ 0.005 且國家值／分類有效才顯示；否則 NULL 並標示原因 |

HHI 狀態由模型檢查 missing_world、invalid_world、no_countries、missing_country_value、negative_country_value、unreviewed_country、insufficient_coverage，最後才為 ok。HHI 以 World 為分母，不把剩餘國家重新正規化成完整市場。原 24 月皆覆蓋不足，不能聲稱集中度低或把 NULL 畫成 0。

Dashboard 的期間排名占比＝該來源期間金額合計 ÷ 期間各月 World 合計；期間 World 每月只取一次。未選／多選 Partner 時展示 World 月度 YoY，單選時展示該 Partner YoY；百分比不跨月份或 Partner 加總／平均。

## 品質與發布欄位

| 欄位 | 型別 | 語意 |
|---|---|---|
| candidate_batch_id／candidate_hash | STRING | 凍結候選身分／內容 hash，防止品質與發布對象不一致 |
| quality_status／published_quality_status | STRING | 正式版本品質 PASS／WARN，不等於最新品質嘗試 |
| published_run_id／published_at | STRING／TIMESTAMP | 正式版本與成功發布時間；同版本安全重跑不更新 |
| latest_run_id／latest_quality_status／latest_tested_at | STRING／STRING／TIMESTAMP | 最新品質嘗試；FAIL 仍可與較早正式版本並存 |
| reason_codes | ARRAY<STRING> | 品質原因，可為空陣列 |
| latest_publish_run_id／latest_publish_status／latest_attempted_at | STRING／STRING／TIMESTAMP | 最新發布操作；缺操作時 NULL，unknown 必須追查 job／交易，不能當成功 |

對帳使用 `reconciliation_role=detail` 合計對 World 的絕對差異率：其餘檢查皆通過時，≤ 0.5％ 為 PASS，> 0.5％ 且 ≤ 2％ 為 WARN，> 2％ 為 FAIL；來源、映射、grain、候選指標等硬性錯誤直接 FAIL。PASS／WARN 可發布，FAIL 不更新正式 partition。品質 PASS 與 HHI 可用是不同條件。
