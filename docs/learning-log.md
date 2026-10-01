# Trade Analytics 學習與實作日誌

最新補充（2026-09-14）：Day 4 的 Terraform state 管理與既有資源接管已完成，詳見文末補充；Day 4 原始紀錄保留歷史狀態。

依 [20 天實作規格](trade-analytics-spec.md) 記錄實際進度、驗證結果與待辦事項。計畫工時與實際工時分開記錄；完成狀態以實作結果及本人確認為準。

## Day 1：理解資料擷取流程與確認開發環境

| 項目 | 紀錄 |
|---|---|
| 完成確認日期 | 2026-09-08 |
| 狀態 | 已完成；本人確認「Day 1 檢查都 OK」 |
| 對應內容 | [Day 1 學習計畫](day-01-learning-plan.md) |
| 實際投入時間 | 未記錄，不以預估的 3～4 小時代填 |
| 今日成果 | 確認主要資料流程、完成 Day 1 檢查，修正全專案 mypy 型別錯誤 |

### 1. 資料流程與學習範圍

本日以理解成功擷取流程為主，不要求逐行理解全部測試或抽象設計。

```text
ingest.py：接收 CLI 參數
    ↓
ComtradeQuery：驗證月份、商品碼與查詢類型
    ↓
ComtradeClient：呼叫 API、解析回應
    ↓
IngestionService：檢查資料契約、排除 World／檢查重複
    ↓
LocalStorage：產生並寫入 data.ndjson 與 manifest.json
    ↓
CLI：輸出筆數、檔案路徑與 checksum
```

Lambda 從 event 接收參數，重用 query、client 與 service，最後改由 S3Storage 寫入 S3。

學習順序確定為：先追成功流程，再挑少量業務規則測試閱讀；修改某個功能時，才深入研究該功能的測試。HTTP mock、Protocol、clock／sleep 注入與 S3 故障復原留待第二輪深入。

### 2. 檢查與驗證結果

以下命令結果來自本次型別修正後的實際執行；本日補寫日誌時未再次執行。

| 檢查 | 命令 | 結果 |
|---|---|---|
| 全專案型別檢查 | `.venv/bin/mypy .` | 23 個來源檔案通過，無錯誤 |
| 測試 | `.venv/bin/pytest -q` | 68 個通過，2 個整合測試略過 |
| 程式規則 | `.venv/bin/ruff check src tests ingest.py` | 通過 |
| 格式 | `.venv/bin/ruff format --check src tests ingest.py` | 23 個檔案格式符合規範 |
| Diff 空白檢查 | `git diff --check` | 通過 |

2 個整合測試因未使用 `--run-integration` 而略過，不能以本次 pytest 結果代表真實 API 測試已通過。本機擷取及其餘 Day 1 檢查，由本人整體確認完成；個別 CLI 輸出、資料筆數與 checksum 未附於本日誌。

### 3. 遇到的問題：mypy 檢查範圍擴大

先前使用 `mypy src ingest.py`，只檢查應用程式。改執行 `mypy .` 後，測試檔也納入 strict 型別檢查，出現 8 個錯誤，分布於 6 個測試檔。

| 問題 | 修正與理解 |
|---|---|
| `json.loads()` 回傳 Any | fixture 回傳前用 `isinstance(payload, dict)` 確認 JSON 是物件，讓型別範圍縮小 |
| `storage_module.os` 並非明確公開匯出 | 直接使用測試已匯入的 `os`，替換相同模組物件的 `replace` |
| `query_type` 傳入字串 | 改用 `QueryType.PARTNER_DETAIL`；執行時可轉換，不等於靜態型別相容 |
| 使用 `yield` 的 fixture 標成一般回傳值 | 改為 `Iterator[IngestionService]`，反映 generator 的實際行為 |
| `dict[str, str]` 傳給 `dict[str, object]` | 測試 event 宣告改為 `dict[str, object]`；可變 dict 的型別參數不是協變 |
| AWS SDK 型別資訊與介面 | 環境已具備 stubs，將 `boto3-stubs[s3]` 納入開發依賴，移除多餘 ignore，並修正 S3 Protocol |

修正期間，已安裝的 AWS stubs 另外揭露了舊 `type: ignore` 已不需要，以及 S3 Protocol 與 SDK 簽章不相容。最終將 Protocol 限定為實際使用的參數，回傳值以 `Mapping` 描述，通過真實 SDK 與測試替身的型別檢查。

本次改動為型別宣告、開發依賴與測試寫法，資料擷取與儲存的業務邏輯未變更。

### 4. 設計檢視結論

- 主要分層有現實用途：CLI 與 Lambda 已共用擷取與驗證邏輯，本機與 S3 分別處理儲存。
- Manifest、checksum、重試與半成品復原有助於追蹤及重跑，保留。
- Schema 明確定義的欄位偏多，部分類別與小函式可更精簡，但本日未進行重構。
- 覆蓋率高不代表每個測試都有效；曾辨識到 CLI 的 secret 測試未把假 secret 注入受測流程，這項測試品質問題仍待後續改善。

### 5. 核心概念整理

| 問題 | 重點 |
|---|---|
| 為什麼分開 Partner Detail 與 World Total？ | 明細用來分析來源國，World 提供總額分母與對帳基準；避免把總計混入明細加總 |
| 為什麼 service 獨立於 CLI？ | 資料規則可由 CLI 與 Lambda 共用，並可用固定資料測試 |
| Manifest 與 checksum 有何差別？ | Manifest 保存查詢及稽核資訊；checksum 用來比對序列化內容是否一致，不代表業務數字必然正確 |
| 測試如何不連外？ | 用 fixture 與假 client 提供可預期的資料，再檢查正常及錯誤情境 |

此表為本次討論整理，供複習使用，不作為逐項口頭測驗的紀錄。

### 6. 環境與證據紀錄

- Python／專案 `.venv`：可用，已有測試與型別檢查結果。
- Docker、AWS、GCP、GitHub：依本人「Day 1 檢查都 OK」的回報記錄為已確認；Region、Project ID、既有資源與權限細節未逐項記錄。
- 本機擷取：依本人回報完成；計畫預設位置為 `data/preview/period=202401/`，實際檔案位置與內容本次未重新查驗。
- 雲端預算金額：未記錄，建置雲端資源前需補具體金額與限制。
- 未回報新的阻礙；本日不代表已完成 Lambda／BigQuery 真實雲端整合驗收。

### 7. 下一步：Day 2

依規格進行 API 契約與資料完整性確認：抽查展示範圍起訖月份、確認 HS 分類版本與欄位可用性，決定 Preview 是否足夠，並記錄兩類查詢的真實回應摘要。先完成資料來源決策，再進入 Day 3 的儲存路徑與精度修正。


## Day 2：API 契約與資料可用性驗證

| 項目 | 紀錄 |
|---|---|
| 完成日期 | 2026-09-09 |
| 狀態 | 抽查、資料來源決策與契約完成；契約的程式約束在 Day 3 實作 |
| 實際投入時間 | 未記錄 |
| 資料契約 | [data-contract.md](data-contract.md) |
| 詳細證據 | [day02-audit.json](evidence/day02-audit.json) |

### 實際執行與結果

本人先執行抽查指令；檢查檔案時找到 202301 明細／World 與 202412 明細共 3 組。助理補抓缺少的 202412 World；首次因沙箱連線限制失敗，允許連外後成功。沒有修改應用程式。

| 月份 | 明細／World 筆數 | 兩者各自金額合計 | 差額 |
|---|---|---:|---:|
| 202301 | 67／1 | 2,799,575,181 | 0 |
| 202412 | 67／1 | 4,054,690,213 | 0 |

4 組資料的 checksum、Manifest 筆數／金額、固定查詢欄位及 grain 均通過。分類全部為 H6（HS2022），金額均為正值，沒有重複 grain。

### 資料限制與決策

- 202301 明細重量有效 36／67 筆（53.73%），202412 為 53／67 筆（79.10%）；其餘為 NULL，沒有 0 或負重量。World 的重量皆為 NULL。
- 交易檔案的 partnerISO 與 partnerDesc 全部缺值。官方夥伴參考表能找到所有代碼，後續建立維度補名稱及可用 ISO。
- 特殊代碼 490 的官方名稱為 Other Asia, nes，約占兩月份 World 的 22.54%／28.40%。保留原碼與金額；映射及正式 HHI 待 Day 8～10，不自行改名或排除。
- 4 次指定 `/H6` endpoint 的探測均為 HTTP 500；不宣稱該路徑已可用，也不推論永久不支援。
- 選擇沿用 `/HS` Preview，在 Day 3 加上只接受回應 H6 的驗證；此為資料接受限制，不是 API 端強制指定版本。
- 保留 202301～202412 目標期間，不切換正式 API。其他 22 個月仍待 Day 11 驗證。
- 本次核對的是已儲存檔案，原始 response count 未保留；精度與全期間完整性不能因此宣稱已驗證。

### 下一步

Day 3 補 H6 與固定維度驗證、版本／商品碼儲存路徑、Decimal 解析及重跑規則。此日誌記錄完成的是資料檢查與來源決策，不代表上述程式改動已完成。

## Day 3：將資料契約落實到程式

| 項目 | 紀錄 |
|---|---|
| 實作與 API smoke | 2026-09-10 |
| 文件收尾與離線複驗 | 2026-09-11 |
| 狀態 | 技術交付與驗收完成 |
| 實際投入時間 | 未記錄；未將助理執行時間當作本人學習工時 |
| 驗證證據 | [day03-verification.md](evidence/day03-verification.md)、[day03-smoke.json](evidence/day03-smoke.json) |

### 實作與設計理由

- 維持已成功使用的 `/HS`，在 service 逐筆拒絕非 H6；Day 2 的 `/H6` 探測失敗，不能將該路徑當成已可用設定。
- 補固定維度與金額驗證；明細允許 0，World 必須大於 0。重量／ISO 缺值及夥伴 490 仍保留。
- 從 JSON 解析開始使用 Decimal，避免先經 float 失真。Schema 2.0.0 將金額、重量、數量序列化為一致的十進位字串，合計亦保留精度。
- 本機與 S3 共用 v2 路徑及已有檔案的核對函式。路徑包含分類、商品、月份、查詢類型與 revision，避免互相覆蓋。
- 同內容重跑回傳 already_exists；同 revision 內容或 Manifest 不符即衝突。來源修訂由操作者指定新 revision，部分檔案吻合時只補缺檔。

### 驗證結果

先加入契約測試確認舊程式失敗，再完成實作。最終 134 個單元測試通過，ingestion 覆蓋率為 97.02%；mypy、Ruff 與格式檢查通過。Ruff 排除與專案無關的 `tests/TEST` 個人字典轉換檔案，保留原檔。

真實 API 擷取 202301／8542：明細 67 筆，World 1 筆，兩者金額皆為 2,799,575,181。首次各回傳 success，再跑各回傳 already_exists；checksum、筆數、合計、新格式與不改檔檢查通過，舊輸出保留。

### 限制與下一步

本次由助理完成技術工作，未測驗本人的理解程度。儲存採單 writer，不保證兩檔整體原子性；S3 使用假 client 測試。下一步依 Day 4 計畫重新建置 image，進行真實 AWS S3／Lambda 部署與驗收。

## Day 4：Console 部署 Lambda 與真實 S3 驗證

| 項目 | 紀錄 |
|---|---|
| 日期 | 2026-09-12 |
| 狀態 | Console 部署與功能驗收完成；總規格的 Terraform 與追溯證據仍待補 |
| 實際投入時間 | 未記錄 |
| 部署紀錄 | [day04-deployment-record.md](day04-deployment-record.md) |
| 本機複驗 | [day04-local-verification.json](evidence/day04-local-verification.json) |

### 實作與驗收

本人完成 AWS ECR、IAM、映像部署與 Lambda 設定，執行測試並在 S3 查看、下載輸出，最後確認全部檢查通過。依本人回報，兩類查詢、4 個輸出檔案、相同事件重跑不改寫、非法月份拒絕，以及資料核對均通過；逐次雲端原始輸出尚待附入紀錄。

助理實際複驗提供的 partner_detail 下載檔：202301／8542／H6／revision 1，共 67 筆，Decimal 金額合計 2,799,575,181。SHA-256、筆數與合計均符合 manifest；固定維度、無 World、無重複 grain、金額及 schema 契約檢查亦通過。Manifest 擷取時間為臺灣時間 20:20:07.713138，S3 截圖顯示兩檔修改時間為 20:20:08。本次未取得 World 下載檔或重新執行雲端測試。

### 今日理解

釐清 Docker 封裝、ECR 保存映像、Lambda 執行、IAM 授權、S3 保存資料與 CloudWatch 查紀錄的分工。確認 S3 路徑是 object key 前綴，NDJSON 每行一筆資料；查看檔案之外，還需透過 manifest、checksum、Decimal 合計與重跑版本確認結果。未回報具體部署故障。

### 待補與下一步

單日計劃使用 Console，但總規格 Day 4 另要求 Terraform、remote state 與 plan／apply 證據，故總規格尚不勾選完成。後續補 IaC 管理既有資源，以及資源名稱、image digest、invocation、S3 URI、Version ID、World 核對數值與預算資訊。本次 raw 資料保留供 Day 5 的 S3 → BigQuery 單月入倉使用。

### 2026-09-14：Terraform 接管補充

助理完成 bootstrap state bucket 的 6 個資源／設定，將 state 遷移至 S3，再匯入 application 的 11 個既有資源／設定。兩組使用不同 state key、固定版本與 lock file，套用後 plan 均回傳 `No changes`。本次實際启用 raw bucket 版本控制，Logs 設為保留 30 天；Lambda 映像與環境變數值不變。使用者實際學習工時未記錄。

驗證與剩餘差距見 [Terraform 接管驗證](evidence/aws/terraform-adoption.md)。OIDC bootstrap／部署、ECR lifecycle 與功能追溯等仍未全部完成，因此不將總規格 Day 4 勾選為全部通過。

## Day 5：BigQuery 單月載入與驗證

本人完成兩張 landing 表與 S3 Transfer，並提供查詢截圖、Transfer config／run IDs 與筆數／金額查詢 Job ID。明細 67 筆、World 1 筆，兩者金額各為 2,799,575,181；完整驗證截圖中金額缺失／轉型、月份商品分類與夥伴缺值檢查均為 0，World 正確分離。本人另確認明細 Transfer 重跑後仍為 67 筆。

已選定 S3 Data Transfer Service 作為本次載入方案，未實作 Python 替代 adapter。截圖確認兩張 raw 表存在；分區／clustering 已由後續截圖確認；非機密載入設定與來源 checksum 對應仍待補。實際學習工時未記錄。證據依本人提供，助理未獨立查詢 GCP 執行紀錄。

詳見 [Day 5 載入紀錄](day05-load-record.md)。提供的 Job ID 僅對應筆數／金額 SQL，不冒用為完整驗證或底層 load job ID。核心單月載入已通過，完整單日收尾仍待完成。

2026-09-15 補充：兩張 raw 表均已取消 60 天分區期限，更新後截圖確認「分區永不過期」，分區／clustering 與 0 筆空表狀態正確。原 DDL 遺漏明確取消到期設定，已修正並完成雲端確認，歷史月份入倉的此項阻礙已排除。


## Day 6：單月 raw 載入、Manifest gate 與交易處理

| 項目 | 紀錄 |
|---|---|
| 執行與補充日期 | 2026-09-15～2026-09-16 |
| 目前狀態 | 基本單月載入與手動 SQL 練習完成，可進入 Day 7；版本保護與完整驗收延後，M1 待驗收 |
| 實際學習工時 | 未提供，不以助理執行時間或計畫工時代填 |
| 載入紀錄 | [Day 6 載入與執行紀錄](day06-load-record.md) |
| 來源核對 | [S3 原始檔驗證](evidence/day06-source-verification.json) |

### 已完成的實作與確認

本人確認新增 SQL 均已執行且結果正確。明細 raw 為 67 筆、World raw 為 1 筆，金額各為 2,799,575,181，兩邊均有 success audit；此處以本人回報與載入紀錄為依據，不將本次文件核對描述為重新執行雲端驗收。

本人手動補入明細的完整 S3 路徑、真實 checksum、manifest 擷取時間，並補上 gate 異常中斷、交易內筆數／金額／重複檢查、回滾後 failed audit。World 的真實 checksum 已同步至本機驗證 SQL 與載入紀錄。

助理於 2026-09-15 實際下載明細及 World 的 S3 data／manifest，核對原始 bytes SHA-256、筆數、Decimal 合計、來源身分與 NUMERIC 可表示精度。明細重量 NULL 為 31 筆，World 為 1 筆；夥伴 490 保留原碼，明細金額為 630,972,428。這是來源檔案驗證，不等同於 raw 全欄位及 lineage 驗收。

### 整理的學習重點

- Manifest gate 必須在異常時中斷正式寫入；只列出查詢結果仍需要人工判讀。
- 將 raw 修改與 success audit 放在同一交易；失敗時先回滾，再於交易外保存 failed。
- 筆數與金額相同不能證明每個夥伴及來源追蹤欄位都正確；完整驗收仍需逐欄比較。
- 已跑通單月流程可以銜接 dbt sources／staging；處理修訂與自動重跑還需要版本判斷。

以上為本次討論整理，未作本人理解程度測驗。

### 延後與待核對事項

1. 正式 MERGE 的同版略過、同版衝突與舊版整批攔截延後；在處理來源修訂、舊版重送或自動載入前補齊。
2. 無損精度檢查接入正式 SQL、固定維度 NULL／頻率檢查、完整快照／lineage 比對、job ID 與 attempt 區分，留待擴大新來源／多月份自動載入前完成。
3. World SQL 的擷取時間已由 `2026-09-15T07:48:00Z` 修正為來源 manifest 的 `2026-09-12T12:20:59.992916Z`；本次修改本機 SQL，未重新執行雲端寫入。
4. 已確認 [day06-verification.md](evidence/day06-verification.md) 存在，由原 SQL 檔改名，內含 World 寫入與測試 SQL；完整真實重跑結果、fixture 證據、job ID 與延後項目的整理仍待補齊。
5. 已依本人要求移除未完成的獨立正規化模板、SQL 產生器、雲端執行腳本及專用 job 工具，並移除相依測試。保留獨立 MERGE 腳本、唯讀來源核對工具與其測試；歷史 SQL 保存在 `docs/evidence/day06-original/`，僅供追溯，不是執行入口。先前測試結果不代表 BigQuery 整合已驗收。

### 工具清理驗證（2026-09-16）

移除未完成工具後，152 個測試通過，2 個真實 API 整合測試因未啟用 `--run-integration` 略過；Ruff 檢查、格式檢查、全專案 mypy 與 `git diff --check` 均通過。已確認沒有執行程式引用已刪除工具，且 `merge-raw.sql` 內容未變。歷史 SQL 備份保留；本次未執行雲端 SQL。

### 下一步

沿用目前已確認的 `202301／8542／H6` raw 快照，進入 Day 7 的 dbt 基礎、sources 與 staging。保留 Day 6 完整規格與待辦，M1 暫不標示完成。


## Day 7：dbt sources、staging 與月份日曆

| 項目 | 紀錄 |
|---|---|
| 證據日期 | 2026-09-16（dbt JSON UTC 日期） |
| 狀態 | 三個模型、十個資料測試及重複 grain 反例完成；文件已整理，尚未提交 Git |
| 實際學習工時 | 未提供，不以終端機起訖或計畫工時代填 |
| 驗收紀錄 | [Day 7 dbt 驗收](day07-dbt-record.md) |
| 查核證據 | [驗證摘要](evidence/day07-verification.md)、[唯讀 SQL](evidence/day07-verification.sql) |

### 實作與驗證

本人在 dbt-staging 分支的獨立 worktree 操作，建立 .venv-dbt，安裝 Python 3.14.6、dbt Core 1.12.5 與 BigQuery adapter 1.12.1，pip check 通過並保存依賴版本。設定 Google Cloud CLI、ADC、dev／fixture targets；以 trade_raw 為真實來源，trade_analytics_dev 為輸出，location 為 asia-northeast1。

建立兩個 staging views 與獨立的 dim_months table。十個測試涵蓋月份完整性、非空與唯一、兩類 grain、202301 存在性、固定契約與 raw 保真；清理後 dev build 為 3 個模型成功、10 個測試通過。兩張 staging 的 30 個欄位型別經 Console 核對；模型說明 parse 通過，docs generate 產生 catalog.json，另記 table_owner 警告。

202301 明細 67 筆、World 1 筆，金額各 2,799,575,181；保留 partner 490、重量 NULL 與 lineage。日曆涵蓋 24 個月，閏年月底正確，其餘 23 個月缺交易資料並保留 NULL。隔離 fixture 正常通過，注入重複明細後 grain 測試 FAIL 1，恢復後 PASS=13。

### 問題與處理

- 啟用虛擬環境前沒有 python 指令，改以 python3 建立環境；啟用後可使用 python。
- gcloud 起初找不到，完成 CLI 設定與 ADC 後連線成功；早期 NoneType.close 錯誤的確切根因未定位，不推斷為特定套件問題。
- 從子資料夾執行時，相對的 --project-dir dbt 指錯位置；統一從專案根目錄執行。
- 缺月查詢發現真實 raw 混入 Day 6 的 202302 隔離測試資料；依 lineage 確認後備份並精確移除，重新驗證通過。
- BigQuery 不允許交易內建立永久表；備份表改在交易外建立，備份與刪除留在同一交易並檢查影響筆數。

### 本次整理的理解

- source() 引用外部載入的 raw，ref() 引用 dbt 模型；source 宣告不負責搬移或建立 raw。
- staging 固定輸出欄位、日期範圍與依賴，保留來源值；已正規化的 raw 仍需要穩定介面與測試。
- 月份日曆獨立產生，才能顯示缺月；缺資料的 NULL 不等於零交易。
- 違規列測試回傳零列才通過，空表也可能通過，因此另加單月存在性檢查。
- 測試通過只代表已編寫規則通過；二月測試資料可符合欄位契約，仍需追查 lineage。
- fixture 隔離 raw 與模型輸出；dbt debug 成功不等於來源讀取、模型寫入或業務驗證均完成。

以上為本次討論整理，不代表已逐項測驗本人的理解程度。

### 限制與下一步

實際工時未提供。真實資料保真驗收限於 202301，其他 23 個月未回填；負面測試僅實測重複 grain。人工 Console job IDs 待補，Day 6 延後事項與 M1 仍依原紀錄。下一步檢查提交內容，再進入 Day 8 的國家／商品維度與事實表。

## Day 8：國家／商品維度與月度進口事實表

| 項目 | 紀錄 |
|---|---|
| 實作日期 | 2026-09-20 |
| 狀態 | 技術實作、真實 dev build／重跑及隔離反例完成；490 地圖與對帳角色仍待考證 |
| 實際學習工時 | 未提供，不以助理執行時間代填 |
| 設計紀錄 | [Day 8 模型紀錄](day08-modeling-record.md) |
| 驗收證據 | [驗證摘要](evidence/day08-verification.md)、[查核 SQL](evidence/day08-verification.sql) |

### 完成內容

助理在獨立工作目錄完成 69 列夥伴 seed、1 列 H6／8542 seed、dim_countries、dim_hs_codes、月度 fact 與映射 audit。官方 Comtrade／M49 快照、取得時間、SHA-256 與離線產生流程已保存。一般夥伴包含已核對的國家及地區，不作主權國家清單解讀。

真實 BigQuery dev build 與重跑各 PASS=70（7 個模型、2 個 seeds、61 個資料測試），seed 單獨測試 PASS=20。202301 明細保持 67 筆、金額 2,799,575,181、重量 NULL 31 筆；全部來源欄位與 lineage 保真，重建結果完全相同。型別維持 STRING／NUMERIC／INT64。dbt docs generate 成功，table_owner 警告與 catalog 均保存。

專用 day08 fixture 已驗證缺夥伴、重複維度鍵、相同商品的另一個 HS 版本、缺月份、缺商品及新增未審特殊碼。預期失敗確實由測試偵測；來源交易在缺維度時仍保留。恢復後完整 build PASS=70，fixture fact 回到 baseline，真實 raw 未被修改。

### 理解與待辦

- Grain 代表交易身分，run_id／revision 只負責追溯，不增加交易粒度。
- LEFT JOIN 仍可能因維度鍵重複而倍增，須先檢查唯一性，不能靠 DISTINCT 掩蓋。
- 官方名稱、單一夥伴分類、地圖映射、互斥對帳角色需要分別確認。
- 490 的特殊分類已確認，S19 不直接作地圖碼；金額 630,972,428 保留，audit 有地圖不可用及對帳未解兩項問題。
- World 與夥伴明細分開，避免總額與其組成重複加總。
- 真實驗收仍只涵蓋 202301。Day 9 分析須保留覆蓋不足狀態；Day 10 補對帳與發布門檻。

以上為助理實作與驗證紀錄，不代表使用者已逐項完成理解測驗。

## Day 9：分析指標、固定資料測試與真實核對

| 項目 | 紀錄 |
|---|---|
| 實作日期 | 2026-09-21（台北；證據使用 UTC） |
| 狀態 | 實作及驗收完成，分支 analytics-metrics |
| 實際學習工時 | 未提供 |
| 完整紀錄 | [Day 9 指標驗收](day09-metrics-record.md) |

完成金額、市占率、MoM、YoY、有效重量 USD/kg、World 分母 HHI 與國家覆蓋率；新增兩個 intermediate models 及 candidate mart。缺月以日曆 join 處理，未將前一筆／前十二筆直接視為前月／去年同月；無效分母與重量保留 NULL，附市占率及 HHI 狀態。

以 Day 8 提交 e2b135d 為前置，在獨立 trade_analytics_day09_dev 建置。10 個模型、2 個 seeds、71 項資料測試與 5 組固定資料測試全部成功，dbt PASS=88。固定案例涵蓋 HHI 手算 5,200、覆蓋不足與恰好 0.5% 邊界、缺月、零分母、跨年、夥伴及版本隔離、缺重量與未審國家。真實 67 筆資料另以 Python Decimal 核對，所有 fact 欄位及 lineage 保留。

202301 的 66 個實際國家／地區覆蓋率約 77.46%，490 仍保留為 special；內部 HHI 為 992.713039409，可顯示 HHI 為 NULL，狀態 insufficient_coverage。資料不足沒有被誤呈現為低集中度。真實資料仍僅一個月，有效 MoM／YoY 與重量值由合成資料驗證。

實作與驗證由 AI 協助完成，未測驗本人理解程度。Day 10 的對帳與正式發布 gate 尚未實作；本次不宣稱 M2 或 M1 已完成。證據保存於 docs/evidence/day09，後續可接續 Day 10。


## Day 10：單月對帳、品質 gate 與正式發布

| 項目 | 結果 |
|---|---|
| 完成日期 | 2026-09-23（Asia/Taipei） |
| 分支 | `quality-release` |
| 實作 | 固定批次、歷次 audit、PASS／WARN／FAIL、交易式發布與品質摘要 |
| 真實驗收 | 202301，67 列正式發布；明細／World 同為 2,799,575,181，差異 0 |
| dbt | 92 項成功：11 models、2 seeds、74 data tests、5 unit tests |
| Python | 173 passed、2 個既有即時 API tests skipped |
| 隔離驗證 | 36 個不同案例通過，另有 10 個交易複驗案例 |
| 個人學習工時 | 未提供；未代填 |
| 完整紀錄 | [操作與設計](day10-quality-publish-record.md)、[證據摘要](evidence/day10-verification.md) |

490 已依官方語意及非群組標記確認為對帳明細，仍保留 special、不提供單一國家地圖、不納入國家 HHI。查驗原檔時發現舊 World checksum 與來源時間不正確，先保存備份，再僅修正這兩欄；其他值與原檔相符。獨立 snapshot attestation 保存真實查詢 job ID，沒有改寫歷史載入 audit。

M2 的單月分析與發布技術驗收完成；不因此將 M1、既有 IaC／載入延後事項或 24 個月覆蓋標記完成。實作及驗證由 AI 協助，未測驗本人理解程度。下一步 Day 11 先回填 3 個月，再擴充至 24 個月。

## Day 11：分批回填、覆蓋率與來源修訂

| 項目 | 結果 |
|---|---|
| 完成日期 | 2026-09-24（Asia/Taipei） |
| 實作 | 兩類來源的串行擷取、來源驗證、交易式 raw 載入、審查新增夥伴碼、候選建置與品質發布 |
| 真實驗收 | 202301～202412 共 24 個月份，48 份來源；24 個月份品質 PASS 且正式發布 |
| 覆蓋與指標 | 正式表 1,560 列，與凍結候選表差異 0；MoM 1,265 列、YoY 641 列、有效單位價值 1,304 列 |
| 隔離驗證 | 同版冪等、同版衝突、交易回滾、新版刪列及舊版拒絕均通過 |
| 個人學習工時 | 未提供；未代填 |
| 完整紀錄 | [Day 11 回填紀錄](day11-backfill-record.md)、[24 個月覆蓋清單](evidence/day11/coverage.csv) |

先以 202301、202302、202401 試批，再擴充至 24 個月。202302 初次品質 FAIL 指向 18 個未收錄的夥伴代碼；利用既存的 Comtrade 與 UN M49 快照審查全部新增的 73 個代碼後，重建 142 列國家／地區 seed 並重新驗收，未放寬門檻。多月份作業採 S3 原檔驗證加 Python／BigQuery 交易式載入；Day 5 Transfer PoC 保留為歷史紀錄。

來源修訂的刪列及回滾以隔離 fixture 驗證；此次真實來源無 revision 2。國家覆蓋率 63.01%～82.92%，24 個月的 HHI 均因覆蓋不足而不顯示，不能把品質 PASS 解讀為 HHI 可用。Python 測試 194 passed、2 skipped；dbt 最終 build 88 項成功。實作及驗證由 AI 協助，未測驗本人理解程度；雲端帳單金額與實際學習工時未提供。下一步 Day 12 使用正式資料建立 Dashboard，Day 16 再驗證 Airflow backfill DAG。

## Day 12：Streamlit 查詢與基本分析畫面

| 項目 | 紀錄 |
|---|---|
| 實作日期 | 2026-09-24（Asia/Taipei） |
| 狀態 | 本機 Dashboard、真實 BigQuery 固定條件核對與 UI 驗收完成 |
| 分支 | `streamlit-dashboard-foundation` |
| 本人實際學習工時 | 未提供；未以助理執行時間代填 |
| 詳細紀錄 | [Day 12 Dashboard 驗收](day12-dashboard-record.md) |

助理建立 Streamlit 畫面與唯讀參數化 BigQuery 查詢。畫面提供日期、Partner、Top N 篩選、金額排名、月度趨勢及品質摘要；查詢有日期分區條件、處理量上限和 1 小時快取。World 金額每月只計一次，排名排除特殊代碼 490，最新品質嘗試與正式發布版本分開顯示。

真實資料驗證得到 24 個已發布月份、139 個可選國家／地區；固定夥伴 458 的 24 個月金額為 19,277,096,395 美元，與獨立 SQL 一致。Streamlit 實際篩選、空結果、逆序日期及模擬品質 FAIL／權限失敗均已驗證。Day 13 再完成 YoY、HHI／覆蓋說明、資料新鮮度與分析觀察；目前不宣稱 M3 已完成。此次技術工作由 AI 協助，不代表已測驗本人理解程度。

## Day 13：視覺化與指標解讀

| 項目 | 紀錄 |
|---|---|
| 實作日期 | 2026-09-24（Asia/Taipei） |
| 狀態 | 本機 Dashboard 擴充、真實資料核對與 UI 驗收完成；M3 技術條件達成 |
| 分支 | `trade-visual-insights` |
| 本人實際學習工時 | 未提供；未以助理執行時間代填 |
| 詳細紀錄 | [Day 13 展示與分析驗收](day13-dashboard-record.md) |

在 Day 12 基礎上補上來源國長條圖、YoY、逐月國家覆蓋／HHI 狀態、新鮮度、地圖及金額／YoY 散佈圖。World 與月份級指標每月只取一次，單一 Partner 的 YoY 使用同夥伴去年同月基期；多 Partner 不平均各列 YoY。地圖只用已確認國家／地區的 ISO3 映射，並在畫面記錄未映射資料。

獨立 SQL 核對 2023 年 World 36,062,821,301 美元、2024 年 40,386,451,682 美元，年變化約 +11.99%。馬來西亞 2024 年金額 9,598,343,899 美元，仍為來源國／地區第一；24 個月份國家覆蓋率介於 63.01%～82.92%，HHI 全部為 `insufficient_coverage`，不能解讀成 0。2024-12 有 66 筆國家／地區列具地圖碼，55 筆具有效金額／YoY；預設散佈圖只顯示排名 Top 10。真實 Streamlit 篩選與提示驗收無例外，詳情及限制見執行紀錄。

實作及驗證由 AI 協助，未測驗本人對三項觀察及指標口徑的理解。雲端實際帳單費用與個人學習工時未提供。Day 14 接續 Airflow monthly DAG。

## Day 14：Airflow monthly DAG 與單月安全重跑

| 項目 | 紀錄 |
|---|---|
| 實作日期 | 2026-09-30（Asia/Taipei） |
| 狀態 | Compose、AWS／GCP 容器身分、正式 monthly DAG 與已發布月份完整安全重跑通過；DAG 暫停 |
| 分支 | `feature/airflow-monthly-pipeline` |
| 本人實際學習工時 | 未提供；未以助理執行時間代填 |
| 詳細紀錄 | [Day 14 執行紀錄](day14-run-record.md) |

正式 DAG 先檢查最多 3 個完整月份，每次 run 只處理一個可用月份；兩種來源分開 ingest／load，通過來源查驗後才執行 dbt、品質 audit、gate 與 publish。XCom 只傳 metadata。Pool 為 1 slot，DAG 同時只允許一個 run，避免候選 Dataset 多 writer。

以真實 `202412` 和原發布 run ID 重跑，Airflow 11 個 task 全部成功，dbt 88 項成功，品質 PASS，發布為 `already_published`；正式表 67 筆與 `published_at` 均未變。月份邊界、`not_available`、來源配對錯誤、raw 錯誤與 FAIL gate 由隔離測試驗證。此次由 AI 協助完成實作與驗證，不代表已測驗本人理解程度；新月份首次發布、長期重試／告警與積欠月份自動處理仍待後續。

## Day 15：月度補期、有限重試與告警

| 項目 | 紀錄 |
|---|---|
| 實作日期 | 2026-09-30～2026-10-01（Asia/Taipei） |
| 狀態 | Airflow 多月串行、重試分類、Lambda 結構化日誌與 AWS 告警已部署；SNS email 訂閱與實際收件仍待完成 |
| 分支 | `feature/monthly-scheduling-alerts` |
| 本人實際學習工時 | 未提供；未以助理執行時間代填 |
| 詳細紀錄 | [Day 15 執行紀錄](day15-run-record.md)與[操作手冊](day15-operations-manual.md) |

Monthly DAG 在最多三期的窗口內依舊到新串行處理可用月份；來源未就緒保留每種類型與檢查時間。暫時性遠端錯誤以明確退出碼供 Airflow 額外重試，永久錯誤與品質 FAIL 不重試。真實唯讀檢查指出 202606、202607 可用，202608 尚未可用，但較早的 202501～202605 共 17 個月未發布；正式 DAG 因此保持暫停，避免跳過積欠直接發布較新月份。

已發布的 202412 用原 run ID 安全重跑成功，正式 67 筆與發布時間不變。Terraform 新增三個 CloudWatch filters、五個 Alarms、SNS topic／policy，並以不可變映像 digest 更新 Lambda；部署後 plan 無 drift。隔離真實 handler 失敗產生可解析的 JSON 日誌，Errors 與 151 秒 Duration 均觸發隔離 Alarm，Alarm history 顯示 SNS topic 動作成功；隔離雲端資源已清理。Topic 尚無 email 訂閱，不能宣稱實際通知已送達。技術實作與驗證由 AI 協助，尚未測驗本人理解，個人學習時間未記錄。

## Day 16：參數化回填、品質停損與載入復原

| 項目 | 紀錄 |
|---|---|
| 實作日期 | 2026-10-01（Asia/Taipei） |
| 狀態 | 三個月真實 backfill、安全重跑與載入回報遺失後復原通過；M4 技術條件達成 |
| 分支 | `feature/airflow-backfill-recovery` |
| 本人實際學習工時 | 未提供；未以助理執行時間代填 |
| 詳細紀錄 | [Day 16 執行紀錄](day16-run-record.md)、[操作手冊](day16-backfill-manual.md) |

新增無排程的 `trade_backfill_pipeline`，明確驗證起訖月份及三月上限，沿用單月 pipeline 步驟並與 monthly DAG 共用單 slot Pool。第一輪 `202501` 因 3 個未審夥伴代碼而品質 FAIL，正式發布保持空白，後兩月沒有開始；先從保存的 Comtrade／UN M49 快照審查三個月共 7 個代碼，重建國家 seed 後建立新品質嘗試，未放寬門檻。

`202501`～`202503` 三個月分別發布 67、62、61 筆，品質皆 PASS。另以 `202504` 的 `partner_detail` 做載入提交後失去成功回報的受控演練：Airflow 首次失敗、第二次回傳 `already_loaded`，raw 仍為 61 個不同 grain，品質 PASS 後正式發布。前三個月使用原 run ID 安全重跑，raw 筆數、正式 run ID 與 `published_at` 全部不變。技術工作由 AI 協助，尚未測驗本人理解；雲端實際帳單費用及個人學習工時未提供。正式 monthly DAG 仍暫停，Day 15 的 SNS email 實收仍待完成。


## Day 17：CI／CD、OIDC 與 Terraform 部署

| 項目 | 紀錄 |
|---|---|
| 實作日期 | 2026-10-01（Asia/Taipei） |
| 狀態 | 真實 GitHub CI、OIDC → ECR → Terraform → Lambda 部署、digest／無 drift 查核與隔離 dbt 雲端測試通過 |
| 分支 | `feature/ci-oidc-deployment` |
| 本人實際學習工時 | 未提供；未以助理執行時間代填 |
| 詳細紀錄 | [Day 17 執行紀錄](day17-run-record.md)、[操作手冊](day17-cicd-manual.md) |

新增離線 CI 與共用部署前檢查，251 項 Python unit tests 全部通過，整體 coverage 91.53％、ingestion 97.03％、raw loader 96.52％。真實 Airflow 3.3.2 匯入兩條各 31-task pipeline，Docker handler smoke 與兩組 Terraform 檢查通過。首次 GitHub run 揭露 UI 意外依賴 ADC、Linux provider checksum 缺口與 SDK timetable 型別差異；修正前部署被阻擋，沒有以本機綠燈代替真實 CI。

Bootstrap 新增 GitHub provider 與受限部署角色，trust 精確匹配含 immutable IDs 的 repository subject 與指定 branch。真實 OIDC 身分完成 ECR 推送與 image-only saved-plan apply，Lambda resolved digest 相符，部署後與獨立本機 plan 均無 drift。處理 provider refresh 唯讀權限、巢狀 unknown 值誤判與 PyPI 下載逾時；未放寬 trust 或改用 administrator 部署。驗收用自動部署開關已關閉，main 的部署授權須於 PR 合併後另外同步設定。

手動 ADC 入口在新建隔離 Dataset 執行 88 項 dbt build 結果，包含 5 項 unit tests 與 71 項 data tests；raw sources 唯讀，不發布正式資料。Artifacts 與 query job／處理量已保存，測試表 24 小時到期。技術工作由 AI 協助，尚未測驗本人理解；雲端帳單金額與個人學習工時未提供。正式 monthly DAG 仍暫停，SNS email 實收與 Cloud Run／乾淨重建／真實回復演練仍留在後續階段。


## Day 18：Cloud Run 展示與正常路徑 E2E

- 實作／驗收日期：2026-10-01～2026-10-02（Asia/Taipei）。
- 本人實際投入時間：未提供，不以 AI 操作時間代填。
- 完成：專用非 root Dashboard image、Cloud Run digest 部署、唯讀 runtime、日期範圍設定、線上金額／YoY／覆蓋率核對、202504 正常路徑安全重跑與操作手冊。
- 真實結果：線上年度 World USD 40,386,451,682、Malaysia USD 9,598,343,899；202504 World USD 3,114,414,147。重跑保持 raw grain、正式 run ID 與發布時間不變。
- 費用決策：原始預算 USD 10／月；使用者另指定 TWD 250／月通知門檻，已配置專案限定預算。通知不等於費用硬上限，未驗證通知實收；實際帳單未提供。
- 程式驗證：255 tests passed、coverage 91.66％、Ruff／mypy、容器 smoke 與真實 SQL／UI 檢查通過；未執行遠端 GitHub CI。
- 學習邊界：由 AI 協助實作，本人對 runtime／部署身分、查詢限制與快取的理解尚未測驗。
- 後續：Day 19 乾淨重建／回復／SNS 故障實收，monthly DAG 繼續暫停，剩餘積欠另追蹤。
- 詳細證據：[Day 18 執行紀錄](day18-run-record.md)。

## Day 19：乾淨重建、SNS 實收與故障復原

- 驗收日期：2026-10-02（Asia/Taipei）；分支 `feature/rebuild-alert-recovery`。
- 乾淨來源安裝／255 項 unit tests 通過，coverage 91.66％；Lambda、Dashboard 與 Airflow／dbt image 重建及真實 GitHub CI 通過。
- 以獨立 state／新命名重建 21 個 AWS application 資源，後續無 drift；bootstrap state bucket／帳號 OIDC provider 共用，未宣稱全部帳號資源重建。
- 補齊 SNS 訂閱確認；真實隔離 handler 失敗觸發分類與 Errors Alarm，本人回報兩封告警於台北時間 01:34 收到。同 run ID 修正後成功擷取 61 筆，再重跑為 `already_exists`，checksum 相同。
- 真實 BigQuery 隔離合成品質驗證共 10 案例通過；正式 202504 完整 Airflow 安全重跑成功，raw grain／金額、正式 run ID／發布時間不變。兩類案例分開記錄，不冒稱同一次事故。
- OIDC 精確 trust／部署 ref 改為 `main`，新增指定 SNS topic 的 subscription refresh 唯讀權限；首次部署因缺該權限失敗，修正後真實 OIDC 部署與兩組獨立無 drift 查核成功。
- 隔離 Lambda 舊 digest 回復通過。Cloud Run 直接回切舊 revision 發生 429，暫時 scaling 調整未解決；重新部署舊 digest 至新 revision 並明確切流量後恢復，原 Live URL 的單月數值核對成功，min 0／max 1 已還原。
- 隔離 AWS 21 個資源、BigQuery 兩個 fixture Dataset 已清理；GCP 無流量 revisions／映像與隔離空 remote state 保留。Monthly DAG 仍暫停，積欠另處理。
- 本人實際投入與帳單未提供，理解測驗未進行；由 AI 協助完成技術驗收，M5 留待 Day 20。
- 詳細證據：[Day 19 執行紀錄](day19-run-record.md)、[操作手冊](day19-recovery-manual.md)。
