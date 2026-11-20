import {createHash} from 'node:crypto';
import {gzipSync} from 'node:zlib';
import {pack} from './src/data-loader.mjs';

export function deliveryFiles(manifest, monthly, partners) {
  const files=[];
  function encode(name,rows) {
    const bytes=gzipSync(JSON.stringify(pack({schema_version:manifest.schema_version,snapshot_id:manifest.snapshot_id,rows})));
    const hash=createHash('sha256').update(bytes).digest('hex');
    const filename=`${name}-${hash}.json.gz`;
    files.push({filename,bytes,rows});
    return {path:`./data/${filename}`,encoding:'gzip',bytes:bytes.length,sha256:`sha256:${hash}`,row_count:rows.length};
  }
  const groups=new Map();
  for(const row of partners.rows){const reporter=row.reporter_code??'842';if(!groups.has(reporter))groups.set(reporter,[]);groups.get(reporter).push(row);}
  const delivery={monthly:encode('monthly',monthly.rows),partners:Object.fromEntries([...groups].map(([reporter,rows])=>[reporter,encode(`partners-${reporter}`,rows)]))};
  return {manifest:{...manifest,delivery},files};
}
