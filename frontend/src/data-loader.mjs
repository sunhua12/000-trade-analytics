// Delivery encoding only: preserve strings (NUMERIC and codes), nulls and row order.
export function pack(document) {
  const columns=[...new Set(document.rows.flatMap(Object.keys))];
  return {schema_version:document.schema_version,snapshot_id:document.snapshot_id,
    columns,rows:document.rows.map(row=>columns.map(key=>row[key]??null))};
}
export function unpack(document) {
  if(!document.columns)return document.rows;
  return document.rows.map(values=>Object.fromEntries(document.columns.map((key,index)=>[key,values[index]])));
}
export async function fetchBytes(path, {immutable=false, timeout=30000}={}) {
  try {
    const response=await fetch(path,{cache:immutable?'force-cache':'no-cache',signal:AbortSignal.timeout(timeout)});
    if(!response.ok)throw new Error('無法讀取資料檔案。請稍後重試。');
    return new Uint8Array(await response.arrayBuffer());
  } catch(error) {
    if(error.name==='TimeoutError'||error.name==='AbortError')throw new Error('資料下載逾時，請檢查連線後重試。');
    throw error;
  }
}
export const parse=bytes=>JSON.parse(new TextDecoder().decode(bytes));
export function createDataLoader(manifest, {read=fetchBytes}={}) {
  const cache=new Map();
  async function checked(metadata, fallback) {
    const bytes=await read(metadata.path??fallback,{immutable:Boolean(metadata.path)});
    const digest=await crypto.subtle.digest('SHA-256',bytes);
    const checksum='sha256:'+Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
    if(bytes.length!==metadata.bytes||checksum!==metadata.sha256)throw new Error('資料完整性驗證失敗。請重新載入頁面。');
    if(metadata.encoding==='gzip'&&typeof DecompressionStream==='undefined')throw new Error('瀏覽器不支援壓縮資料，請更新瀏覽器後重試。');
    const payload=metadata.encoding==='gzip'
      ? new Uint8Array(await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer())
      : bytes;
    const document=parse(payload);
    if(document.schema_version!==manifest.schema_version||document.snapshot_id!==manifest.snapshot_id||document.rows.length!==metadata.row_count)throw new Error('資料版本不一致，已停止顯示。');
    return unpack(document);
  }
  function once(key,metadata,fallback) {
    if(!metadata)return Promise.reject(new Error('此市場沒有可用的資料檔案。'));
    if(!cache.has(key))cache.set(key,checked(metadata,fallback).catch(error=>{cache.delete(key);throw error;}));
    return cache.get(key);
  }
  return {
    monthly:()=>once('monthly',manifest.delivery?.monthly??manifest.files['monthly.json'],'./data/monthly.json'),
    partners:reporter=>manifest.delivery
      ? once(reporter,manifest.delivery.partners[reporter])
      : once('partners',manifest.files['partners.json'],'./data/partners.json'),
  };
}
