// Real shipped auth functions, synthetic official URLs and fake windows: no CLI/account/network access.
const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const OFFICIAL='https://accounts.feishu.cn/oauth/v1/device/verify/?flow_id=synthetic-flow&user_code=TEST-CODE';
function setup(mobile,{blocked=false,nativeBridge=null}={}) {
 const source=fs.readFileSync(mobile?'web/m.js':'web/app.js','utf8');
 const start=source.indexOf(mobile?'  let mAuthTimer = null':'  let authPollTimer = null');
 const end=source.indexOf(mobile?'  function renderMemeText':'  async function openApps()',start);assert.ok(start>=0&&end>start);
 const nodes=new Map(), intervals=new Map(), timeouts=[], apiCalls=[], lifecycle=[], windows=[], bridgeCalls=[];
 let sourceOpen=false,next=0,handler=async()=>({status:'pending',url:OFFICIAL});
 function $(id){if(!nodes.has(id)){const classes=new Set(['is-hidden']);nodes.set(id,{classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x)},textContent:'',href:'',src:'',disabled:false,innerHTML:'',removeAttribute(key){this[key]='';},focus(){lifecycle.push(['focus',id,sourceOpen]);}})}return nodes.get(id)}
 const ctx={$,state:{session:{id:'synthetic-conversation'},context:null},URL,
   api:(...args)=>{apiCalls.push(args);lifecycle.push(['api',args[0]]);return handler(...args)},
   setInterval:fn=>{const id=++next;intervals.set(id,fn);return id},clearInterval:id=>intervals.delete(id),
   setTimeout:fn=>timeouts.push(fn),toast(){},els:{onboarding:{classList:{contains:()=>true}}},showWz(){},loadRealSources(){},loadToday(){},
   XinjiSourceDialog:{isOpen:()=>sourceOpen},closeSourceDialog(){lifecycle.push(['close-source']);sourceOpen=false;},
   prepareSourceDialog(){lifecycle.push(['return-source']);sourceOpen=true;},renderFeishuPicker(){lifecycle.push(['show-picker']);},
   open(url,target){lifecycle.push(['open',url,target]);if(blocked)return null;const popup={closed:false,opener:{},navigations:[],location:{replace(value){popup.navigations.push(value);}},close(){this.closed=true;}};windows.push(popup);return popup;}};
 if(nativeBridge)ctx.xinjiDesktop={openLarkAuth:url=>{bridgeCalls.push(url);return nativeBridge(url);}};
 ctx.window=ctx;
 vm.createContext(ctx);
 vm.runInContext(source.slice(start,end)+`\nthis.openAuth=${mobile?'startLarkAuthMobile':'startLarkAuth'};this.closeAuth=${mobile?'closeLarkAuthMobile':'closeLarkAuth'};this.canChoose=larkCanChooseDocuments;`,ctx);
 return {ctx,$,intervals,timeouts,apiCalls,lifecycle,windows,bridgeCalls,openSource:()=>sourceOpen=true,setHandler:fn=>handler=fn,
   modal:mobile?'#m-auth':'#auth-modal',status:mobile?'#m-auth-status':'#auth-status',link:mobile?'#m-auth-url':'#auth-url',retry:mobile?'#m-auth-retry':'#auth-retry',hint:mobile?'#m-auth-hint':'#auth-hint'};
}
function deferred(){let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j});return{promise,resolve,reject}}
async function flushMicrotasks(){for(let i=0;i<8;i++)await Promise.resolve();}
for(const mobile of [false,true]){
 const label=mobile?'H5':'Web';
 test(`${label}: user click reserves a safe window before POST and preserves the exact opaque official URL`,async()=>{
  const h=setup(mobile);await h.ctx.openAuth('document',{force:true});
  assert.equal(h.lifecycle[0][0],'open');assert.equal(h.lifecycle[0][1],'about:blank');
  assert.equal(h.apiCalls[0][0],'/api/auth/lark/start');assert.deepEqual(JSON.parse(h.apiCalls[0][1].body),{force:true});
  assert.equal(h.windows[0].opener,null);assert.deepEqual(h.windows[0].navigations,[OFFICIAL]);assert.equal(h.$(h.link).href,OFFICIAL);
  assert.equal(h.ctx.canChoose(),false);assert.equal(h.intervals.size,1);
 });
 test(`${label}: blocked popup leaves a validated manual official link and a truthful instruction`,async()=>{
  const h=setup(mobile,{blocked:true});await h.ctx.openAuth('document',{force:true});
  assert.equal(h.$(h.link).classList.contains('is-hidden'),false);assert.equal(h.$(h.link).href,OFFICIAL);assert.match(h.$(h.hint).textContent,/点击下方链接/);
 });
 test(`${label}: unsafe URL never navigates or becomes a link; retry remains available`,async()=>{
  for(const url of ['javascript:alert(1)','http://accounts.feishu.cn/x','https://accounts.feishu.cn.evil.invalid/x','https://evil.invalid/x','https://u:p@accounts.feishu.cn/x','https://accounts.feishu.cn:8443/x']){
   const h=setup(mobile);h.setHandler(async()=>({status:'pending',url}));await h.ctx.openAuth();
   assert.deepEqual(h.windows[0].navigations,[]);assert.equal(h.windows[0].closed,true);assert.equal(h.$(h.link).href,'');assert.equal(h.$(h.link).classList.contains('is-hidden'),true);assert.equal(h.intervals.size,0);assert.equal(h.$(h.retry).classList.contains('is-hidden'),false);
  }
 });
 test(`${label}: international official URL remains byte-for-byte unchanged`,async()=>{
  const h=setup(mobile),url='https://accounts.larksuite.com/oauth/v1/device/verify/?opaque=a%2Fb%2BC&user_code=SYNTHETIC';h.setHandler(async()=>({status:'pending',url}));await h.ctx.openAuth();assert.equal(h.$(h.link).href,url);assert.deepEqual(h.windows[0].navigations,[url]);
 });
 test(`${label}: expiry clears old URL and QR; retry is another explicit same-purpose forced request`,async()=>{
  const h=setup(mobile);let expired=false;h.setHandler(async path=>path.endsWith('/status')?{status:'error',error:'授权已过期'}:{status:'pending',url:OFFICIAL,qr:'data:image/png;base64,AAAA'});
  await h.ctx.openAuth('search',{force:true});await [...h.intervals.values()][0]();
  assert.equal(h.$(h.link).href,'');assert.equal(h.$(h.link).classList.contains('is-hidden'),true);assert.equal(h.intervals.size,0);assert.equal(h.ctx.canChoose(),false);
  if(!mobile){assert.equal(h.$('#auth-qr').src,'');assert.equal(h.$('#auth-qr').classList.contains('is-hidden'),true);}
  assert.equal(h.$(h.retry).classList.contains('is-hidden'),false);await h.$(h.retry).onclick();
  assert.equal(h.apiCalls.at(-1)[0],'/api/auth/lark/search/start');assert.deepEqual(JSON.parse(h.apiCalls.at(-1)[1].body),{force:true});
 });
 test(`${label}: polls do not overlap and network failure exposes manual retry instead of endless waiting`,async()=>{
  const h=setup(mobile),d=deferred();h.setHandler(path=>path.endsWith('/status')?d.promise:Promise.resolve({status:'pending',url:OFFICIAL}));await h.ctx.openAuth();
  const poll=[...h.intervals.values()][0],first=poll();await poll();assert.equal(h.apiCalls.filter(([path])=>path.endsWith('/status')).length,1);
  d.reject(Error('synthetic offline'));await first;assert.equal(h.intervals.size,0);assert.equal(h.$(h.link).href,'');assert.equal(h.$(h.retry).classList.contains('is-hidden'),false);
 });
 test(`${label}: only document success enables this-page connection and closes an unused blank window`,async()=>{
  const h=setup(mobile);h.setHandler(async()=>({status:'success'}));await h.ctx.openAuth('document',{force:true});assert.equal(h.ctx.canChoose(),true);assert.equal(h.windows[0].closed,true);assert.equal(h.$(h.link).href,'');
  const search=setup(mobile);search.setHandler(async()=>({status:'success'}));await search.ctx.openAuth('search');assert.equal(search.ctx.canChoose(),false);
 });
 test(`${label}: closing while start is in flight cannot revive a picker, URL or polling`,async()=>{
  const h=setup(mobile),d=deferred();h.setHandler(()=>d.promise);const first=h.ctx.openAuth('document',{force:true});h.ctx.closeAuth();d.resolve({status:'pending',url:OFFICIAL});await first;
  assert.equal(h.$(h.modal).classList.contains('is-hidden'),true);assert.equal(h.intervals.size,0);assert.equal(h.$(h.link).href,'');assert.equal(h.ctx.canChoose(),false);assert.ok(!h.lifecycle.some(step=>step[0]==='show-picker'));assert.equal(h.windows[0].closed,true);
 });
 test(`${label}: old poll and old completion timeout cannot finish or clear a newer flow`,async()=>{
  const h=setup(mobile),d=deferred();h.setHandler(path=>path.endsWith('/search/status')?d.promise:Promise.resolve({status:'pending',url:OFFICIAL}));await h.ctx.openAuth('search');const oldPoll=[...h.intervals.values()][0]();await h.ctx.openAuth('document',{force:true});d.resolve({status:'success'});await oldPoll;assert.equal(h.intervals.size,1);assert.equal(h.ctx.canChoose(),false);
  const h2=setup(mobile);h2.setHandler(async path=>path.endsWith('/search/start')?{status:'success'}:{status:'pending',url:OFFICIAL});await h2.ctx.openAuth('search');await h2.ctx.openAuth('document');h2.timeouts[0]();assert.equal(h2.$(h2.modal).classList.contains('is-hidden'),false);
 });
 test(`${label}: stale error or another conversation cannot alter the current auth surface`,async()=>{
  const h=setup(mobile),d=deferred();let n=0;h.setHandler(()=>++n===1?d.promise:Promise.resolve({status:'pending',url:OFFICIAL}));const old=h.ctx.openAuth('search');h.ctx.closeAuth();await h.ctx.openAuth('document');d.resolve({status:'error',error:'old failure'});await old;assert.equal(h.intervals.size,1);assert.equal(h.$(h.status).textContent,'等待你在飞书中确认…');
  const other=setup(mobile),late=deferred();other.setHandler(()=>late.promise);const waiting=other.ctx.openAuth();other.ctx.state.session={id:'other'};late.resolve({status:'success'});await waiting;assert.equal(other.ctx.canChoose(),false);assert.equal(other.timeouts.length,0);
 });
 test(`${label}: exact missing-app response offers only the static official setup guide, never automatic setup navigation`,async()=>{
  const h=setup(mobile),guide='https://open.feishu.cn/document/no_class/mcp-archive/feishu-cli-installation-guide.md';
  h.setHandler(async()=>({status:'error',error:'应用尚未配置',error_code:'needs_app_setup',setup_url:guide}));await h.ctx.openAuth('document',{force:true});
  assert.equal(h.$(h.link).href,guide);assert.equal(h.$(h.link).textContent,'首次配置飞书 CLI 应用');assert.equal(h.$(h.link).classList.contains('is-hidden'),false);assert.equal(h.windows[0].closed,true);assert.deepEqual(h.windows[0].navigations,[]);assert.equal(h.ctx.canChoose(),false);assert.equal(h.intervals.size,0);
  h.setHandler(async()=>({status:'pending',url:OFFICIAL}));await h.$(h.retry).onclick();assert.equal(h.$(h.link).href,OFFICIAL);assert.equal(h.$(h.link).textContent,'在飞书中打开授权');assert.deepEqual(h.windows.at(-1).navigations,[OFFICIAL]);
 });
 test(`${label}: other errors and nonexact setup guide URLs never become setup links`,async()=>{
  const guide='https://open.feishu.cn/document/no_class/mcp-archive/feishu-cli-installation-guide.md';
  for(const [error_code,setup_url] of [['configuration_unavailable',guide],['needs_app_setup',guide+'?redirect=evil'],['needs_app_setup','https://open.feishu.cn/page/cli'],['needs_app_setup','https://evil.invalid/guide']]){
   const h=setup(mobile);h.setHandler(async()=>({status:'error',error:'合成配置错误',error_code,setup_url}));await h.ctx.openAuth();assert.equal(h.$(h.link).href,'');assert.equal(h.$(h.link).classList.contains('is-hidden'),true);assert.deepEqual(h.windows[0].navigations,[]);
  }
 });
 test(`${label}: official setup guide is never accepted as an OAuth pending URL`,async()=>{
  const h=setup(mobile);h.setHandler(async()=>({status:'pending',url:'https://open.feishu.cn/document/no_class/mcp-archive/feishu-cli-installation-guide.md'}));await h.ctx.openAuth();assert.equal(h.$(h.link).href,'');assert.equal(h.intervals.size,0);assert.deepEqual(h.windows[0].navigations,[]);
 });
 test(`${label}: native bridge replaces blank popup and requests the validated official URL once despite polls`,async()=>{
  const h=setup(mobile,{nativeBridge:async()=>true});await h.ctx.openAuth('document',{force:true});await flushMicrotasks();
  assert.equal(h.windows.length,0);assert.ok(!h.lifecycle.some(step=>step[0]==='open'));assert.deepEqual(h.bridgeCalls,[OFFICIAL]);assert.match(h.$(h.hint).textContent,/已请求系统浏览器/);assert.equal(h.$(h.link).href,OFFICIAL);
  const poll=[...h.intervals.values()][0];await poll();await poll();assert.deepEqual(h.bridgeCalls,[OFFICIAL]);assert.equal(h.ctx.canChoose(),false);
 });
 test(`${label}: native false, reject, throw and nonboolean results keep manual link without repeat or browser fallback`,async()=>{
  for(const nativeBridge of [async()=>false,async()=>{throw Error('synthetic failure')},()=>{throw Error('synthetic throw')},async()=> 'true',async()=>({ok:true})]){
   const h=setup(mobile,{nativeBridge});await h.ctx.openAuth();await flushMicrotasks();assert.equal(h.windows.length,0);assert.equal(h.$(h.link).href,OFFICIAL);assert.equal(h.$(h.link).classList.contains('is-hidden'),false);assert.match(h.$(h.hint).textContent,/未能自动打开页面.*点击下方链接/);await [...h.intervals.values()][0]();assert.equal(h.bridgeCalls.length,1);
  }
 });
 test(`${label}: cancelled or expired native opening promises cannot restore a link or success state`,async()=>{
  for(const mode of ['close','expired']){
   const d=deferred(),h=setup(mobile,{nativeBridge:()=>d.promise});h.setHandler(async path=>path.endsWith('/status')?{status:'error',error:'合成授权过期'}:{status:'pending',url:OFFICIAL});await h.ctx.openAuth();
   if(mode==='close')h.ctx.closeAuth();else await [...h.intervals.values()][0]();const before=h.$(h.hint).textContent;
   d.resolve(true);await flushMicrotasks();assert.equal(h.$(h.link).href,'');assert.equal(h.$(h.hint).textContent,before);assert.equal(h.ctx.canChoose(),false);assert.equal(h.intervals.size,0);
  }
 });
 test(`${label}: old native promise cannot overwrite a newer flow's failed-open instruction`,async()=>{
  const d=deferred();let n=0;const h=setup(mobile,{nativeBridge:()=>++n===1?d.promise:Promise.resolve(false)});
  await h.ctx.openAuth();await h.ctx.openAuth('document',{force:true});await flushMicrotasks();assert.match(h.$(h.hint).textContent,/未能自动打开页面.*点击下方链接/);const before=h.$(h.hint).textContent;d.resolve(true);await flushMicrotasks();assert.equal(h.$(h.hint).textContent,before);assert.equal(h.bridgeCalls.length,2);assert.equal(h.$(h.link).href,OFFICIAL);
 });
 test(`${label}: native bridge never receives nonofficial URLs or the app setup guide`,async()=>{
  for(const value of [{status:'pending',url:'https://evil.invalid/auth'},{status:'pending',url:'https://open.feishu.cn/page/cli'},{status:'error',error:'首次配置',error_code:'needs_app_setup',setup_url:'https://open.feishu.cn/document/no_class/mcp-archive/feishu-cli-installation-guide.md'}]){
   const h=setup(mobile,{nativeBridge:async()=>true});h.setHandler(async()=>value);await h.ctx.openAuth();assert.equal(h.bridgeCalls.length,0);assert.equal(h.windows.length,0);assert.equal(h.intervals.size,0);
  }
 });
 test(`${label}: existing current-conversation source permits adding documents without persisting connection or tokens`,()=>{
  const h=setup(mobile);h.ctx.state.context={sources:[{connector_id:'feishu',stale:false}]};assert.equal(h.ctx.canChoose(),true);h.ctx.state.context.sources[0].stale=true;assert.equal(h.ctx.canChoose(),false);h.ctx.state.context={connector_id:'feishu'};assert.equal(h.ctx.canChoose(),true);h.ctx.state.session.source_revoked=true;assert.equal(h.ctx.canChoose(),false);
 });
}
test('Web cancellation releases the focus trap but never labels an unfinished connection as authorized',async()=>{
 const h=setup(false);h.openSource();await h.ctx.openAuth('document',{force:true});assert.ok(h.lifecycle.some(step=>step[0]==='close-source'));
 const focus=h.lifecycle.find(step=>step[0]==='focus');assert.equal(focus[2],false);h.ctx.closeAuth();assert.ok(h.lifecycle.some(step=>step[0]==='return-source'));assert.ok(!h.lifecycle.some(step=>step[0]==='show-picker'));assert.match(h.$('#read-head').innerHTML,/尚未完成/);assert.doesNotMatch(h.$('#read-head').innerHTML,/已授权/);
});
test('Web success is the only automatic path back into the document picker',async()=>{
 const h=setup(false);h.openSource();h.setHandler(async()=>({status:'success'}));await h.ctx.openAuth('document',{force:true});assert.ok(!h.lifecycle.some(step=>step[0]==='show-picker'));h.timeouts[0]();assert.ok(h.lifecycle.some(step=>step[0]==='show-picker'));
});
