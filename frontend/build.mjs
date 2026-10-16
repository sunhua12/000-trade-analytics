import {readFile, mkdir, cp, rename, rm, access} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=path.dirname(fileURLToPath(import.meta.url));
const manifest=JSON.parse(await readFile(path.join(root,'public/data/manifest.json'),'utf8'));
if(manifest.schema_version!=='1.0.0')throw new Error('Unsupported schema');
for(const name of ['monthly','partners']) {
 const payload=await readFile(path.join(root,`public/data/${name}.json`));
 const document=JSON.parse(payload);
 const digest='sha256:'+createHash('sha256').update(payload).digest('hex');
 const metadata=manifest.files[`${name}.json`];
 if(document.snapshot_id!==manifest.snapshot_id||document.schema_version!==manifest.schema_version||document.rows.length!==metadata.row_count||digest!==metadata.sha256||payload.length!==metadata.bytes)throw new Error('Data snapshot validation failed');
}
const stage=path.join(root,`.dist-${process.pid}`),dist=path.join(root,'dist'),backup=path.join(root,`.dist-backup-${process.pid}`);
let backedUp=false;
try {
 await mkdir(stage);
 await cp(path.join(root,'src'),stage,{recursive:true});
 await cp(path.join(root,'public'),stage,{recursive:true});
 await cp(path.join(root,'assets'),path.join(stage,'assets'),{recursive:true});
 try{await access(dist);await rename(dist,backup);backedUp=true;}catch(error){if(error.code!=='ENOENT')throw error;}
 try{await rename(stage,dist);}catch(error){if(backedUp)await rename(backup,dist);throw error;}
 if(backedUp)await rm(backup,{recursive:true});
 console.log(JSON.stringify({status:'built',snapshot_id:manifest.snapshot_id,directory:dist}));
} finally {await rm(stage,{recursive:true,force:true});}
