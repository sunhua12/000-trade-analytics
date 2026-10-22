// Local UI copy only. Source names, ISO codes, numeric values and CSV schema stay unchanged.
const copy = {
'全球來源進口總額':'Imports from all global sources','所選來源國進口額':'Imports from selected sources',
'進口市場':'Importing market','進口來源國／地區':'Import source country / area',
'兩個金額為什麼不同？':'Why do these totals differ?',
'「全球來源」是目前進口市場向全球進口的總額，不是全球所有市場的總和。選擇來源國只會改變「所選來源國進口額」。未選來源國時，會加總全部已確認國家；特殊來源代碼未納入國家合計，因此仍可能小於全球來源總額。百分比表示所選來源占全球來源進口總額的比例。':'Global sources means imports into the selected market from the world, not imports summed across all markets. Source filters change only the selected-source total. With no sources selected, all identified countries are included. Special source codes are excluded from country totals, so the sum may still be below the World total. The percentage is the selected-source total divided by the World total.',

'半導體進口分析':'SEMICONDUCTOR IMPORT ANALYSIS',
'研究摘要':'AT A GLANCE / SUMMARY',
'01 / 進口趨勢':'01 / THE BIG PICTURE',
'02 / 來源國排行':'02 / ORIGIN RANKING',
'03 / 地理分布':'03 / TRADE GEOGRAPHY',
'04 / 跨年度比較':'04 / ACROSS THE YEARS',
'05 / 資料探索':'05 / EXPLORE THE DATA',
'06 / 資料方法':'06 / BEHIND THE NUMBERS',
'全球進口總額':'World total','世界地圖':'WORLD MAP','年增率':'YoY','月增率':'MoM',
'半導體進口數據觀察':'Semiconductor Import Insights',
'月度國家明細':'Monthly Country Data','資料來源與指標定義':'Sources & Definitions',
'從進口資料出發，探索積體電路貿易的規模、來源與時間變化。':'Explore the scale, origins and trends of integrated circuit trade through import data.',
'貿易總覽':'Overview','資料明細':'Data Explorer','資料方法':'Methodology','主要導覽':'Main navigation','介面語言':'Interface language','跳至主要內容':'Skip to main content',
'月度進口 · USD':'Monthly imports · USD','研究範圍':'Research scope','載入中':'Loading','調整篩選':'Edit filters',
'報告市場':'Reporting market','商品複選':'Products','跨市場比較：僅使用共同可用月份':'Cross-market comparison: common available months only',
'分析期間':'Period','起始月份':'Start month','結束月份':'End month','來源國／地區':'Source country / area','來源國或代碼…':'Country or code…',
'搜尋名稱或代碼…':'Search name or code…','搜尋來源國':'Search source countries','未選＝全部':'None selected = all','清除選擇':'Clear selection',
'全部已確認國家':'All identified countries','全部來源':'All sources','排名顯示':'Ranking size','重設所有篩選':'Reset all filters','重設':'Reset','匯出資料':'Export CSV',
'AT A GLANCE / 研究摘要':'AT A GLANCE / SUMMARY','依目前篩選期間計算':'Based on the selected period',
'期間進口總額':'Total imports','已選來源國金額':'Selected source imports','最新資料月份':'Latest data month','整體市場':'Entire market','占期間 World':'Share of period World total','已確認來源':'Identified sources',
'進口規模如何隨時間變化？':'How have imports changed over time?',
'所選來源國的月度總額 · USD':'Monthly imports from selected sources · USD','進口金額':'Import value','缺月保留斷點，不補為零':'Missing months remain gaps, not zeros',
'哪些國家是主要來源？':'Which countries are the main sources?','所選期間的進口金額排名':'Import value ranking for the selected period','查看完整資料':'Explore all data','占比以 World 為分母':'Shares use the World total',
'貿易來源的地理分布':'Where do imports come from?','所選期間與來源國的進口金額分布':'Imports by source country for the selected period','進口金額分級圖例':'Import value legend',
'相同月份，不同年度':'Same months, different years','所選來源國月度總額':'Monthly imports from selected sources','同月份對照':'same-month comparison','橫軸：月份 · 每條線代表一個年度 · 缺月不補零':'X-axis: month · One line per year · Missing months remain gaps',
'完整的月份與國家明細，跟隨市場、商品、期間與來源國篩選；保留原始商品及分類版本。':'Explore monthly country records using the shared market, product, period and source filters. Original product codes and classification versions are preserved.',
'搜尋明細':'Search records','月份':'Month','代碼':'Code','商品月度市占':'Product monthly share','進口金額（USD）':'Import value (USD)','HS 版本':'HS version','商品':'Product','← 上一頁':'← Previous','下一頁 →':'Next →',
'資料處理流程':'Data pipeline','網站使用經過 dbt 測試與 checksum 驗證的 JSON 快照，不直接查詢 BigQuery。':'The website uses JSON snapshots validated by dbt tests and checksums, without querying BigQuery directly.',
'資料流程':'Data pipeline','公開貿易資料':'Public trade data','擷取與不可變原檔':'Ingestion & immutable raw files','建模與資料測試':'Modeling & data tests','精確數值與版本驗證':'Exact values & version checks','靜態網頁':'Static website','互動分析介面':'Interactive analysis',
'分析範圍':'Analysis scope','報告國':'Reporting market','貿易流向':'Trade flow','月度進口':'Monthly imports','分類版本':'Classification','金額單位':'Currency','美元 USD':'US dollars (USD)',
'指標如何計算':'How metrics are calculated','World 總額':'World total','直接使用來源的 World 月度值，每月只計一次，不加總重複的國家列。':'Uses the reported monthly World value once per month, without summing duplicate country rows.',
'市占與成長':'Share & growth','月度市占以同月 World 為分母；YoY 與 MoM 比對去年同月及上一日曆月。期間市占先加總金額再相除。':'Monthly share uses the same-month World total. YoY and MoM compare the same month last year and the previous calendar month. Period share divides the summed values.',
'資料限制':'Data limitations','特殊代碼 490 不歸入一般國家或地圖；因此國家合計可能小於 World。貿易來源不等於晶片製造地，進口規模不代表全球最終需求；圖表關聯也不代表因果。':'Special code 490 is excluded from country rankings and the map, so country totals may be below World. Trade origin does not identify chip fabrication location, imports do not measure global final demand, and chart correlations do not establish causation.',
'多選國家時，YoY 顯示 World 參考指標。缺月不補零，金額加總使用精確十進位運算。':'For multiple countries, YoY uses the World reference metric. Missing months are not filled with zeros. Values are summed using exact decimal arithmetic.',
'從快照到畫面':'From snapshot to screen','dbt build 與資料測試通過':'Pass dbt build and data tests','同一查詢讀取月份與國家模型':'Read monthly and country models in a single query','驗證金額、筆數、基期與缺值':'Validate values, row counts, comparison periods and missing data','產生版本與 SHA-256 checksum':'Generate version metadata and SHA-256 checksums','網站載入時再次核對版本與檔案':'Verify versions and files again on page load',
'資料來源與版本':'Sources & versions','Natural Earth 地圖資料':'Natural Earth map data','查看公開資料 Manifest':'View public data manifest',
'原始申報版本（依市場及月份保留）':'Original reported version (by market and month)',
'依所選報告市場與商品分析；保留各月份原始 HS 分類版本。':'Analysis follows the selected market and products, preserving the original monthly HS classifications.',
'854231、854232、854233、854239 與 854290（零件）':'854231, 854232, 854233, 854239 and 854290 (parts)',
'金額單位 USD／月度資料':'Values in USD / Monthly data','資料更新時間：':'Data updated: ','匯出時間 ':'Exported: ','（台北）':' (Taipei)',
'處理器與控制器':'Processors & controllers','記憶體':'Memories','放大器':'Amplifiers','其他積體電路':'Other integrated circuits','零件':'Parts',
'美國':'United States','日本':'Japan','德國':'Germany','韓國':'South Korea','中國':'China','香港':'Hong Kong','新加坡':'Singapore','馬來西亞':'Malaysia','越南':'Viet Nam','台灣':'Taiwan','荷蘭':'Netherlands','印度':'India','英國':'United Kingdom','法國':'France',
'資料不足':'N/A','未提供名稱':'Name unavailable','此篩選條件沒有資料。':'No records match these filters.',
'各市場與所選商品沒有共同可用月份。':'No common months are available across the markets and selected products.',
'起始月份不可晚於結束月份。':'The start month must not be later than the end month.','請至少選擇一項商品。':'Select at least one product.',
'已重設所有篩選。':'All filters have been reset.',
'無法讀取資料檔案。請稍後重試。':'Unable to load data. Please try again later.','資料完整性驗證失敗。請重新載入頁面。':'Data integrity check failed. Please reload the page.','資料版本不一致，已停止顯示。':'Data versions do not match. Display has been stopped.',
'此資料版本尚未受到支援。':'This data version is not supported.','資料載入失敗。':'Unable to load data.','重新載入':'Reload','正在載入資料。':'Loading data.','讀取並驗證資料快照。':'Reading and validating the data snapshot.',
'此範圍尚無可比較資料':'No comparable data in this range','缺少有效基期或來源資料':'No valid baseline or source data','請調整日期或來源國':'Adjust the dates or source countries','沒有符合條件的來源國':'No source countries match these filters','此期間沒有可比較資料':'No comparable data for this period','請調整年度或來源國':'Adjust the years or source countries',
'跨年度月度進口比較圖':'Monthly imports by year','各年度一至十二月進口總額，缺月保留斷點':'Monthly import totals from January to December by year; missing months remain gaps',
'所選來源國進口金額世界地圖':'World map of selected source imports','來源國進口金額分布，固定金額五級配色':'Source imports shown in five fixed value bands','精確金額請見排名與明細':'See rankings and records for exact values',
'低於 1M':'Below 1M','1B 以上':'1B and above','零金額':'Zero value','無資料':'No data','USD · 期間總額 · M＝百萬，B＝十億':'USD · Period total · M = million, B = billion','未映射金額：':'Unmapped value: ',
'多市場積體電路貿易研究':'Multi-market IC Trade Research','積體電路貿易研究':'IC Trade Research',
};
const entries=Object.entries(copy).sort((a,b)=>b[0].length-a[0].length);
let language='zh';
try {if(typeof document!=='undefined')language=localStorage.getItem('trade-language')==='en'?'en':'zh';} catch {}
export const getLanguage = () => language;
export function translate(text, lang=language) {
 if(lang!=='en')return text;
 let result=text
 .replace(/(.+)從全球進口的總額，不受來源國篩選影響。/g,'$1: imports from the world, unaffected by source filters.')
 .replace(/(.+)從目前所選來源國進口的合計金額。/g,'$1: combined imports from your selected sources.')
 .replace(/(.+)從全部已確認來源國進口的合計金額。/g,'$1: combined imports from all identified source countries.')
 .replace(/前 (\d+) 名/g,'Top $1')
 .replace(/所選期間有 (\d+) 個月份缺少 World 金額。期間總額與市占僅反映可用分母，請留意缺月。/g,'World values are missing for $1 month(s) in this period. Totals and shares use only available denominators.')
 .replace(/有效來源明細：([\d,]+) 筆；正金額：([\d,]+) 筆。資料範圍依各市場實際公布月份而異。/g,'Valid source records: $1; positive-value records: $2. Coverage follows each market’s published months.')
 .replace(/共 ([\d,]+) 筆 · 每頁 (\d+) 筆/g,'$1 records · $2 per page')
 .replace(/已選 (\d+) 個來源/g,'$1 sources selected')
 .replace(/(\d+) 個市場 · (\d+) 類商品/g,'$1 markets · $2 products')
 .replace(/(\d+) 個國家／地區/g,'$1 countries / areas')
 .replace(/(\d+) 個有效月份/g,'$1 available months')
 .replace(/(\d+) 類商品/g,'$1 products')
 .replace(/(\d+) 個年度/g,'$1 years')
 .replace(/(\d+) 月 · 各年度比較/g,'Month $1 · All years')
 .replace(/(\d+)\/12 月/g,'$1/12 months')
 .replace(/已匯出 ([\d,]+) 筆完整明細。/g,'Exported all $1 records.')
 .replace(/共同月份/g,'common months');
 for(const [zh,en] of entries)result=result.split(zh).join(en);
 return result.replace(/：/g,': ').replace(/（/g,' (').replace(/）/g,')').replace(/，/g,', ');
}
const originals=new WeakMap();
function update(node,key,value,set) {
 let record=originals.get(node);if(!record){record={};originals.set(node,record);}
 const old=record[key];const source=old&&old.output===value?old.source:value;
 const output=translate(source);record[key]={source,output};if(output!==value)set(output);
}
export function localize() {
 if(typeof document==='undefined')return;
 document.documentElement.lang=language==='en'?'en':'zh-Hant';
 const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
 let node;while((node=walker.nextNode())) {
  if(node.parentElement?.closest('script,style,[data-language]'))continue;
  update(node,'text',node.nodeValue,value=>node.nodeValue=value);
 }
 for(const element of document.querySelectorAll('[aria-label],[placeholder],[title],[data-tooltip]'))
  for(const key of ['aria-label','placeholder','title','data-tooltip'])if(element.hasAttribute(key))update(element,key,element.getAttribute(key),value=>element.setAttribute(key,value));
 update(document,'title',document.title,value=>document.title=value);
 for(const button of document.querySelectorAll('[data-language]'))button.setAttribute('aria-pressed',String(button.dataset.language===language));
}
export function setupLanguage(onChange) {
 for(const button of document.querySelectorAll('[data-language]'))button.addEventListener('click',()=>{
  language=button.dataset.language;try{localStorage.setItem('trade-language',language);}catch{}
  document.querySelector('#tooltip').hidden=true;localize();onChange();localize();
 });
 for(const event of ['input','change','click'])document.addEventListener(event,()=>queueMicrotask(localize));
 localize();
}
