import {amount, percent, monthLabel, share, sum} from './analytics.mjs';
export const escape = text => String(text ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
export const empty = (title, copy = '') => `<div class="empty-chart"><span>${escape(title)}</span><small>${escape(copy)}</small></div>`;
const tooltipAttributes = text => `tabindex="0" aria-label="${escape(text)}" data-tooltip="${escape(text)}"`;
// Shared regular ticks for money and percentage axes; always include zero.
export function axisScale(values, {ratio = false} = {}) {
  const numbers = values.map(Number).filter(Number.isFinite).map(v => ratio ? v * 100 : v);
  const min = Math.min(0, ...numbers), max = Math.max(0, ...numbers);
  const target = Math.max((max - min) / 4, ratio ? 1 : 1);
  const power = 10 ** Math.floor(Math.log10(target));
  const step = [1, 2, 5, 10].map(n => n * power).find(n => n >= target);
  const low = Math.floor(min / step) * step;
  const high = Math.max(low + step, Math.ceil(max / step) * step);
  const divisor = ratio ? 100 : 1;
  const ticks = Array.from({length: Math.round((high - low) / step) + 1}, (_, i) => (low + i * step) / divisor);
  const unit = step >= 1e9 ? 1e9 : step >= 1e6 ? 1e6 : step >= 1e3 ? 1e3 : 1;
  const suffix = {1: '', 1000: 'K', 1000000: 'M', 1000000000: 'B'}[unit];
  return {low: low / divisor, high: high / divisor, ticks,
    format: value => ratio ? `${Math.round(value * 100)}%` : `${Math.round(value / unit).toLocaleString('en-US')}${suffix}`};
}
export function lineChart(container, rows, {ratio = false, compact = false, mini = false, label = '進口金額'} = {}) {
  const valid = rows.filter(row => row.value !== null);
  if (!valid.length) {container.innerHTML = empty('此範圍尚無可比較資料', ratio ? '缺少有效基期或來源資料' : '請調整日期或來源國');return;}
  const width = Math.max(300, container.clientWidth - 32), height = mini ? 205 : width >= 700 ? 410 : 300;
  const left = mini ? 20 : 62, right = 18, top = mini ? 12 : 26, bottom = mini ? 15 : 44;
  const values = valid.map(row => Number(row.value));
  const scale = axisScale(values, {ratio});
  const {low, high} = scale;
  const monthIndex = month => Number(month.slice(0,4))*12+Number(month.slice(5,7))-1;
  const firstMonth = monthIndex(rows[0].month), lastMonth = monthIndex(rows.at(-1).month);
  const x = index => left + (width - left - right) * (monthIndex(rows[index].month)-firstMonth) / Math.max(1,lastMonth-firstMonth);
  const y = value => top + (height - top - bottom) * (high - Number(value)) / (high - low);
  const format = scale.format;
  let content = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(label)}"><title>${escape(label)}，${valid.length} 個有效月份</title>`;
  if (!mini) for (const value of scale.ticks) {
    content += `<line class="grid-line" x1="${left}" x2="${width-right}" y1="${y(value)}" y2="${y(value)}"/><text class="axis-label" x="${left-10}" y="${y(value)+3}" text-anchor="end">${format(value)}</text>`;
  }
  let segments = [], current = [];
  rows.forEach((row,index) => {if(index>0&&monthIndex(row.month)-monthIndex(rows[index-1].month)>1) {if(current.length) segments.push(current);current=[];}if(row.value === null) {if(current.length) segments.push(current); current=[];} else current.push([x(index), y(row.value)]);});
  if(current.length) segments.push(current);
  for (const points of segments) {
    const path = points.map(([px,py], index) => `${index?'L':'M'}${px.toFixed(2)},${py.toFixed(2)}`).join(' ');
    if(!ratio && points.length > 1) content += `<path d="${path} L${points.at(-1)[0]},${height-bottom} L${points[0][0]},${height-bottom}Z" class="plot-area"/>`;
    content += `<path class="plot-line" d="${path}" ${mini?'style="stroke:var(--green)"':''}/>`;
  }
  const step = Math.max(1, Math.ceil(rows.length / (width < 440 ? 4 : 6)));
  rows.forEach((row,index) => {
    if(!mini && (index % step === 0 || index === rows.length-1)) content += `<text class="axis-label" x="${x(index)}" y="${height-10}" text-anchor="middle">${monthLabel(row.month)}</text>`;
    if(row.value !== null) content += `<circle class="plot-dot" cx="${x(index)}" cy="${y(row.value)}" r="${mini?1.5:2.5}" ${tooltipAttributes(`${monthLabel(row.month)}\n${label}：${ratio ? percent(row.value) : 'USD ' + amount(row.value, false)}`)}/>`;
  });
  container.innerHTML = content + '</svg>';
}
export function rankChart(container, rows, world) {
  if(!rows.length) {container.innerHTML=empty('沒有符合條件的來源國');return;}
  const max = Number(rows[0].value);
  container.innerHTML = rows.map((row,index) => `<div class="ranking-row" data-iso="${escape(row.iso3||'')}" ${tooltipAttributes(`${row.name}（${row.code}）\nUSD ${amount(row.value, false)}\n占期間 World：${percent(share(row.value,world))}`)}><span class="rank-number">${String(index+1).padStart(2,'0')}</span><span class="rank-name">${escape(row.name)}</span><span class="rank-bar"><i style="width:${max>0 ? Number(row.value)/max*100:0}%"></i></span><span class="rank-value">${amount(row.value,true)}<small>${percent(share(row.value,world))} World</small></span></div>`).join('');
}
export function annualSeries(rows) {
  const years=[...new Set(rows.map(row=>row.month.slice(0,4)))].sort();
  return years.map(year=>({year,months:Array.from({length:12},(_,index)=>{
    const month=`${year}-${String(index+1).padStart(2,'0')}-01`;
    return {month,value:rows.find(row=>row.month===month)?.value??null};
  })}));
}
export function annualChart(container, rows) {
  const series=annualSeries(rows),valid=rows.filter(row=>row.value!==null);
  if(!valid.length) {container.innerHTML=empty('此期間沒有可比較資料','請調整年度或來源國');return;}
  const width=Math.max(320,container.clientWidth-32),height=300,left=62,right=22,top=20,bottom=40;
  const scale=axisScale(valid.map(row=>row.value));
  const x=index=>left+(width-left-right)*index/11;
  const y=value=>top+(height-top-bottom)*(scale.high-Number(value))/(scale.high-scale.low);
  const colors=series.map((item,index)=>index===series.length-1?'#286b79':['#a9b7b5','#b9a68f','#879da5','#c7bdb0'][index%4]);
  let svg=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="跨年度月度進口比較圖"><title>各年度一至十二月進口總額，缺月保留斷點</title>`;
  for(const tick of scale.ticks) svg+=`<line class="grid-line" x1="${left}" x2="${width-right}" y1="${y(tick)}" y2="${y(tick)}"/><text class="axis-label" x="${left-8}" y="${y(tick)+3}" text-anchor="end">${scale.format(tick)}</text>`;
  for(let month=0;month<12;month++) svg+=`<text class="axis-label" x="${x(month)}" y="${height-12}" text-anchor="middle">${month+1}</text>`;
  series.forEach((item,index)=>{
    const color=colors[index%colors.length],dash=index===series.length-1?'none':['none','5 3','2 3'][index%3];
    let path='',connected=false;
    item.months.forEach((row,month)=>{
      if(row.value===null) {connected=false;return;}
      path+=`${connected?'L':'M'}${x(month)},${y(row.value)} `;connected=true;
    });
    svg+=`<g class="annual-series" data-year="${item.year}"><path d="${path}" fill="none" stroke="${color}" stroke-width="${index===series.length-1?3:1.4}" stroke-dasharray="${dash}"/>`;
    item.months.forEach((row,month)=>{if(row.value!==null)svg+=`<circle cx="${x(month)}" cy="${y(row.value)}" r="3" fill="${color}" ${tooltipAttributes(`${month+1} 月 · 各年度比較\n`+series.map(year=>`${year.year}：${year.months[month].value===null?'無資料':'USD '+amount(year.months[month].value,false)}`).join('\n'))}/>`;});
    svg+='</g>';
  });
  container.innerHTML=svg+'</svg><div class="annual-legend">'+series.map((item,index)=>`<span><i style="background:${colors[index%colors.length]}"></i>${item.year}<small>${item.months.filter(row=>row.value!==null).length}/12 月</small></span>`).join('')+'</div>';
}
export const mapBands = [
  {limit:1e6,color:'#f0dfcf',label:'低於 1M'},
  {limit:1e7,color:'#dcbb99',label:'1M–10M'},
  {limit:1e8,color:'#c49167',label:'10M–100M'},
  {limit:1e9,color:'#a86743',label:'100M–1B'},
  {limit:Infinity,color:'#75432f',label:'1B 以上'},
];
export function mapColor(value) {
  if(value===undefined||value===null) return '#e3e6e1';
  if(Number(value)===0) return '#9ca9aa';
  return mapBands.find(band=>Number(value)<band.limit).color;
}
export function mapChart(container, geometry, rankings) {
  const byIso = new Map();
  for(const row of rankings) if(row.iso3) byIso.set(row.iso3, sum([byIso.get(row.iso3) ?? '0',row.value]));
  let content='<svg viewBox="0 0 900 390" role="img" aria-label="所選來源國進口金額世界地圖"><title>來源國進口金額分布，固定金額五級配色</title>';
  for(const feature of geometry.features) {
    if(feature.properties.iso3==='ATA') continue;
    const polygons=feature.geometry.type==='Polygon'?[feature.geometry.coordinates]:feature.geometry.coordinates;
    let path='';
    for(const polygon of polygons) for(const ring of polygon) {
      let previous=null;
      for(const [longitude,latitude] of ring) {
        const px=(longitude+180)*2.5,py=(83-latitude)*2.5;
        const move=previous===null || Math.abs(longitude-previous)>180;
        path+=`${move?'M':'L'}${px.toFixed(1)},${py.toFixed(1)} `; previous=longitude;
      }
      path+='Z ';
    }
    const value=byIso.get(feature.properties.iso3);
    const color=mapColor(value);
    content+=`<path class="map-country${value===undefined?'':' has-data'}" data-iso="${escape(feature.properties.iso3)}" fill="${color}" d="${path}" ${value===undefined?'':tooltipAttributes(`${feature.properties.name}\nUSD ${amount(value)}\n精確金額請見排名與明細`)}/>`;
  }
  container.innerHTML=content+'</svg>';
}

export function mapLegend(container) {
  container.innerHTML=mapBands.map(band=>`<span class="map-key"><i style="background:${band.color}"></i>${band.label}</span>`).join('')+'<span class="map-key"><i style="background:#9ca9aa"></i>零金額</span><span class="map-key"><i style="background:#e3e6e1"></i>無資料</span><span class="map-scale">USD · 期間總額 · M＝百萬，B＝十億</span>';
}
