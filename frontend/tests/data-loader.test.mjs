import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {gzipSync} from 'node:zlib';
import {createDataLoader,pack,unpack} from '../src/data-loader.mjs';
import {deliveryFiles} from '../delivery.mjs';

const manifest={schema_version:'2.0.0',snapshot_id:'test',files:{}};
const rows=[{reporter_code:'842',partner_code:'004',import_value:'9007199254740993.123456789',yoy:null,month:'2024-01-01',has_world:false},{reporter_code:'156',partner_code:'392',import_value:'10',yoy:'0',month:'2024-01-01',has_world:true}];
const document={...manifest,rows};
const build=()=>deliveryFiles(manifest,document,document);
test('delivery is lossless, deterministic and each market contains its complete source scope',async()=>{
  const result=build();assert.deepEqual(unpack(pack(document)),rows);
  assert.deepEqual(result.manifest,build().manifest);
  const loader=createDataLoader(result.manifest,{read:async path=>result.files.find(file=>`./data/${file.filename}`===path).bytes});
  assert.deepEqual(await loader.monthly(),rows);
  for(const reporter of ['842','156'])assert.deepEqual(await loader.partners(reporter),rows.filter(row=>row.reporter_code===reporter));
});
test('load only the requested market and reuse concurrent and subsequent requests',async()=>{
  const result=build();const paths=[];
  const loader=createDataLoader(result.manifest,{read:async path=>{paths.push(path);return result.files.find(file=>`./data/${file.filename}`===path).bytes;}});
  const [first,second]=await Promise.all([loader.partners('842'),loader.partners('842')]);
  assert.strictEqual(first,second);assert.strictEqual(first,await loader.partners('842'));
  assert.equal(paths.length,1);assert.ok(paths[0].includes('partners-842-'));
  await loader.partners('156');assert.equal(paths.length,2);
});
test('reject corruption and evict failures so retry can succeed',async()=>{
  const result=build();let calls=0;
  const loader=createDataLoader(result.manifest,{read:async path=>{const bytes=result.files.find(file=>`./data/${file.filename}`===path).bytes;if(++calls===1){const broken=Buffer.from(bytes);broken[0]^=1;return broken;}return bytes;}});
  await assert.rejects(loader.partners('842'),/完整性/);
  assert.deepEqual(await loader.partners('842'),[rows[0]]);assert.equal(calls,2);
});
test('reject valid-checksum data from a different snapshot or with a wrong row count',async()=>{
  for(const change of [{snapshot_id:'other'},{rows:[]}]){
    const bytes=gzipSync(JSON.stringify(pack({...document,...change})));
    const metadata={path:'./data/test.json.gz',encoding:'gzip',bytes:bytes.length,row_count:rows.length,sha256:'sha256:'+createHash('sha256').update(bytes).digest('hex')};
    const loader=createDataLoader({...manifest,delivery:{partners:{'842':metadata}}},{read:async()=>bytes});
    await assert.rejects(loader.partners('842'),/版本不一致/);
  }
});
test('legacy snapshots remain readable with the same integrity checks',async()=>{
  const bytes=Buffer.from(JSON.stringify(document));const paths=[];
  const metadata={bytes:bytes.length,row_count:rows.length,sha256:'sha256:'+createHash('sha256').update(bytes).digest('hex')};
  const loader=createDataLoader({...manifest,files:{'partners.json':metadata}},{read:async path=>{paths.push(path);return bytes;}});
  assert.deepEqual(await loader.partners('842'),rows);assert.deepEqual(await loader.partners('156'),rows);
  assert.deepEqual(paths,['./data/partners.json']);
});
