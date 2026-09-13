# Day 2：確認 API 資料契約、HS 分類與資料可用性

| 項目 | 內容 |
|---|---|
| 對應計畫 | [20 天實作規格](trade-analytics-spec.md) 的 Day 2 |
| 前置成果 | Day 1 已完成，詳見 [學習日誌](learning-log.md) |
| 預計投入 | 約 3～4 小時 |
| 核心目標 | 確認抓到的是什麼資料、有哪些限制，以及能否支援後續分析 |
| 今日交付物 | 起訖月份抽查紀錄、資料契約、來源選擇與待處理事項 |

## 1. 今天先做什麼？

**先用現有程式抓取 `202301` 與 `202412` 的資料，對照回應欄位與 Manifest。**每個月份各抓 Partner Detail 與 World Total，共 4 次 CLI 執行。

Day 1 關心「程式如何跑」，Day 2 關心「跑出來的資料能不能用」。今天以讀資料、核對與記錄決策為主，無須先理解全部測試，也不需要先重構程式、部署 AWS 或建立 BigQuery。

本計畫已於 2026-09-09 完成抽查與來源決策。實際結果見 [資料契約](data-contract.md) 與 [驗證證據](evidence/day02-audit.json)；下方指令及範本保留供重做。

## 2. 認識今天需要的概念

**預計時間：30 分鐘。**

| 概念 | 白話說明 | 今天要回答的問題 |
|---|---|---|
| 資料契約 | 對輸入、欄位、粒度與錯誤處理的約定 | 什麼資料可以繼續進入分析？ |
| HS 商品碼 | 商品分類代碼 | 本專案先固定的 `8542`，與分類版本是不同欄位嗎？ |
| HS 分類版本 | 商品分類採用哪一版規則 | 不同月份的 `classificationCode` 是否一致？ |
| Grain／資料粒度 | 一筆資料代表什麼 | 同月份、夥伴國與商品是否出現重複？ |
| World Total | 同條件下的世界總計 | 是否只有 `partnerCode=0` 的一筆資料？ |
| 完整性 | 是否缺月份、欄位或被截斷 | 能成功回傳，是否就能證明資料完整？ |

目前 endpoint 結尾為 `/C/M/HS`。官方的 HS 參考檔將 `HS` 標示為 `Combined HS`，不能只憑網址中的 `HS` 就宣稱固定了某個分類版本；必須核對實際回應與選定 endpoint 的版本語意。[UN Comtrade HS 參考檔](https://comtradeapi.un.org/files/v1/app/reference/HS.json)

今日只需閱讀三個位置：

- [queries.py](../src/trade_analytics/ingestion/queries.py)：`to_params()`，確認真正送出的參數。
- [schemas.py](../src/trade_analytics/ingestion/schemas.py)：找出下方欄位，不必逐行閱讀全部欄位。
- [client.py](../src/trade_analytics/ingestion/client.py)：確認 endpoint 與現有截斷檢查。

## 3. 抽查展示期間的起訖月份

**預計時間：45～60 分鐘。**

### 3.1 執行指令

切換至專案根目錄：

```bash
cd /Users/syunhua/Documents/10_Projects/000-trade-analytics
```

依序執行以下 4 個指令，確認前一個結果後再執行下一個。輸出另放在 `data/day02-preview`，保留 Day 1 的資料。

```bash
.venv/bin/python ingest.py --period 202301 --cmd-code 8542 --query-type partner_detail --output-dir data/day02-preview
```

```bash
.venv/bin/python ingest.py --period 202301 --cmd-code 8542 --query-type world_total --output-dir data/day02-preview
```

```bash
.venv/bin/python ingest.py --period 202412 --cmd-code 8542 --query-type partner_detail --output-dir data/day02-preview
```

```bash
.venv/bin/python ingest.py --period 202412 --cmd-code 8542 --query-type world_total --output-dir data/day02-preview
```

這些命令會連接真實 API。本機 storage 會替換相同位置的檔案；若要保留多次抽查結果，第二次執行時改用新目錄，例如 `data/day02-preview-rerun`。

若發生限流，先閱讀錯誤並等待，不反覆快速重送。若指令失敗，記錄錯誤摘要及時間，不把先前留下的檔案當成本次成功輸出。

### 3.2 打開輸出

每個查詢都應有 `data.ndjson` 與 `manifest.json`，例如：

```text
data/day02-preview/
├── period=202301/
│   ├── query_type=partner_detail/
│   │   ├── data.ndjson
│   │   └── manifest.json
│   └── query_type=world_total/
│       ├── data.ndjson
│       └── manifest.json
└── period=202412/
    ├── query_type=partner_detail/
    │   ├── data.ndjson
    │   └── manifest.json
    └── query_type=world_total/
        ├── data.ndjson
        └── manifest.json
```

### 3.3 填寫摘要表

| 月份 | 查詢類型 | 執行成功？ | row_count | hs_version | primary_value_sum | 檔案位置／錯誤摘要 |
|---|---|---|---|---|---|---|
| 202301 | partner_detail | 是 | 67 | H6 | 2,799,575,181 | data/day02-preview；詳見證據 |
| 202301 | world_total | 是 | 1 | H6 | 2,799,575,181 | data/day02-preview；詳見證據 |
| 202412 | partner_detail | 是 | 67 | H6 | 4,054,690,213 | data/day02-preview；詳見證據 |
| 202412 | world_total | 是，助理補抓 | 1 | H6 | 4,054,690,213 | data/day02-preview；詳見證據 |

每次抽查另記錄執行時間、endpoint 與 checksum；不要把 API Key 放進紀錄。

注意：Manifest 的 `row_count` 是篩選後資料筆數。Partner Detail 可能已移除 World，不能將它直接視為原始 API response 的 `count`。目前 CLI 也沒有保存原始 response envelope；需要該項證據時應另記錄，不能反推原始 count。

## 4. 檢查欄位與資料契約

**預計時間：45～60 分鐘。**

### 4.1 核心欄位

| 欄位 | 預期／檢查方式 | 結果不符時 |
|---|---|---|
| period | 等於請求月份 | 停止接受這份資料 |
| reporterCode | `842` | 停止接受這份資料 |
| flowCode | `M` | 停止接受這份資料 |
| cmdCode | `8542` | 停止接受這份資料 |
| classificationCode | 同一份資料只有一個版本，4 份結果互相比對 | 不混用；調查版本選擇方式 |
| partnerCode | 明細排除 `0`；World 恰一筆且為 `0` | 調查查詢與篩選規則 |
| primaryValue | 記錄缺值、負值與 0 的筆數 | 必要金額缺失需釐清，不能補成 0 |
| netWgt | 記錄 NULL、0、負值與大於 0 的筆數 | 只有大於 0 才可計算 USD／kg |
| partnerISO／partnerDesc | 記錄缺值情形 | 後續可用國家維度補對應，不代表金額資料必須丟棄 |

也要確認 `partner2Code=0`、`customsCode=C00`、`motCode=0`。目前 service 已驗證部分核心欄位，尚未代表表中所有語意條件都已由程式保證。

同一版本、固定 Reporter／Flow／其他維度下，檢查 `period × partnerCode × cmdCode` 是否唯一。若版本不一致，先處理版本問題，不能直接合併去重。

### 4.2 資料能支持哪些畫面？

| 分析功能 | 最低資料條件 | 今日判斷 |
|---|---|---|
| 來源國進口金額 | 夥伴代碼與金額有效 | 可用／待釐清 |
| 市占率 | 同月份、商品與版本的 World 金額 > 0 | 可用／待釐清 |
| HHI | 能辨識實際國家，且有足夠覆蓋率 | 待國家維度及對帳驗證 |
| 地圖 | ISO 可用或可由代碼補對應 | 可用／需補維度 |
| 單位價值與重量散佈圖 | 金額有效且 netWgt > 0 | 可用／部分可用／無有效重量 |
| YoY | 去年同月資料存在且可比較 | 起訖抽查無法證明，待逐月驗證 |

重量缺失不必立刻改整套架構。先記錄有效重量筆數占明細筆數的比例，再決定保留條件式圖表，或是否值得更換來源。不要將 NULL 當成 0，也不要把 USD／kg 稱為晶片單顆價格。

### 4.3 完整性與初步金額比較

- 現有程式以原始 response `count >= 500` 拒絕疑似截斷結果。這是目前實作的警戒值；實際 endpoint 限制仍需查核，不把它視為所有 API 方案的共同上限。
- 筆數低於警戒值只能表示未觸發該檢查，不能單獨證明沒有缺漏。
- 比較同月 Partner Detail 與 World 的金額合計，先記錄差額及差異率。
- 若特殊代碼或群組尚未分類，不把「全部非 World 加總」直接視為正式對帳或 HHI 的國家集合。
- 起訖月份成功不代表中間 22 個月全部可用；完整 24 個月覆蓋驗證安排在 Day 11。

金額檢查可先使用 Manifest 的合計，但現有資料模型仍讓金額經過 float；它不構成來源精度完全保留的證據。Decimal 解析與相應測試安排在 Day 3。

## 5. 決定資料來源與分類版本

**預計時間：30～45 分鐘。**

今天要形成「有證據的選擇」，不必今天就完成來源切換程式。

| 觀察 | 決策方向 |
|---|---|
| 兩個月份皆成功，版本一致，核心金額可用 | Preview 可作候選來源；仍需確認固定版本的查詢方式與完整期數 |
| 兩個月份版本不同 | 查核該 endpoint 如何選擇明確版本；未確認前不混合分析 |
| 達截斷限制或核心欄位無法取得 | 評估正式 API 的實際權限、限制與所需欄位，記錄切換需求 |
| 只有重量／名稱缺值 | 先評估條件式功能或國家維度補值，不自動判定必須切換 |
| 預設期間無法取得可比較資料 | 提出可驗證的替代期間，說明為何調整；仍以連續 24 個月為目標 |
| 文件或權限不足，無法確認 | 標記來源決策受阻，保留具體待查事項，不填入猜測的版本 |

目前 CLI 沒有 `--hs-version` 參數，也不能只靠 CLI 選擇正式 endpoint。若需要指定版本或認證，先記錄可用方式及驗證證據，再交由 Day 3 實作；不要使用尚未存在的 CLI 參數。

「觀察到回應版本一致」與「查詢已強制固定版本」是兩件事，必須在契約中分開記錄。正式 API 也不自動保證重量、完整性或可比較性，仍要實測。

## 6. 寫出最小資料契約

**預計時間：30 分鐘，含學習日誌。**

建立 `docs/data-contract.md`，使用以下範本填入本日實測結果。若檔案已存在，更新原文件，保留已有決策。

```markdown
# UN Comtrade 資料契約

## 範圍與來源

- 確認日期：
- 來源模式：Preview／正式 API／待決定
- Endpoint：
- Reporter／Flow／Frequency：842／M／M
- partner2Code／customsCode／motCode：0／C00／0
- 商品碼：8542
- 目標期間：202301～202412；若調整，註明理由
- 實際抽查期間與證據位置：
- 觀察到的 classificationCode：
- 選定分類版本與官方定義：
- 如何強制指定版本：已驗證方式／待驗證

## 輸入與資料規則

- 每次一個 period 與 query_type。
- Partner Detail 排除 World；特殊代碼保留待分類。
- World Total 恰一筆，partnerCode=0。
- 同一分類版本與固定其他維度下，grain 為 period × partnerCode × cmdCode。
- 必要金額不可用時，不宣稱該批可供分析。
- 重量缺值不補 0，netWgt > 0 才可計算單位價值。
- 同批／跨期分類不一致時，不直接合併。
- 目前實作的截斷警戒：500；endpoint 實際限制與查核證據：

## 抽查結果與限制

- 4 次 CLI 的筆數、版本、金額、時間與 checksum：
- 重量／ISO 缺值情形：
- 初步明細與 World 金額差異：
- 已由程式驗證的規則：
- 仍需補實作的規則：
- 尚未驗證的月份與資料完整性：

## 決策與下一步

- 是否沿用 Preview，以及理由：
- 是否調整期間，以及理由：
- Day 3 實作項目：
- 未解問題與解除方式：
```

最後在 [learning-log.md](learning-log.md) 新增 Day 2，記錄實際工時、抽查結果、來源決策與資料契約位置。今日計畫完成前，不預先標記成功。

## 7. 今天不必做的事

- 不用重新閱讀全部 68 個單元測試。
- 不用回填全部 24 個月；先取得起訖月份的證據。
- 不用建立 dbt、Airflow 或雲端資源。
- 不用為了 HS 6 碼、關稅或進階告警增加設計。
- 不用今天修好全部程式缺口；把可重現的問題交給 Day 3。

## 8. Day 2 完成檢查表

- [x] 起訖月份的兩類查詢已執行，結果或失敗原因均有紀錄。
- [x] 核對月份、Reporter、Flow、商品碼、World 與明細的條件。
- [x] 核對 4 份結果的分類版本，並區分「觀察一致」與「強制指定」。
- [x] 記錄金額、重量及 ISO 的可用性，知道哪些分析需加限制。
- [x] 知道現有截斷檢查的範圍，沒有把成功回應當成完整性證明。
- [x] 明確決定來源及目標期間；若受阻，列出尚缺的證據。
- [x] 完成 `docs/data-contract.md` 與 Day 2 日誌。
- [x] 列出 Day 3 的版本、儲存路徑與精度修正項目。

**完成標準：能說清楚這份資料的來源、口徑、限制及下一步修正，並有實際抽查證據。**若來源或分類版本仍無法決定，記錄為部分完成，不宣稱資料契約已確認。
