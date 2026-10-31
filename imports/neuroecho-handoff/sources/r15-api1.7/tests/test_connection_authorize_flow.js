// Synthetic direct-authorization race tests. These do not claim real device permissions.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const flush=async()=>{for(let i=0;i<15;i++)await Promise.resolve();};
function deferred(){let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j});return{promise,resolve,reject};}
function setup(mobile,reply){
 const src=fs.readFileSync(mobile?'web/m.js':'web/app.js','utf8');
 const name=mobile?'readMobileConfirmedSource':'readConfirmedSource',a=src.indexOf('  async function '+name+'() {'),b=src.indexOf('\n  async function ',a+5);
 const nodes=new Map(),$=key=>{if(!nodes.has(key))nodes.set(key,{textContent:'',disabled:false});return nodes.get(key)};
 const calls=[],entered=[],ledger=new Set(),state={session:{id:'same'},messages:[]},wizard={pendingSource:'apple_calendar'};
 const ctx={$,state,wizard,wz:wizard,api:async(...args)=>{calls.push(args);return reply(...args)},activeTurn:null,queuedTurns:[],turnQueue:[],mActiveTurn:null,mQueuedTurns:[],mTurnQueue:[],mobileSourceFormEpoch:1,
   beginCredentialRequest:()=>({controller:{signal:{}}}),credentialRequestCurrent:()=>ctx.current!==false,
   markCredentialStart:()=>{ledger.add('pending');return'pending'},markMobileSourceStart:()=>{ledger.add('pending');return'pending'},finishCredentialStart:key=>ledger.delete(key),finishMobileSourceStart:key=>ledger.delete(key),
   enterSession:data=>entered.push(data),enterSessionData:data=>entered.push(data)};
 vm.createContext(ctx);vm.runInContext(src.slice(a,b)+'\nthis.run='+name+';',ctx);
 return{ctx,$,state,calls,entered,ledger,wizard,button:$(mobile?'#m-read-btn':'#wz-read'),scope:$(mobile?'#m-read-scope':'#read-scope')};
}
const read={ok:true,preview_id:'actual-preview'},data={session:{id:'same'},intro:{id:'intro-job',status:'running'}};
for(const mobile of [false,true]){
 const label=mobile?'H5':'Web';
 test(`${label}: one authorization reads the past seven days then attaches the same preview and starts a real intro`,async()=>{
  const e=setup(mobile,async path=>path.endsWith('/read')?read:data);await e.ctx.run();assert.equal(e.calls.length,2);
  assert.deepEqual(JSON.parse(e.calls[0][1].body),{source_id:'apple_calendar',read_window:'recent7',start_intro:true});
  assert.deepEqual(JSON.parse(e.calls[1][1].body),{source_id:'apple_calendar',preview_id:'actual-preview',session_id:'same',start_intro:true});
  assert.equal(e.entered.length,1);assert.strictEqual(e.entered[0],data);assert.equal(e.ledger.size,0);assert.equal(e.wizard.pendingSource,null);
 });
 test(`${label}: duplicate clicks while a system read is pending issue only one request`,async()=>{
  const waiting=deferred(),e=setup(mobile,async path=>path.endsWith('/read')?waiting.promise:data);const running=e.ctx.run();await e.ctx.run();assert.equal(e.calls.length,1);waiting.resolve(read);await running;assert.equal(e.calls.length,2);assert.equal(e.entered.length,1);
 });
 test(`${label}: refusing permission leaves the dialog with an accurate error and never checks a connection`,async()=>{
  const e=setup(mobile,async()=>({ok:false,error:'系统权限未允许'}));await e.ctx.run();assert.equal(e.calls.length,1);assert.equal(e.entered.length,0);assert.equal(e.button.disabled,false);assert.match(e.scope.textContent,/权限未允许/);
 });
 test(`${label}: closing or switching while a read is running discards the late result without attachment`,async()=>{
  const waiting=deferred(),e=setup(mobile,async()=>waiting.promise);const running=e.ctx.run();if(mobile)e.ctx.mobileSourceFormEpoch++;else e.ctx.current=false;waiting.resolve(read);await running;assert.equal(e.calls.length,1);assert.equal(e.entered.length,0);
 });
 test(`${label}: a source withdrawal while the system reads prevents an overlapping attachment`,async()=>{
  const waiting=deferred(),e=setup(mobile,async()=>waiting.promise);const running=e.ctx.run();e.state.revokingSource=true;waiting.resolve(read);await running;assert.equal(e.calls.length,1);assert.equal(e.entered.length,0);assert.match(e.scope.textContent,/对话正在更新/);
 });
 test(`${label}: unknown save results do not auto-replay and leave a pending receipt for verification`,async()=>{
  const e=setup(mobile,async path=>{if(path.endsWith('/read'))return read;throw Error('response lost')});await e.ctx.run();await e.ctx.run();assert.equal(e.calls.length,2);assert.equal(e.entered.length,0);assert.equal(e.button.disabled,true);assert.equal(e.ledger.size,1);assert.match(e.scope.textContent,/结果尚未确认/);
 });
 test(`${label}: explicit expiry can retry a fresh read but never gains a success badge`,async()=>{
  const e=setup(mobile,async path=>{if(path.endsWith('/read'))return read;const error=Error('预览已失效');error.status=400;throw error});await e.ctx.run();assert.equal(e.entered.length,0);assert.equal(e.ledger.size,0);assert.equal(e.button.disabled,false);assert.match(e.scope.textContent,/预览已失效/);
 });
}
