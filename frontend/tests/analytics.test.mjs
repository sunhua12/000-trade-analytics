import test from 'node:test';import assert from 'node:assert/strict';import {readFileSync} from 'node:fs';
import {sum,share,analyze,csv,units} from '../src/analytics.mjs';
const load=name=>JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`,import.meta.url))).rows;
const monthly=load('monthly'),partners=load('partners');
test('large NUMERIC sums preserve every digit and null stays null',()=>{assert.equal(sum(['9007199254740993.123456789','0.000000001']),'9007199254740993.12345679');assert.equal(sum([null,null]),null);assert.throws(()=>units(0.1));assert.equal(share('25','100'),'0.25');assert.equal(share('1','0'),null);});
test('country filters and Top N do not change World or full trend totals',()=>{const base={start:'2023-01-01',end:'2024-12-01',topN:10};const all=analyze(monthly,partners,base);const code=partners[0].partner_code;const one=analyze(monthly,partners,{...base,countries:[code],topN:5});assert.equal(all.world,one.world);assert.equal(one.selected,sum(partners.filter(row=>row.partner_code===code).map(row=>row.import_value)));assert.equal(one.yoy[0].value,partners.find(row=>row.month==='2023-01-01'&&row.partner_code===code)?.yoy??null);const top5=analyze(monthly,partners,{...base,topN:5});assert.deepEqual(all.trend,top5.trend);assert.equal(top5.top.length,5);assert.equal(sum(all.trend.map(row=>row.value)),all.selected);});
test('period share uses totals and multi-country YoY remains World',()=>{const config={start:'2024-01-01',end:'2024-12-01',countries:[partners[0].partner_code,partners[1].partner_code],topN:5};const result=analyze(monthly,partners,config);assert.equal(result.selectedShare,share(result.selected,result.world));assert.deepEqual(result.yoy,monthly.filter(row=>row.month>=config.start).map(row=>({month:row.month,value:row.world_yoy})));assert.deepEqual(result.scatter,partners.filter(row=>row.month===config.end&&config.countries.includes(row.partner_code)&&row.yoy!==null));});
test('missing month produces a null gap and bad ranges fail',()=>{const months=[{month:'2023-01-01',world_value:'10',has_world:true,has_countries:false,world_yoy:null},{month:'2023-02-01',world_value:null,has_world:false,has_countries:false,world_yoy:null}];const result=analyze(months,[],{start:'2023-01-01',end:'2023-02-01'});assert.deepEqual(result.trend.map(row=>row.value),[null,null]);assert.equal(result.worldMonths,1);assert.throws(()=>analyze(months,[],{start:'2023-02-01',end:'2023-01-01'}));});
test('CSV keeps exact amounts, escaped names and complete scope',()=>{const output=csv([{month:'2024-01-01',partner_code:'004',source_name:'=HYPERLINK("evil")',import_value:'9007199254740993.123456789',market_share:null,yoy:null,mom:null}]);assert.ok(output.includes('9007199254740993.123456789'));assert.ok(output.includes("\"'=HYPERLINK"));assert.ok(output.includes('"004"'));});

test('market scope isolates reporters and aggregates product denominators',async()=>{
  const {marketScope}=await import('../src/analytics.mjs');
  const months=['842','156'].flatMap(reporter_code=>['854231','854232'].map(cmd_code=>({month:'2024-01-01',reporter_code,cmd_code,world_value:reporter_code==='842'?'100':'999',previous_year_world_value:null,has_countries:true})));
  const detail=['842','156'].flatMap(reporter_code=>['854231','854232'].map(cmd_code=>({month:'2024-01-01',reporter_code,cmd_code,partner_code:'392',import_value:'25',source_name:'Japan',hs_version:'H6'})));
  const scoped=marketScope(months,detail,'842',['854231','854232']);
  assert.equal(scoped.monthly[0].world_value,'200');
  assert.equal(scoped.partners[0].import_value,'50');
  assert.equal(scoped.partners[0].market_share,'0.25');
  assert.equal(scoped.partners[0].yoy,null);
  assert.throws(()=>marketScope(months,detail,'842',[]));
  assert.equal(marketScope(months,detail,'842',['854231','854239']).monthly[0].world_value,null);
});

test('cross-market comparison intersects months including internal gaps',async()=>{
  const {commonMonths}=await import('../src/analytics.mjs');
  const scopes=[{reporter_code:'842',cmd_code:'854231',months:['2024-01-01','2024-03-01']},{reporter_code:'156',cmd_code:'854231',months:['2024-01-01','2024-02-01','2024-03-01']}];
  assert.deepEqual(commonMonths(scopes,['842','156'],['854231']),['2024-01-01','2024-03-01']);
  assert.deepEqual(commonMonths(scopes,['842','156'],['854231','854232']),[]);
});

test('aggregate growth stays missing when a selected product has no country base',async()=>{
  const {marketScope}=await import('../src/analytics.mjs');
  const monthly=['2023-01-01','2024-01-01'].flatMap(month=>['854231','854232'].map(cmd_code=>({month,cmd_code,reporter_code:'842',world_value:'100',previous_year_world_value:month.startsWith('2024')?'100':null,has_countries:true})));
  const partners=['2023-01-01','2024-01-01'].map(month=>({month,reporter_code:'842',cmd_code:'854231',partner_code:'392',hs_version:'H6',import_value:month.startsWith('2024')?'25':'10'}));
  const result=marketScope(monthly,partners,'842',['854231','854232']);
  assert.equal(result.partners.find(row=>row.month==='2024-01-01').yoy,null);
});

test('scatter includes all eligible countries independently of ranking Top N',()=>{const config={start:'2024-01-01',end:'2024-12-01',topN:5};const result=analyze(monthly,partners,config);assert.deepEqual(result.scatter,partners.filter(row=>row.month===config.end&&row.yoy!==null));assert.ok(result.scatter.length>result.top.length);assert.deepEqual(result.scatter,analyze(monthly,partners,{...config,topN:10}).scatter);});

test('annual comparison aligns calendar months and preserves missing months',async()=>{const {annualSeries,annualChart}=await import('../src/charts.mjs');const rows=[{month:'2023-01-01',value:'100'},{month:'2023-03-01',value:'120'},{month:'2024-01-01',value:'200'}];const series=annualSeries(rows);assert.deepEqual(series.map(item=>item.year),['2023','2024']);assert.equal(series[0].months[1].value,null);assert.equal(series[1].months[0].value,'200');assert.equal(series[1].months[2].value,null);const container={clientWidth:440,innerHTML:''};annualChart(container,rows);assert.ok(!/NaN|Infinity/.test(container.innerHTML));assert.equal((container.innerHTML.match(/class="annual-series"/g)||[]).length,2);});


test('trend keeps calendar spacing and breaks lines across omitted common months',async()=>{const {lineChart}=await import('../src/charts.mjs');const container={clientWidth:400,innerHTML:''};lineChart(container,[{month:'2024-01-01',value:'10'},{month:'2024-02-01',value:'20'},{month:'2024-04-01',value:'30'}]);assert.equal((container.innerHTML.match(/class="plot-line"/g)||[]).length,2);assert.ok(container.innerHTML.includes('cx="158"'));});
