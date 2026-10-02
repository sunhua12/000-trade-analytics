# Day 20：最終驗收與作品交付

> 後續現況：2026-10-02 已補至 202607，共 43 月，monthly 恢復且真實 scheduled 發布成功，main push 自動部署通過；本頁原驗收快照保留作歷史。跨週、帳單與預算通知待驗，本人展示暫緩，詳見 [營運紀錄](continuous-operations-record.md)。

| 項目 | 結果 |
|---|---|
| 整理／補驗日期 | 2026-10-02，Asia/Taipei；機器證據時間另標 UTC |
| 本次基準提交 | `278f031c2848581b664aece16b7c64a4ad37c779`；本次交付為文件及唯讀證據，交付提交以 Git 歷史為準 |
| 交付層級 | 雲端可展示、可重建／安全重跑的技術與文件交付；14 項中 13 項通過，1 項待本人展示 |
| Day 20／M5 | 文件與可執行技術工作完成；本人 5 分鐘講解未實測，完整 M5／MVP 保留未完成 |
| 本人實際工時／帳單 | 未提供；不以助理操作時間、query bytes 或預算門檻代填 |
| Live Demo | [美國半導體進口分析](https://trade-dashboard-898093147725.asia-northeast1.run.app) |

## 1. 總規格第 11 節逐項對照

「通過」以實測證據的環境與版本為限。本次未重新部署或重跑正式寫入；歷史證據沿用時明列日期與範圍。原測試 CI 為 Day 19 重建來源 `ff59ba5…`，後續 OIDC 部署證據以該 run 的 artifact 為準；不將歷史成功改寫為本次文件 diff 的遠端 CI。

| 編號 | 驗收項目 | 判定 | 主要證據與界線 |
|---|---|---|---|
| 1 | 乾淨安裝、bootstrap／Terraform 重建、無 drift | 通過 | [重建紀錄](day19-run-record.md#1-乾淨環境與-aws-重建)、[clean CI](evidence/day19/clean-ci.log)、[隔離無 drift](evidence/day19/isolation-no-drift.log)；2026-10-02 隔離 21 個 application 資源新建，backend／OIDC provider 共用，非整個帳號重建 |
| 2 | 受限 OIDC → ECR → Terraform → Lambda、digest 可追溯 | 通過 | [修正後真實 OIDC run](https://github.com/sunhua12/000-trade-analytics/actions/runs/36901101994)、[verification](evidence/day19/deployment-verification.json)、[正式無 drift](evidence/day19/production-no-drift.log)；精確 main subject，無靜態 AWS key，自動部署關閉 |
| 3 | 三類 filters、Errors／Duration、SNS 實收與 run ID 復原 | 通過 | [filter 匹配](evidence/day19/filter-tests.json)、[Alarm history](evidence/day19/alarm-history.json)、[本人實收回報](evidence/day19/sns-receipt.json)、[replay](evidence/day19/lambda-replay.json)；分類／Errors 通知為真實隔離 ComtradeResponseError，其他 filters 為樣本匹配；真實 151001.93 ms Duration／SNS action 沿用 [Day 15](day15-run-record.md)，不宣稱每類皆新做實收 |
| 4 | 固定分類、連續 24 月覆蓋、無混版／靜默漏資料 | 通過 | [coverage.csv](evidence/day11/coverage.csv)、[summary](evidence/day11/coverage-summary.json)、[本次唯讀結果](evidence/day20/query-verification.json)；原 202301～202412、H6、兩類來源；延伸 4 月另計 |
| 5 | 真實 Lambda／S3／BigQuery、筆數／金額可追溯 | 通過 | [24 月真實來源紀錄](day11-backfill-record.md)、[來源查驗](evidence/day11/attestation/202412.json)、[Day 18 E2E](day18-run-record.md)、[Day 19 正式重跑](day19-run-record.md#3-品質停損與正式完整重跑) |
| 6 | 同月無重複 grain、來源修訂保留歷史 | 通過 | [Day 11 修訂 fixture](evidence/day11/revision-fixture.json)、[正式前後比較](evidence/day19/production-comparison.json)、[本次 query](evidence/day20/query-verification.json)；S3 版本保留與 raw 有效 grain 分開，修訂例是 fixture |
| 7 | 市占、MoM／YoY、HHI、條件式單位價值測試／手算一致 | 通過 | [Day 9 驗證與手算](day09-metrics-record.md)、[真實查詢](evidence/day09/verification.json)、[24 月指標摘要](evidence/day11/coverage-summary.json)；HHI 真實資料不可用，有效／無效條件由測試驗證 |
| 8 | PASS／WARN／FAIL 正確、FAIL 不發布 | 通過 | [Day 10 gate 驗證](evidence/day10-verification.md)、[Day 19 十案](evidence/day19/quality-fixture/fixture-checkpoint.json)、[品質程式](../src/trade_analytics/warehouse/quality.py)；Day 19 是真實 BigQuery 合成 fixture，非正式月份故障 |
| 9 | Monthly／三月 Backfill、故障復原與本機限制 | 通過 | [Day 14](day14-run-record.md)、[Day 16](day16-run-record.md)、[排程限制](known-limitations.md)；202501～202503 首次發布，202504 載入回報遺失復原；monthly 仍暫停 |
| 10 | 本機／Cloud Run 展示、缺值與新鮮度 | 通過 | [Day 13 本機 UI](evidence/day13-ui-verification.json)、[Day 18 線上](day18-run-record.md)、[本次線上文字](evidence/day20/live-annual.txt)；2024 年度畫面與 SQL 一致，缺基期／HHI／刷新另存 [UI 摘要](evidence/day20/ui-verification.json) |
| 11 | CI、雲端／dbt 證據、repository credential 檢查 | 通過 | [遠端 CI](evidence/day19/remote-ci.json)、[Day 17 隔離 dbt](day17-run-record.md)、[本次文件／敏感模式檢查](evidence/day20/document-verification.json)；只宣稱掃描範圍未檢出，完整 state／plan 不納入交付 |
| 12 | README、架構、字典、runbook、限制、Live URL | 通過 | [README](../README.md)、[架構](architecture.md)、[字典](data-dictionary.md)、[操作索引](runbook.md)、[限制](known-limitations.md)；本次逐一核對本機相對連結 |
| 13 | 本人 5 分鐘敘事、三項分析、解釋重跑／復原 | 待本人完成 | [展示稿](demo-script.md)與三項查詢／UI 證據已完成；AI 操作與文稿不能證明本人計時講解及理解 |
| 14 | 履歷只用實測數字與完成狀態 | 通過 | [作品敘述](demo-script.md#可使用的作品敘述)僅引用 24／28 月、實測技術；未聲稱成本節省、長期全自動或本人時數 |

## 2. 本次新增與沿用的證據

本次 [reference.sql](evidence/day20/reference.sql)對正式 mart 執行三個固定條件唯讀查詢，每 query 上限 1 GB，保存 [結果／job IDs](evidence/day20/query-verification.json)。不重新擷取來源、覆寫資料或觸發 Airflow。

- 原 24 月連續且每月 Partner grain 唯一；2023 World USD 36,062,821,301、2024 USD 40,386,451,682，年度變化約 +11.99％。
- 2024 國家／地區金額第一為 Malaysia，USD 9,598,343,899；排名排除 490。
- 24 月覆蓋率 63.01％～82.92％，HHI 均 NULL／insufficient_coverage。
- 202504 正式 61 筆、World USD 3,114,414,147、原發布 ID `backfill-202504-32a1f3080f769f4e`，發布時間另存查詢結果。

本次年度 Live UI 實際切換至 2024-01～2024-12，清快取後確認 12 月與精確 World 金額、Malaysia 排名；再檢查 24 月缺基期與 HHI 提示。畫面／文字及操作結果放 `docs/evidence/day20/`。UI 操作由 AI 完成，非本人 5 分鐘展示。

故障案例沿用 Day 19 隔離 handler → 通知實收 → 同 run ID 修正 → 再跑 already_exists；正式 202504 完整安全重跑是另一案例；品質 FAIL 是隔離合成案例。三者不串接成一次端到端正式事故。

## 3. 可交付文件與未完成項

README 更新為目前整體成果，新增架構圖、資料字典、runbook 索引、限制及展示稿，並保留既有詳細操作手冊。此版本適合展示與文件交付，尚不能依總規格宣稱所有必要項目全部完成。

本人待完成項只有驗收第 13 項：依展示稿實際講解約 5 分鐘、展示三項觀察、說明故障／重跑與設計取捨，記錄本人耗時與理解結果，再勾選 Day 20／M5。實際個人工時／帳單仍未知，並不以猜測補齊。

Monthly DAG 暫停與積欠、HHI 不可用、Cloud Run 直接回切失敗、GCP 手動部署及費用界線已在 [限制](known-limitations.md)揭露；這些既有範圍不被本次文件整理改成已解決。
