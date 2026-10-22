import test from 'node:test';
import assert from 'node:assert/strict';
import {translate} from '../src/i18n.mjs';
test('language copy preserves exact values and translates dynamic coverage',()=>{
 assert.equal(translate('有效來源明細：222,959 筆；正金額：222,959 筆。資料範圍依各市場實際公布月份而異。','en'),'Valid source records: 222,959; positive-value records: 222,959. Coverage follows each market’s published months.');
 assert.equal(translate('USD 399,039,881,537','en'),'USD 399,039,881,537');
 assert.equal(translate('共 25,044 筆 · 每頁 50 筆','en'),'25,044 records · 50 per page');
});
test('Chinese copy remains intact and missing data is not presented as zero',()=>{
 assert.equal(translate('半導體進口數據觀察','zh'),'半導體進口數據觀察');
 assert.equal(translate('資料不足','en'),'N/A');
 assert.equal(translate('無資料','en'),'No data');
 assert.equal(translate('3 月 · 各年度比較','en'),'Month 3 · All years');
 assert.equal(translate('請至少選擇一項商品。','en'),'Select at least one product.');
});

test('metric explanations identify the importing market and source scope',()=>{
 assert.equal(translate('美國從全球進口的總額，不受來源國篩選影響。','en'),'United States: imports from the world, unaffected by source filters.');
 assert.equal(translate('日本從目前所選來源國進口的合計金額。','en'),'Japan: combined imports from your selected sources.');
});
