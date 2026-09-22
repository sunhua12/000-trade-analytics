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
