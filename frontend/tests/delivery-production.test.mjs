import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {deliveryFiles} from '../delivery.mjs';
import {createDataLoader} from '../src/data-loader.mjs';
import {analyze,marketScope,csv} from '../src/analytics.mjs';

test('all production markets retain every row, exact KPI, trend, ranking and CSV',async()=>{
  const load=name=>JSON.parse(readFileSync(new URL(`../public/data/${name}.json`,import.meta.url)));
  const monthly=load('monthly'),partners=load('partners'),manifest=load('manifest');
  const result=deliveryFiles(manifest,monthly,partners);
  const loader=createDataLoader(result.manifest,{read:async path=>result.files.find(file=>`./data/${file.filename}`===path).bytes});
  const restoredMonthly=await loader.monthly();assert.deepEqual(restoredMonthly,monthly.rows);
  let restoredCount=0;
  for(const reporter of Object.keys(result.manifest.delivery.partners)){
    const restored=await loader.partners(reporter);
    assert.deepEqual(restored,partners.rows.filter(row=>(row.reporter_code??'842')===reporter));
    restoredCount+=restored.length;
    const products=manifest.products.map(row=>row.cmd_code);
    const baseline=marketScope(monthly.rows,partners.rows,reporter,products);
    const optimized=marketScope(restoredMonthly,restored,reporter,products);
    const filters={start:'2016-01-01',end:manifest.latest_data_month};
    assert.deepEqual(analyze(optimized.monthly,optimized.partners,filters),analyze(baseline.monthly,baseline.partners,filters));
    assert.equal(csv(optimized.rawPartners),csv(baseline.rawPartners));
  }
  assert.equal(restoredCount,partners.rows.length);
  const oldBytes=manifest.files['monthly.json'].bytes+manifest.files['partners.json'].bytes;
  const initialBytes=result.manifest.delivery.monthly.bytes+result.manifest.delivery.partners['842'].bytes;
  assert.ok(initialBytes<oldBytes*0.02,`initial data ${initialBytes} must be below 2% of ${oldBytes}`);
});
