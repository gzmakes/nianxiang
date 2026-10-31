// Synthetic UI tests: no real account, credential, network, or user session.
const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const src=fs.readFileSync('web/m.js','utf8');
function clip(from,to){const a=src.indexOf(from),b=src.indexOf(to,a);assert.ok(a>=0&&b>a);return src.slice(a,b)}
function element(){const hidden=new Set();return {value:'',textContent:'',innerHTML:'',disabled:false,classList:{add:x=>hidden.add(x),remove:x=>hidden.delete(x),toggle:(x,on)=>on?hidden.add(x):hidden.delete(x),contains:x=>hidden.has(x)}}}
function storage(){const m=new Map();return {get length(){return m.size},key:i=>Array.from(m.keys())[i]??null,getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k)};}
function setup(source,api,localStorage=storage()){
 const nodes=new Map(), $=x=>{if(!nodes.has(x))nodes.set(x,element());return nodes.get(x)};
 const state={session:{id:'old'}}, calls=[],entered=[],shown=[];
 const ctx=vm.createContext({$,state,localStorage,esc:s=>String(s??'').replace(/</g,'&lt;'),api:async(...args)=>{calls.push(args);return api(...args)},toast:s=>shown.push(s),enterSessionData:d=>entered.push(d)});
 vm.runInContext('let mActiveTurn=null, mQueuedTurns=[], mTurnQueue=[];'+clip('  const mobilePendingPrefix', '  async function loadCatalog()')+clip('  function openMobileCredentialSource(', '  function openMobileLocalFiles()')+'\nthis.open=openMobileCredentialSource;this.clear=clearMobileSourceForm;this.renderPending=renderMobilePendingNotice;this.dismiss=dismissMobilePendingNotice;',ctx);
 ctx.open(source);
 return {$,state,calls,entered,shown,ctx,localStorage};
}
const flush = async () => { for (let i=0;i<15;i++) await Promise.resolve(); };
const sample={ok:true,preview_id:'fixture',title:'样本',items:Array.from({length:9},(_,i)=>({title:`主题${i}<`,meta:`发件人${i}`,summary:`日期${i}`})),understanding:{facts:['事实一','事实二']}};
for(const source of ['gmail','notion']) {
 const secret=source==='gmail'?'#m-gmail-password':'#m-notion-token', other=source==='gmail'?'#m-gmail-address':'#m-notion-url';
 test(`${source}: one authorization reads and attaches the same preview to the current conversation without resending credentials`,async()=>{
  const env=setup(source,async(path)=>path.endsWith('/preview')?sample:{session:{id:'old'},messages:[],memories:[]});
  env.$(secret).value='dummy-secret';env.$(other).value='dummy-identifier';
  await env.$('#m-source-preview').onclick();
  assert.equal(env.$(secret).value,'');assert.match(env.$('#m-read-items').innerHTML,/主题8&lt;/);assert.match(env.$('#m-read-items').innerHTML,/发件人7/);assert.match(env.$('#m-read-items').innerHTML,/事实二/);
  assert.equal((env.$('#m-read-items').innerHTML.match(/生成理解时可能发送给模型/g)||[]).length,8);
  assert.deepEqual(JSON.parse(env.calls[1][1].body),{preview_id:'fixture',start_intro:true,session_id:'old'});assert.equal(env.entered[0].session.id,'old');
  assert.equal(env.localStorage.length,0);
 });
 test(`${source}: failed preview clears credential and does not offer confirmation`,async()=>{
  const env=setup(source,async()=>({ok:false,error:'synthetic failure'}));env.$(secret).value='dummy';env.$(other).value='dummy';
  await env.$('#m-source-preview').onclick();assert.equal(env.$(secret).value,'');assert.match(env.$('#m-source-hint').textContent,/synthetic failure/);assert.doesNotMatch(env.$('#m-read-items').innerHTML,/m-source-start/);
 });
 for(const [status,expected] of [[400,/预览已失效/],[0,/未能确认接入结果.*已接入资料列表.*核对/]]) test(`${source}: start failure ${status} gives accurate result`,async()=>{
  const env=setup(source,async(path)=>{if(path.endsWith('/preview'))return sample;const e=Error('failed');e.status=status;throw e});env.$(secret).value='dummy';env.$(other).value='dummy';
  await env.$('#m-source-preview').onclick();await env.$('#m-source-start').onclick();assert.match(env.$('#m-source-hint').textContent,expected);assert.equal(env.$('#m-source-start').disabled,true);assert.equal(env.entered.length,0);
  assert.equal(env.localStorage.length,status===400?0:1);
 });
 test(`${source}: cancelling during preview clears credential and discards response`,async()=>{
  let resolve;const waiting=new Promise(r=>resolve=r);const env=setup(source,async()=>waiting);env.$(secret).value='dummy';env.$(other).value='dummy';
  const running=env.$('#m-source-preview').onclick();env.ctx.clear();assert.equal(env.$(secret).value,'');resolve(sample);await running;assert.doesNotMatch(env.$('#m-read-items').innerHTML,/m-source-start/);
 });
 test(`${source}: cancellation during an uncertain commit still points to the connected-source list for verification`,async()=>{
  let reject;const waiting=new Promise((_,r)=>reject=r);const env=setup(source,async(path)=>path.endsWith('/preview')?sample:waiting);
  env.$(secret).value='dummy';env.$(other).value='dummy';
  const running=env.$('#m-source-preview').onclick();await flush();env.ctx.clear();reject(Error('offline'));await running;
  assert.match(env.shown[0],/结果未确认.*已接入资料列表.*核对/);assert.equal(env.entered.length,0);
  assert.equal(env.localStorage.length,1);
 });
 test(`${source}: uncertain creation survives reload and requires explicit dismissal`,async()=>{
  const shared=storage();let reject;const waiting=new Promise((_,r)=>reject=r);
  const env=setup(source,async(path)=>path.endsWith('/preview')?sample:waiting,shared);
  env.$(secret).value='dummy-secret';env.$(other).value='dummy-identifier';
  const running=env.$('#m-source-preview').onclick();await flush();assert.equal(shared.length,1);
  const key=shared.key(0);assert.match(key,/^xinji_h5_source_pending_/);assert.equal(shared.getItem(key),'1');
  assert.doesNotMatch(key+shared.getItem(key),/dummy|fixture/);
  env.ctx.clear();const reopened=setup(source,async()=>({}),shared);reopened.ctx.renderPending();
  assert.equal(reopened.$('#m-source-uncertain-notice').classList.contains('is-hidden'),false);
  reject(Error('offline'));await running;assert.equal(shared.length,1);
  reopened.ctx.dismiss();assert.equal(shared.length,0);assert.equal(reopened.$('#m-source-uncertain-notice').classList.contains('is-hidden'),true);
 });
 test(`${source}: cannot submit when persistence is unavailable`,async()=>{
  const blocked=storage();blocked.setItem=()=>{throw Error('blocked')};
  const env=setup(source,async()=>sample,blocked);env.$(secret).value='dummy';env.$(other).value='dummy';
  await env.$('#m-source-preview').onclick();await env.$('#m-source-start').onclick();
  assert.equal(env.calls.length,1);assert.match(env.$('#m-source-hint').textContent,/存储不可用/);
 });
 test(`${source}: late success after leaving still requires connected-source verification`,async()=>{
  let resolve;const waiting=new Promise(r=>resolve=r);
  const env=setup(source,async(path)=>path.endsWith('/preview')?sample:waiting);
  env.$(secret).value='dummy';env.$(other).value='dummy';
  const running=env.$('#m-source-preview').onclick();await flush();env.ctx.clear();resolve({session:{id:'new'}});await running;
  assert.equal(env.localStorage.length,1);assert.equal(env.entered.length,0);assert.match(env.shown[0],/结果未确认.*已接入资料列表.*核对/);
 });
}

const desktop=fs.readFileSync('web/app.js','utf8');
function desktopHelpers(){
 const start=desktop.indexOf('  const credentialPendingKey = ');
 const end=desktop.indexOf('  function showWz(n)', start);
 assert.ok(start>=0 && end>start);
 return desktop.slice(start,end);
}
for (const source of ['gmail','notion']) test(`desktop ${source}: preview shows all submitted fields and facts`, async()=>{
 const start=source==='gmail'?'  function renderGmailReal()':'  function renderNotionReal()';
 const end=source==='gmail'?'  function renderFeishuPicker()':'  function renderInsights()';
 const a=desktop.indexOf(start),b=desktop.indexOf(end,a);assert.ok(a>=0&&b>a);
 const nodes=new Map(), $=x=>{if(!nodes.has(x))nodes.set(x,element());return nodes.get(x)};
 const head=$('#read-head');head.querySelector=()=>null;head.insertAdjacentHTML=()=>{};
 const secret=source==='gmail'?'#wz-gmail-password':'#wz-notion-token';
 let valueAtRequest;
 const ctx=vm.createContext({$,state:{session:null},AbortController,localStorage:storage(),esc:s=>String(s??'').replace(/</g,'&lt;'),api:async()=>{valueAtRequest=$(secret).value;return sample},enterSession(){}});
 vm.runInContext(desktopHelpers()+desktop.slice(a,b)+`\nthis.run=render${source==='gmail'?'Gmail':'Notion'}Real`,ctx);ctx.run();
 $(source==='gmail'?'#wz-gmail-address':'#wz-notion-url').value='dummy';
 $(source==='gmail'?'#wz-gmail-password':'#wz-notion-token').value='dummy';
 await $(`#wz-${source}-preview`).onclick();
 assert.equal(valueAtRequest,'');assert.equal($(secret).value,'');
 const html=$(`#wz-${source}-result`).innerHTML;
 assert.match(html,/主题8&lt;/);assert.match(html,/发件人7/);assert.match(html,/事实二/);assert.equal((html.match(/生成理解时可能发送给模型/g)||[]).length,8);
});

for (const source of ['gmail','notion']) test(`desktop ${source}: leaving clears credentials and rejects late previews`, async()=>{
 const start=source==='gmail'?'  function renderGmailReal()':'  function renderNotionReal()';
 const end=source==='gmail'?'  function renderFeishuPicker()':'  function renderInsights()';
 const a=desktop.indexOf(start),b=desktop.indexOf(end,a);assert.ok(a>=0&&b>a);
 const nodes=new Map(), $=x=>{if(!nodes.has(x))nodes.set(x,element());return nodes.get(x)};
 const head=$('#read-head');head.querySelector=()=>null;head.insertAdjacentHTML=()=>{};
 let resolve,signal;const waiting=new Promise(r=>resolve=r);
 const ctx=vm.createContext({$,state:{session:null},AbortController,localStorage:storage(),esc:s=>String(s??'').replace(/</g,'&lt;'),api:async(_path,opts)=>{signal=opts.signal;return waiting},enterSession(){}});
 vm.runInContext(desktopHelpers()+desktop.slice(a,b)+`\nthis.run=render${source==='gmail'?'Gmail':'Notion'}Real;this.clear=clearCredentialForms`,ctx);ctx.run();
 const secret=source==='gmail'?'#wz-gmail-password':'#wz-notion-token';
 $(secret).value='dummy';$(source==='gmail'?'#wz-gmail-address':'#wz-notion-url').value='dummy';
 const pending=$(`#wz-${source}-preview`).onclick();assert.equal($(secret).value,'');
 ctx.clear();assert.equal(signal.aborted,true);resolve(sample);await pending;
 assert.equal($(`#wz-${source}-result`).innerHTML,'');
});
