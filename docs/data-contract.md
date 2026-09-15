# UN Comtrade 資料契約

| 項目 | 決策 |
|---|---|
| 確認日期 | 2026-09-09 |
| 契約狀態 | Day 2 抽查與來源決策完成；Day 3 約束已實作，2026-09-11 複驗完成 |
| 來源 | 公開 Preview API，保留現有 `/public/v1/preview/C/M/HS` endpoint |
| 接受的分類版本 | `H6`，即 HS2022；不接受其他分類混入 |
| 固定版本方式 | 回應驗證層已拒絕非 H6；不是由 API 端強制選定版本 |
| Reporter／Flow／Frequency | `842`／`M`／`M` |
| partner2Code／customsCode／motCode | `0`／`C00`／`0` |
| 商品碼 | `8542` |
| 目標期間 | `202301～202412`，連續 24 個月 |
| 本日實測 | `202301`、`202412`，各含 partner_detail 與 world_total |
| 詳細證據 | [day02-audit.json](evidence/day02-audit.json)，含來源路徑、時間、checksum、逐項檢查與特殊代碼 |

官方參考檔將 H6 定義為 HS2022。[UN Comtrade H6](https://comtradeapi.un.org/files/v1/app/reference/H6.json)

## 1. 抽查結果

| 月份 | 類型 | 筆數 | 分類 | 金額合計 | checksum／Manifest／固定欄位／grain |
|---|---|---:|---|---:|---|
| 202301 | partner_detail | 67 | H6 | 2,799,575,181 | 全部通過 |
| 202301 | world_total | 1 | H6 | 2,799,575,181 | 全部通過 |
| 202412 | partner_detail | 67 | H6 | 4,054,690,213 | 全部通過 |
| 202412 | world_total | 1 | H6 | 4,054,690,213 | 全部通過 |

開始檢查時只有前 3 組檔案，缺少 202412 World。經允許連外後使用原 CLI 補抓成功，未覆寫其他 3 組資料。固定欄位包含 period、reporterCode、flowCode、freqCode、cmdCode、classificationCode、partner2Code、customsCode、motCode。

所有樣本 primaryValue 均大於 0，無 NULL、0 或負值。明細無 World，World 各只有一筆；沒有重複 grain。重新計算檔案 SHA-256、筆數與十進位金額合計，均與 Manifest 一致。

### 初步對帳

| 月份 | 非 World 明細合計 | World | 差額 | 差異率 |
|---|---:|---:|---:|---:|
| 202301 | 2,799,575,181 | 2,799,575,181 | 0 | 0% |
| 202412 | 4,054,690,213 | 4,054,690,213 | 0 | 0% |

這是「目前保留的非 World 明細」與 World 的樣本核對，包含特殊代碼 490；不是已完成全部國家分類的正式對帳模型，也不代表全部 24 個月完整。

## 2. 重量與國家資訊

| 月份／類型 | 重量 NULL | 重量 > 0 | 有效重量筆數比例 | ISO／名稱缺值 |
|---|---:|---:|---:|---|
| 202301 明細 | 31 | 36 | 53.73% | 67／67 |
| 202412 明細 | 14 | 53 | 79.10% | 67／67 |
| 202301 World | 1 | 0 | 0% | 1／1 |
| 202412 World | 1 | 0 | 0% | 1／1 |

重量沒有 0 或負值。比例以資料筆數計算，不是金額覆蓋率。

- 金額與 World 分母可用，可繼續入倉及市占率實作。
- 單位價值僅限重量 > 0 的資料；顯示有效資料比例，不補 0。
- 名稱與 ISO 不由交易回應直接取得，後續使用官方夥伴代碼表建立維度。
- 官方 partnerAreas 參考表能找到本次所有夥伴代碼，但「找到代碼」不代表都能直接對應地圖。

### 特殊代碼 490 必須保留

官方參考表將 490 標示為 `Other Asia, nes`，其 ISO 欄位不是一般三字母國家代碼。本次將它標記為需釐清的特殊區域，不能直接當成一般國家，也不能自行改名或丟棄。[官方 partnerAreas](https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json)

| 月份 | 490 金額 | 約占 World |
|---|---:|---:|
| 202301 | 630,972,428 | 22.54% |
| 202412 | 1,151,535,965 | 28.40% |

因此正式 HHI／地圖尚不能直接發布。Day 8 必須釐清代碼語意及映射來源，保留原始代碼；若依契約只計可確認的一般國家而排除 490，需顯示覆蓋不足，依 spec 將公開 HHI 標成資料不足，不能把偏低結果當成完整市場集中度。

## 3. Endpoint 與分類選擇

1. 沿用現有可用的 `/HS` Preview endpoint，接受資料版本選定為 H6。
2. 本日另以 `/public/v1/preview/C/M/H6` 探測同樣 4 組查詢，均回傳 HTTP 500。回應保存於 `data/day02-h6-probe/`，不能假設該路徑可用；500 也不足以證明永久不支援。
3. 不將 `/H6` 寫成已驗證的正式設定；Day 3 採「抓取後強制檢查 classificationCode == H6」策略，遇到其他版本立即拒絕入倉。
4. Day 3 已加入 H6 版本拒絕規則。之後若某月份非 H6，該月份視為無可接受資料，評估正式來源或調整期間，不能混用或自行轉換標籤。
5. 本次不因名稱缺值或部分重量缺值切換正式 API；現有來源足以繼續核心金額分析的實作。正式 API 權限與欄位優勢尚未實測。

## 4. 完整性與精度限制

- 官方 Preview 說明為最多 500 筆；目前 client 在原始 response count 達 500 時拒絕寫入。[官方說明](https://uncomtrade.org/docs/what-is-data-preview/)
- 現有輸出是篩選、模型處理與序列化後的資料，沒有保存原始 response count／envelope；Manifest 筆數不能反推原始 count。
- 本次金額對帳與筆數檢查支持樣本一致性，不是全期間完整性的證明。其他 22 個月在 Day 11 驗證。
- Day 2 舊檔重新以 Decimal 讀取，不能追回先經 float 解析可能失去的精度。Day 3 新流程已從 JSON 解析使用 Decimal，並以原始 JSON 小數 fixture 驗證精度與合計；舊檔未覆寫。

## 5. 接受與錯誤規則

| 規則 | 接受條件 | 現有程式狀態 |
|---|---|---|
| 查詢範圍 | 月份、Reporter、Flow、商品符合請求 | 已有核心驗證 |
| 分類 | 一批及跨批都只能接受 H6 | 已實作逐筆拒絕非 H6；Query 只允許 H6 |
| 其他固定維度 | freqCode、partner2Code、customsCode、motCode 符合契約 | 已實作拒絕分支與測試 |
| Grain | 固定其他維度與版本下，period × partnerCode × cmdCode 唯一 | 已有檢查 |
| World | partnerCode=0、恰一筆且 primaryValue > 0 | 已實作與測試 |
| 金額 | primaryValue 不得 NULL、非有限值或負值；明細允許 0 | 已實作與測試 |
| 重量 | NULL 保留，僅 > 0 計算單位價值 | 後續模型處理 |
| 特殊夥伴 | 保存 490 等原碼及金額，維度註明類別與映射依據 | Day 8 建模，不直接套一般 ISO |
| 截斷 | 達 Preview 上限拒絕寫入 | 已有 count 檢查 |

## 6. Day 3 已完成的儲存契約

- Query 保存 `expected_hs_version=H6`；維持 `/HS` endpoint，不把接受條件當作 API 參數。
- 路徑為 `<root-or-prefix>/v2/hs_version=H6/cmd_code=8542/period=202301/query_type=partner_detail/revision=1/`；舊資料保留。
- Schema version 為 `2.0.0`。`qty`、`altQty`、`netWgt`、`grossWgt`、`cifvalue`、`fobvalue`、`primaryValue` 使用 Decimal，輸出為無指數及多餘尾零的十進位字串，NULL 保留。額外的小數欄位亦依相同方式序列化。
- Manifest 的 `primary_value_sum` 為精確加總後的十進位字串，另保存月份、商品、查詢類型、H6 與 revision。後續 BigQuery 正規化需轉為 NUMERIC 並檢查範圍。
- CLI 與 Lambda 支援正整數 revision，預設 1。相同內容回傳 `already_exists` 並保留原檔；checksum 或 Manifest 契約欄位不符則 conflict，來源修訂須明確指定新 revision。
- 本機與 S3 共用路徑及核對函式。僅缺一檔且現有檔案吻合時補缺檔；採單 writer，不宣稱兩檔是整體原子交易。
- HHI 與 490 的業務映射留在 Day 8～10 處理，不在 ingestion 靜默刪除。

驗收詳見 [Day 3 驗證紀錄](evidence/day03-verification.md) 與 [真實 API smoke](evidence/day03-smoke.json)。S3 本日使用假 client 測試；真實 AWS 驗收留待 Day 4。
