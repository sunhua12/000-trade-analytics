import test from 'node:test';
import assert from 'node:assert/strict';
import {countryName} from '../src/countries.mjs';
test('country display labels preserve source names and codes',()=>{
 const row={source_name:'Rep. of Korea',map_iso3:'KOR',partner_code:'410'};
 assert.equal(countryName(row),'南韓');
 assert.equal(countryName(row,'en'),'Rep. of Korea');
 assert.equal(row.partner_code,'410');
 assert.equal(countryName({source_name:'Unknown area',map_iso3:'XXX'}),'Unknown area');
 assert.equal(countryName({source_name:'Europe EU, nes',map_iso3:'MCO'}),'歐洲歐盟（未另列明）');
});
