import {analyze, amount, percent, monthLabel, csv} from './analytics.mjs';
import {lineChart, rankChart, scatterChart, mapChart, escape} from './charts.mjs';
const $ = id => document.getElementById(id);
let dataset, current, pageIndex=0;
const selectedCountries = new Set();
const pageSize=50;
const pageTitles={overview:'美國半導體進口分析',data:'月度國家明細',method:'資料來源與指標定義'};
function showPage() {
  const key=location.hash.slice(1) in pageTitles ? location.hash.slice(1) : 'overview';
  document.querySelectorAll('[data-page]').forEach(link=>{const active=link.dataset.page===key;link.classList.toggle('active',active);if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');});
  for(const name of Object.keys(pageTitles)) $(name+'-page').hidden=name!==key||(name!=='method'&&!current);
  $('heading').textContent=pageTitles[key];
  $('analysis-controls').hidden=key==='method';
  $('filter-error').hidden=key==='method'||!$('filter-error').textContent;
  $('missing-notice').hidden=key==='method'||!current||current.worldMonths===current.months.length;
  if(key==='data' && current) renderTable();
}
async function fetchBytes(path) {
  const response=await fetch(path,{cache:'no-cache'});
  if(!response.ok) throw new Error('無法讀取資料檔案。請稍後重試。');
  return new Uint8Array(await response.arrayBuffer());
}
const parse = bytes=>JSON.parse(new TextDecoder().decode(bytes));
async function checkedDocument(name, manifest) {
  const bytes=await fetchBytes(`./data/${name}.json`);
  const metadata=manifest.files[`${name}.json`];
  const digest=await crypto.subtle.digest('SHA-256',bytes);
  const checksum='sha256:'+Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
  if(bytes.length!==metadata.bytes||checksum!==metadata.sha256) throw new Error('資料完整性驗證失敗。請重新載入頁面。');
  const document=parse(bytes);
  if(document.schema_version!=='1.0.0'||document.snapshot_id!==manifest.snapshot_id||document.rows.length!==metadata.row_count) throw new Error('資料版本不一致，已停止顯示。');
  return document.rows;
}
function filters() {return {start:$('start').value,end:$('end').value,countries:[...selectedCountries],topN:Number($('top-n').value)};}
function renderCountries() {
  const query=$('country-search').value.toLowerCase();
  const options=[...new Map(dataset.partners.map(row=>[row.partner_code,row])).values()].sort((a,b)=>(a.source_name||a.partner_code).localeCompare(b.source_name||b.partner_code));
  $('country-options').innerHTML=options.filter(row=>`${row.source_name} ${row.partner_code}`.toLowerCase().includes(query)).map(row=>`<label><input type="checkbox" value="${escape(row.partner_code)}" ${selectedCountries.has(row.partner_code)?'checked':''}><span>${escape(row.source_name||row.partner_code)}</span><small>${escape(row.partner_code)}</small></label>`).join('');
  $('selected-count').textContent=selectedCountries.size?`已選 ${selectedCountries.size} 個來源`:'未選＝全部';
  $('country-label').innerHTML=(selectedCountries.size===1?escape(options.find(row=>selectedCountries.has(row.partner_code))?.source_name||[...selectedCountries][0]):selectedCountries.size?`已選 ${selectedCountries.size} 個來源`:'全部已確認國家')+'<span class="chevron">⌄</span>';
}
function renderTable() {
  const query=$('table-search').value.toLowerCase();
  const rows=current.scope.filter(row=>`${row.source_name} ${row.partner_code}`.toLowerCase().includes(query)).sort((a,b)=>b.month.localeCompare(a.month)||a.partner_code.localeCompare(b.partner_code));
  const pages=Math.max(1,Math.ceil(rows.length/pageSize));pageIndex=Math.min(pageIndex,pages-1);
  $('table-body').innerHTML=rows.slice(pageIndex*pageSize,(pageIndex+1)*pageSize).map(row=>`<tr><td>${monthLabel(row.month)}</td><td>${escape(row.partner_code)}</td><td>${escape(row.source_name||'未提供名稱')}</td><td class="numeric">${amount(row.import_value,false)}</td><td class="numeric">${percent(row.market_share)}</td><td class="numeric">${percent(row.yoy)}</td><td class="numeric">${percent(row.mom)}</td></tr>`).join('')||'<tr><td colspan="7">此篩選條件沒有資料。</td></tr>';
  $('table-count').textContent=`共 ${rows.length.toLocaleString()} 筆 · 每頁 ${pageSize} 筆`;$('page-number').textContent=`${pageIndex+1} / ${pages}`;$('previous-page').disabled=pageIndex===0;$('next-page').disabled=pageIndex>=pages-1;
}
function render() {
  try {current=analyze(dataset.monthly,dataset.partners,filters());$('filter-error').textContent='';$('filter-error').hidden=true;$('download').disabled=false;}
  catch(error) {current=null;$('filter-error').textContent=error.message;$('filter-error').hidden=false;$('download').disabled=true;for(const key of ['overview','data'])$(key+'-page').hidden=true;return;}
  showPage();
  const config=filters();
  $('world-kpi').textContent=amount(current.world);$('selected-kpi').textContent=amount(current.selected);$('latest-kpi').textContent=current.last?monthLabel(current.last):'資料不足';
  $('world-months').textContent=`${current.worldMonths} / ${current.months.length} 個有效月份`;$('selected-share').textContent=percent(current.selectedShare);$('country-kpi').textContent=`${current.rankings.length} 個國家／地區`;
  $('world-kpi').parentElement.title=current.world===null?'資料不足':`USD ${amount(current.world,false)}`;$('selected-kpi').parentElement.title=current.selected===null?'資料不足':`USD ${amount(current.selected,false)}`;
  const incomplete=current.worldMonths<current.months.length;
  $('missing-notice').hidden=!incomplete;$('missing-notice').textContent=incomplete?`所選期間有 ${current.months.length-current.worldMonths} 個月份缺少 World 金額。期間總額與市占僅反映可用分母，請留意缺月。`:'';
  lineChart($('trend-chart'),current.trend,{label:'進口金額'});$('trend-foot').textContent=`${current.trend.filter(row=>row.value!==null).length} 個有效月份`;
  rankChart($('ranking-chart'),current.top,current.world);$('ranking-top').textContent=`TOP ${config.topN}`;
  const latest=current.months.find(row=>row.month===config.end);
  mapChart($('map-chart'),dataset.geometry,current.rankings);$('map-note').textContent=`未映射金額：USD ${amount(current.unmapped??'0')}`;
  scatterChart($('scatter-chart'),current.scatter);$('scatter-caption').textContent=`${monthLabel(config.end)} · 期間 Top ${config.topN} 來源國`;$('scatter-note').textContent=`${current.scatter.length} 個有效資料點`;
  renderTable();
}
function toast(message) {$('toast').textContent=message;$('toast').hidden=false;setTimeout(()=>$('toast').hidden=true,3000);}
function bind() {
  for(const id of ['start','end','top-n']) $(id).addEventListener('change',()=>{pageIndex=0;render();});
  $('country-search').addEventListener('input',renderCountries);
  $('country-options').addEventListener('change',event=>{if(event.target.checked)selectedCountries.add(event.target.value);else selectedCountries.delete(event.target.value);renderCountries();pageIndex=0;render();});
  $('clear-countries').addEventListener('click',()=>{selectedCountries.clear();renderCountries();pageIndex=0;render();});
  $('reset').addEventListener('click',()=>{$('start').value=dataset.monthly[0].month;$('end').value=dataset.monthly.at(-1).month;$('top-n').value='10';selectedCountries.clear();$('country-search').value='';$('table-search').value='';pageIndex=0;renderCountries();render();toast('已重設所有篩選。');});
  $('table-search').addEventListener('input',()=>{pageIndex=0;renderTable();});
  $('previous-page').addEventListener('click',()=>{pageIndex--;renderTable();});$('next-page').addEventListener('click',()=>{pageIndex++;renderTable();});
  $('download').addEventListener('click',()=>{const link=document.createElement('a');const url=URL.createObjectURL(new Blob([csv(current.scope)],{type:'text/csv;charset=utf-8'}));link.href=url;link.download=`semiconductor-imports-${$('start').value.slice(0,7)}-${$('end').value.slice(0,7)}.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast(`已匯出 ${current.scope.length.toLocaleString()} 筆完整明細。`);});
  addEventListener('hashchange',()=>{if(current)render();else showPage();});
  let resizeFrame;addEventListener('resize',()=>{cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(()=>{if(current)render();});});
  document.addEventListener('click',event=>{if(!$('country-menu').contains(event.target))$('country-menu').open=false;});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){$('country-menu').open=false;$('tooltip').hidden=true;}});
  function tooltip(event) {const target=event.target.closest('[data-tooltip]');if(!target)return;const tip=$('tooltip');tip.textContent=target.dataset.tooltip;tip.style.whiteSpace='pre-line';tip.hidden=false;const rect=target.getBoundingClientRect();const x=event.clientX||rect.left+rect.width/2;const y=event.clientY||rect.top;tip.style.left=`${Math.max(8,Math.min(innerWidth-tip.offsetWidth-12,x+14))}px`;tip.style.top=`${Math.max(8,Math.min(innerHeight-tip.offsetHeight-12,y+16))}px`;}
  document.addEventListener('pointerover',tooltip);document.addEventListener('focusin',tooltip);
  document.addEventListener('pointerout',event=>{if(event.target.closest('[data-tooltip]'))$('tooltip').hidden=true;});document.addEventListener('focusout',()=>$('tooltip').hidden=true);
}
async function init() {
  try {
    const manifest=parse(await fetchBytes('./data/manifest.json'));
    if(manifest.schema_version!=='1.0.0')throw new Error('此資料版本尚未受到支援。');
    const [monthly,partners,geometry]=await Promise.all([checkedDocument('monthly',manifest),checkedDocument('partners',manifest),fetchBytes('./assets/world.json').then(parse)]);
    dataset={manifest,monthly,partners,geometry};
    $('data-updated').textContent=`資料更新時間：${new Date(manifest.generated_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei',hour12:false})}（台北）`;
    for(const id of ['start','end'])$(id).innerHTML=monthly.map(row=>`<option value="${row.month}">${row.month.slice(0,7)}</option>`).join('');
    $('start').value=monthly[0].month;$('end').value=monthly.at(-1).month;
    $('method-latest').textContent=monthLabel(manifest.latest_data_month);$('version-note').textContent=`Snapshot ${manifest.snapshot_id}\nSchema ${manifest.schema_version}\n匯出時間 ${new Date(manifest.generated_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})}（台北）`;
    $('load-state').hidden=true;$('app').hidden=false;renderCountries();bind();render();
  }catch(error){$('load-state').innerHTML=`<h1>資料載入失敗。</h1><p>${escape(error.message)}</p><button type="button" id="retry" class="download-button">重新載入</button>`;$('retry').addEventListener('click',()=>location.reload());console.error(error);}
}
init();
