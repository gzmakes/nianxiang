// Only explicit local metadata reads. No account, token, model config or port scan.
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const DOMAINS=['conversation','messages','memories','sources','moods','followups','boundary','actions','turns'];
const id=value=>typeof value==='string'&&/^[A-Za-z0-9_.:-]{1,128}$/.test(value);
function parseOrigin(value){
 if(typeof value!=='string'||!/^http:\/\/127\.0\.0\.1:([1-9][0-9]{0,4})$/.test(value))throw Error('请输入完整的 http://127.0.0.1:端口，不含路径、别名或其它信息。');
 const port=Number(value.slice(value.lastIndexOf(':')+1));if(port<1||port>65535)throw Error('端口应为1至65535。');return value;
}
function sameOrigin(value,origin){try{return new URL(value).origin===new URL(parseOrigin(origin)).origin}catch(_){return false}}
function readJSON(url,{signal,timeoutMs=3500,maxBytes=16384}={}){
 return new Promise((resolve,reject)=>{
  let settled=false,timer,request;const finish=(error,value)=>{if(settled)return;settled=true;clearTimeout(timer);signal?.removeEventListener('abort',abort);error?reject(error):resolve(value)};
  const abort=()=>{request?.destroy();finish(Error('核对已取消。'))};
  if(signal?.aborted)return abort();
  request=http.request(url,{method:'GET',headers:{Accept:'application/json','Cache-Control':'no-store',Connection:'close'},agent:false},response=>{
   if(response.statusCode!==200){response.destroy();return finish(Error('本机服务没有返回可用的核对信息（不跟随重定向）。'))}
   const length=response.headers['content-length'];if(length!==undefined&&(!/^\d+$/.test(length)||Number(length)>maxBytes)){response.destroy();return finish(Error('核对信息超过限定大小。'))}
   const chunks=[];let size=0;response.on('data',chunk=>{size+=chunk.length;if(size>maxBytes){response.destroy();finish(Error('核对信息超过限定大小。'))}else chunks.push(chunk)});
   response.on('error',()=>finish(Error('暂时无法完整读取本机服务。')));
   response.on('end',()=>{try{finish(null,JSON.parse(Buffer.concat(chunks).toString('utf8')))}catch(_){finish(Error('本机服务的核对格式不完整。'))}});
  });
  request.on('error',()=>finish(Error('暂时无法连接这个本机服务。')));
  signal?.addEventListener('abort',abort,{once:true});timer=setTimeout(()=>{request.destroy();finish(Error('核对本机服务超时。'))},timeoutMs);request.end();
 });
}
function metadata(origin,capabilities,changes){
 const version=capabilities?.contract_version,parts=typeof version==='string'?version.match(/^(\d+)\.(\d+)\.(\d+)$/):null;
 if(!parts||Number(parts[1])!==1||Number(parts[2])<7||capabilities.deployment_mode!=='local_single_user'||capabilities.features?.conversation_change_cursor!==true)throw Error('这个服务尚不支持当前持续对话核对，请先更新服务。');
 if(!id(changes?.service_instance_id)||!id(changes?.conversation_id)||typeof changes.cursor!=='string'||!/^[A-Za-z0-9_-]{1,2048}$/.test(changes.cursor)||changes.reset_required!==true||changes.reset_reason!=='initial'||!Array.isArray(changes.domains)||changes.domains.length!==DOMAINS.length||new Set(changes.domains).size!==DOMAINS.length||DOMAINS.some(domain=>!changes.domains.includes(domain)))throw Error('服务身份或持续对话回执不完整。');
 return {version:1,mode:'shared',origin:parseOrigin(origin),service_instance_id:changes.service_instance_id,conversation_id:changes.conversation_id,contract_version:version};
}
function sameIdentity(a,b){return !!a&&!!b&&a.origin===b.origin&&a.service_instance_id===b.service_instance_id&&a.conversation_id===b.conversation_id}
async function probeService(origin,{expected=null,signal,read=readJSON}={}){
 origin=parseOrigin(origin);
 const capabilities=await read(origin+'/api/capabilities',{signal});const changes=await read(origin+'/api/conversation/changes',{signal});
 const result=metadata(origin,capabilities,changes);if(expected&&!sameIdentity(expected,result))throw Error('服务身份或持续对话已更换，旧空间没有被接管。请重新核对后明确选择。');return result;
}
function partitionFor(value){if(!validProfile(value)||value.mode!=='shared')throw Error('Invalid local selection.');return 'persist:xinji-shared-v1-'+crypto.createHash('sha256').update(JSON.stringify([value.origin,value.service_instance_id,value.conversation_id])).digest('hex')}
function validProfile(value){return !!value&&value.version===1&&(value.mode==='own'||value.mode==='shared'&&(()=>{try{return parseOrigin(value.origin)&&id(value.service_instance_id)&&id(value.conversation_id)&&typeof value.contract_version==='string'}catch(_){return false}})())}
function selectionStore(directory){
 const file=path.join(directory,'desktop-connection.json');
 return {file,load(){try{const stat=fs.lstatSync(file);if(!stat.isFile()||stat.isSymbolicLink()||stat.size>4096)throw Error();const value=JSON.parse(fs.readFileSync(file,'utf8'));if(!validProfile(value))throw Error();return value}catch(error){if(error.code==='ENOENT')return null;return {invalid:true}}},save(value){
  if(!validProfile(value))throw Error('连接选择无效，原空间保留。');const data=value.mode==='own'?{version:1,mode:'own'}:{version:1,mode:'shared',origin:parseOrigin(value.origin),service_instance_id:value.service_instance_id,conversation_id:value.conversation_id,contract_version:value.contract_version};
  const temporary=file+'.'+crypto.randomUUID()+'.tmp';try{fs.mkdirSync(directory,{recursive:true,mode:0o700});fs.writeFileSync(temporary,JSON.stringify(data),{mode:0o600,flag:'wx'});fs.renameSync(temporary,file)}catch(_){try{fs.unlinkSync(temporary)}catch(_){}throw Error('未能保存本机连接选择，尚未切换空间。')}
 }};
}
function createSelectionFlow({probe=probeService,save,activate,clock=Date.now}){
 let generation=0,candidate=null,busy=false;const invalidate=()=>{generation++;candidate=null};
 return {invalidate,get busy(){return busy},async verify(origin){const ticket=++generation;candidate=null;const value=await probe(parseOrigin(origin));if(ticket!==generation)return {ok:false,reason:'superseded'};candidate={...value,nonce:crypto.randomUUID(),at:clock()};return {ok:true,...candidate}},async connect({nonce,origin,confirmed}={}){
  if(busy||confirmed!==true||!candidate||nonce!==candidate.nonce||origin!==candidate.origin||clock()-candidate.at>60000)throw Error('请先核对这个地址，再明确确认连接。');
  const ticket=generation,chosen={...candidate};busy=true;
  try{const verified=await probe(chosen.origin,{expected:chosen});if(ticket!==generation)return false;save(verified);const activated=await activate(verified);candidate=null;return activated!==false}finally{busy=false}
 },async own(confirmed){if(busy||confirmed!==true)throw Error('请明确选择返回本机原空间。');invalidate();busy=true;try{const value={version:1,mode:'own'};save(value);return (await activate(value))!==false}finally{busy=false}}};
}
module.exports={DOMAINS,parseOrigin,sameOrigin,readJSON,metadata,probeService,sameIdentity,partitionFor,validProfile,selectionStore,createSelectionFlow};
