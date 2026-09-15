# Day 4：AWS 部署與驗證紀錄

2026-09-14 補充：bootstrap remote state 與 application 既有資源接管已完成，兩組後續 plan 均無差異。實測 raw bucket 原先未啟用版本控制，本次才啟用；Lambda digest 與執行設定已讀取確認。詳見 [Terraform 接管驗證](evidence/aws/terraform-adoption.md)。下方保留 2026-09-12 的原始紀錄；OIDC bootstrap、其餘治理設定與功能證據仍待補，不宣稱總規格全部完成。

| 項目 | 紀錄 |
|---|---|
| 日期 | 2026-09-12（Asia/Taipei） |
| 功能驗收 | Console 部署與功能檢查完成，依本人確認「檢查全都通過」 |
| 總規格狀態 | 尚待 Terraform／remote state 與部署識別證據補齊，不勾選總規格 Day 4 全部完成 |
| 實際工時 | 未記錄 |
| 對應計劃 | [Day 4 學習計劃](day-04-learning-plan.md) |
| 本機核對證據 | [day04-local-verification.json](evidence/day04-local-verification.json) |

## 1. 實際完成與證據來源

本人完成 ECR、IAM、容器映像部署與 Lambda 設定，執行測試後查看 S3，下載資料確認內容，並回報全部檢查通過。助理本次只讀取下載檔案並核對，未重新呼叫 AWS、部署映像或執行 Lambda。

提供的 S3 截圖顯示 `un_comtrade/v2/hs_version=H6/cmd_code=8542/period=202301/query_type=partner_detail/revision=1/` 中有 `data.ndjson` 與 `manifest.json`，兩者 Last modified 均為 2026-09-12 20:20:08（UTC+08:00）。截圖未顯示 bucket 名稱或 Version ID，亦不是重跑前後的對照證據。

## 2. 下載檔案實際核對

來源為本人提供的 [data.ndjson](../data/data.ndjson) 與 [manifest.json](../data/manifest.json)，僅包含 partner_detail。本次重新解析每一個非空 NDJSON 行，以 Decimal 加總，並對原始檔案位元組計算 SHA-256。

| 項目 | 實際結果 |
|---|---|
| 月份／商品／分類／revision | `202301`／`8542`／`H6`／`1` |
| Schema version | `2.0.0` |
| 筆數 | 67，與 manifest 一致 |
| primaryValue 合計 | 2,799,575,181，與 manifest 一致 |
| SHA-256 | `90002d6c1374e9e48fe946e22613a9c0629766e87a1674eab11a7404a461abcf`，與 manifest 一致 |
| Manifest 擷取時間 | `2026-09-12T12:20:07.713138Z`，臺灣時間 20:20:07.713138 |
| 固定維度 | 月份、商品、H6、Reporter 842、Flow M、Frequency M、partner2Code 0、customsCode C00、motCode 0 全部符合 |
| Grain | period × partnerCode × cmdCode 無重複 |
| World 混入 | 無 partnerCode 0 |
| 金額 | 全部為有限且非負的數值 |

8 項本機核對全部通過，詳細布林結果保存於 JSON 證據。Day 4 明細筆數與合計也符合 Day 2／3 歷史基準；未以歷史值代填本次 World 結果。

## 3. 雲端驗收回報

以下依本人「檢查全都通過」記錄；尚未提供逐次 invocation 原始輸出與 World 下載檔供助理複驗。

| 檢查 | 回報結果 | 證據狀態 |
|---|---|---|
| Lambda 擷取 partner_detail、world_total | 通過 | 明細下載檔已複驗；World 原始輸出待附 |
| 兩類 data 與 manifest 共 4 檔 | 通過 | 明細另有 S3 截圖 |
| 相同事件重跑 | 通過，依前述檢查應為 already_exists 且不改寫物件 | 回傳 JSON、重跑前後 Version ID 待附 |
| 非法月份 202413 | 通過，依前述檢查應失敗且不新增資料 | 錯誤輸出與 Request ID 待附 |
| 筆數、checksum、Decimal 金額核對 | 通過 | 明細已獨立複驗；World 待附 |
| 明細與 World 比較 | 本人回報檢查通過 | World 合計與實際差額未提供，不代填 0 |

測試依計劃使用 202301／8542、revision 1 的兩類事件；實際 run_id、Request ID、執行時間與 duration 尚未提供，不能將計劃範例當成實際輸出。

## 4. 資源與追溯資訊待補

| 資訊 | 目前紀錄 |
|---|---|
| AWS Account／Region／Raw bucket | 未提供；bucket 名稱未出現在截圖 |
| ECR URI／Lambda 名稱／Role ARN | 已回報完成建置，實際識別值待附 |
| Image tag／部署 digest／建置 Git SHA | 待附；不能以目前工作目錄的 SHA 推定已部署版本 |
| 架構／Memory／Timeout／Concurrency | 計劃為 x86_64／512 MB／180 秒／1；實際設定或配額限制待附 |
| 環境變數／S3 與 ECR 設定／IAM policy | 待附實際設定；計劃值不視為已讀取的 Console 設定 |
| CloudWatch | Log Group、各次 Request ID、status、duration 與執行時間待附 |
| S3 URI | 已知兩類 object key 格式；需補 bucket 名稱才可形成完整 URI |
| 物件版本 | 4 個物件重跑前後的 Last modified／Version ID 待附 |
| World 檔案 | data、manifest、row_count、checksum、合計與明細差額待附 |

## 5. 今日理解與操作重點

- 流程為本機程式 → Docker image → ECR → Lambda → S3，CloudWatch 用於查執行紀錄。
- ECR 需先有映像，才能建立對應的 Container image Lambda；本機推送身分與 Lambda execution role 分工不同。
- 專案已有 Dockerfile；建置 amd64 映像後，Lambda 使用 x86_64。
- S3 顯示的資料夾來自 object key 前綴，成功寫入後即可逐層查看，不需手動建資料夾。
- NDJSON 一行一筆 JSON；檔案存在與肉眼正常是初步確認，筆數、checksum、金額與重跑檢查提供更完整驗證。
- 今日未回報具體權限或容器錯誤，不虛構故障與修復過程。

## 6. 收尾與後续

單日計劃採 Console 部署，但目前 [20 天總規格](trade-analytics-spec.md) 的 Day 4 明確要求 AWS bootstrap／remote state、Terraform 管理 S3／ECR／Lambda／IAM／Log Group，以及 plan／apply 證據。因此本日完成的是 Console 路徑的功能驗收，IaC 交付仍待完成。本次未調整總規格的要求，亦未操作或重建雲端資源。

- 保留本次 raw 檔供 Day 5 的 S3 → BigQuery 單月入倉使用。
- 後續補 Terraform 管理既有資源與 remote state，先確認匯入及 plan，避免重複建立或誤刪已有資料。
- 補齊第 4 節的資源、invocation 與物件版本證據。
- 預算金額與通知設定未提供，需補記；資源保留期間持續檢查費用。
- 不再使用時，先停止相關觸發或排程，確認資料保留需求，再清理不需要的 Lambda、ECR 映像與日誌；S3 歷史版本須另行考量。本次未執行停用或刪除。
