import {amount, percent, monthLabel, share, sum} from './analytics.mjs';
export const escape = text => String(text ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
export const empty = (title, copy = '') => `<div class="empty-chart"><span>${escape(title)}</span><small>${escape(copy)}</small></div>`;
const tooltipAttributes = text => `tabindex="0" data-tooltip="${escape(text)}"`;
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
  const width = Math.max(300, container.clientWidth - 32), height = mini ? 205 : 280;
  const left = mini ? 20 : 62, right = 18, top = mini ? 12 : 26, bottom = mini ? 15 : 44;
  const values = valid.map(row => Number(row.value));
  const scale = axisScale(values, {ratio});
  const {low, high} = scale;
  const x = index => left + (width - left - right) * index / Math.max(1, rows.length - 1);
  const y = value => top + (height - top - bottom) * (high - Number(value)) / (high - low);
  const format = scale.format;
  let content = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(label)}"><title>${escape(label)}，${valid.length} 個有效月份</title>`;
  if (!mini) for (const value of scale.ticks) {
    content += `<line class="grid-line" x1="${left}" x2="${width-right}" y1="${y(value)}" y2="${y(value)}"/><text class="axis-label" x="${left-10}" y="${y(value)+3}" text-anchor="end">${format(value)}</text>`;
  }
  let segments = [], current = [];
  rows.forEach((row,index) => {if(row.value === null) {if(current.length) segments.push(current); current=[];} else current.push([x(index), y(row.value)]);});
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
  container.innerHTML = rows.map((row,index) => `<div class="ranking-row" ${tooltipAttributes(`${row.name}（${row.code}）\nUSD ${amount(row.value, false)}\n占期間 World：${percent(share(row.value,world))}`)}><span class="rank-number">${String(index+1).padStart(2,'0')}</span><span class="rank-name">${escape(row.name)}</span><span class="rank-bar"><i style="width:${max>0 ? Number(row.value)/max*100:0}%"></i></span><span class="rank-value">${amount(row.value)}</span></div>`).join('');
}
export function scatterChart(container, rows) {
  if(!rows.length) {container.innerHTML=empty('此月份沒有有效比較點','需要同時有進口金額與去年同月基期');return;}
  const width=Math.max(300,container.clientWidth-32),height=280,left=62,right=25,top=30,bottom=48;
  const moneyScale=axisScale(rows.map(row=>row.import_value));
  const growthScale=axisScale(rows.map(row=>row.yoy),{ratio:true});
  const max=moneyScale.high;
  const {low,high}=growthScale;
  const x=value=>left+(width-left-right)*Number(value)/max;
  const y=value=>top+(height-top-bottom)*(high-Number(value))/(high-low);
  let content=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="進口金額與 YoY 散佈圖"><title>進口金額與 YoY，${rows.length} 個有效來源國</title>`;
  for(const v of growthScale.ticks) {
    content+=`<line class="grid-line" x1="${left}" x2="${width-right}" y1="${y(v)}" y2="${y(v)}"/><text class="axis-label" x="${left-10}" y="${y(v)+3}" text-anchor="end">${growthScale.format(v)}</text>`;
  }
  for(const v of moneyScale.ticks) {
    content+=`<text class="axis-label" x="${x(v)}" y="${height-25}" text-anchor="middle">${moneyScale.format(v)}</text>`;
  }
  content+=`<text class="axis-label" x="${width/2}" y="${height-5}" text-anchor="middle">進口金額（USD）</text>`;
  for(const [index,row] of rows.entries()) {
    content+=`<circle class="scatter-dot" cx="${x(row.import_value)}" cy="${y(row.yoy)}" r="4.5" ${tooltipAttributes(`${row.source_name || row.partner_code}\nUSD ${amount(row.import_value,false)}\nYoY：${percent(row.yoy)}`)}/>`;
    if(index<4) content+=`<text class="scatter-label" x="${x(row.import_value)+8}" y="${y(row.yoy)-7}">${escape(row.source_name || row.partner_code)}</text>`;
  }
  container.innerHTML=content+'</svg>';
}
export function mapChart(container, geometry, rankings) {
  const byIso = new Map();
  for(const row of rankings) if(row.iso3) byIso.set(row.iso3, sum([byIso.get(row.iso3) ?? '0',row.value]));
  const max = Math.max(1,...[...byIso.values()].map(Number));
  let content='<svg viewBox="0 0 900 390" role="img" aria-label="所選來源國進口金額世界地圖"><title>來源國進口金額分布，對數色階</title>';
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
    const ratio=value===undefined?0:Math.log10(Number(value)+1)/Math.log10(max+1);
    const color=value===undefined?'#2b3038':`rgb(${Math.round(80+140*ratio)},${Math.round(65+80*ratio)},${Math.round(56+42*ratio)})`;
    content+=`<path class="map-country${value===undefined?'':' has-data'}" fill="${color}" d="${path}" ${value===undefined?'':tooltipAttributes(`${feature.properties.name}\nUSD ${amount(value)}\n精確金額請見排名與明細`)}/>`;
  }
  container.innerHTML=content+'</svg>';
}
