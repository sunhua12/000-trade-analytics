# 靜態前端資料層驗收紀錄

驗收日期：2026-10-16（Asia/Taipei）。前三階段已完成：資料契約與頁面草圖、dbt 展示模型、真實 JSON 匯出。

## 本機驗證

- `scripts/ci_checks.sh` 通過 Ruff 格式、lint、mypy 與 pytest。
- Python 測試：40 passed、1 skipped。跳過的是需明確啟用的外部 Preview API integration test。
- 匯出測試包含 Decimal 精度、缺月與 World-only 月份、跨年基期、grain／總額／HHI 一致性、失敗保留前版、checksum、JSON Schema 同步與離線 CLI。
- `git diff --check` 通過；頁面草圖 SVG 已通過 XML 解析。

## BigQuery 真實驗證

- 在隔離 Dataset `trade_ci_presentation_20261016_v3` 執行完整 dbt build；Raw sources 為唯讀，未更新正式分析 Dataset。
- 成功 40 個節點：14 個模型／seed 建置，22 個 data tests、4 個 unit tests；WARN／ERROR／SKIP 皆為 0。
- 最終 dbt invocation：`b3067e23-9685-42cf-9c73-684b11a76036`。
- 完整 artifacts 位於本機 `data/presentation-validation-final/`，由 `/data/` 規則排除於 Git。
- 雲端驗證發現既有 `assert_analytics.sql` 與 `assert_data_flow.sql` 的無 FROM／巢狀 EXISTS 與 BigQuery 相容性問題，已改寫為具名 CTE、明確聚合與 anti-join，保留原本檢查目的；最終兩個測試皆通過。

## 真實 JSON 快照

- 版本：`d7c91dfa3ea9477d8d2f41b02b956afa`。
- 匯出時間：`2026-10-16T06:40:28.684478+00:00`。
- 範圍：2023-01 至 2024-12，24 筆月份摘要、1,536 筆國家月份明細。
- 24 個月份皆有 World 與國家資料。
- 2023-01 World 金額：USD 2,799,575,181；2024-12：USD 4,054,690,213。
- 24 個月份的 HHI 狀態均為 insufficient_coverage，公開 HHI 維持 null；資料測試通過不會強制把不完整集中度改為可用。
- `--verify-only` 成功核對版本、型別、checksum、位元組大小、筆數、月份／國家總額、成長率與其他跨檔一致性。
- `monthly.json`：sha256:c7a0eabc4bdd5eb9288ec599f10582cb2110724910f84ecb1710a228b32301a2。
- `partners.json`：sha256:959c7c7177b4eeed3354c1e4bce940a4657b0d94690a552e7c38a1b282d25ac5。
- 本機版本指標：`data/frontend/current.json`。快照已保存在本機，即使隔離測試表到期，JSON 仍可使用。

## 後續邊界

尚未建立正式前端、修改 Airflow DAG、部署網站或移除 Streamlit。正式環境要匯出新資料，須先在相同 target 執行成功的 dbt build，並在 build 至 export 期間禁止其他 writer。此階段提供本機完整快照與原子指標切換，不提供 warehouse rollback 或跨流程鎖。
