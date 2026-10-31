// Synthetic scheduling and race checks only. Live reads/model acceptance are separate.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/connection-intro.js','utf8');
const flush=async()=>{for(let i=0;i<15;i++)await Promise.resolve();};
function deferred(){let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j});return{promise,resolve,reject};}
function node(){const hidden=new Set();return{children:[],dataset:{},textContent:'',classList:{toggle:(key,on)=>on?hidden.add(key):hidden.delete(key),contains:key=>hidden.has(key)},replaceChildren(){this.children=[]},appendChild(child){this.children.push(child)},setAttribute(){}};}
function setup(reply=async()=>job()){
 const host=node(),calls=[],applied=[],saved=new Map(),timers=new Map(),state={sid:'same',safe:true,rev:1};let counter=0;
 const context={window:{},document:{createElement:node},localStorage:{getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v),removeItem:k=>saved.delete(k)},
   setTimeout(fn){const id=++counter;timers.set(id,fn);return id},clearTimeout(id){timers.delete(id)}};
 vm.runInNewContext(source,context);
 const tracker=context.window.XinjiConnectionIntro.create({api:async(...args)=>{calls.push(args);return reply(...args)},host,getSessionId:()=>state.sid,
   canApply:()=>state.safe,revision:()=>state.rev,apply:data=>applied.push(data)});
 return{tracker,host,calls,applied,saved,timers,state,module:context.window.XinjiConnectionIntro};
}
function job(extra={}){return{id:'one',session_id:'same',source_id:'feishu',status:'running',message_id:null,...extra};}
function snapshot(){return{session:{id:'same'},messages:[{id:'intro-message',role:'assistant',text:'合成边界回复'}]};}

test('one completed connection produces a pending status, never a fake chat message or another source request',async()=>{
 const e=setup();assert.equal(e.tracker.start(job()),true);assert.equal(e.host.children.length,1);assert.match(e.host.children[0].textContent,/这次接入的资料.*接着说/);
 assert.equal(e.applied.length,0);await e.tracker.poll();assert.equal(e.calls.length,1);assert.match(e.calls[0][0],/^\/api\/connections\/intro\/one\?session_id=same$/);assert.equal(e.calls[0][1],undefined);
});

test('the same job is not duplicated and unrelated sources never claim a seven-day scan',()=>{
 for(const source_id of ['local_files','waytoagi','jike','notion','git','connection']){
  const e=setup();e.tracker.start(job({source_id}));e.tracker.start(job({source_id}));assert.equal(e.tracker.size(),1);
  assert.match(e.host.children[0].textContent,/这次接入的资料/);assert.doesNotMatch(e.host.children[0].textContent,/7 天/);
 }
});

test('completed and failed jobs with an actual saved message refresh the same conversation and clear pending status',async()=>{
 for(const status of ['completed','failed']){
  const e=setup(async path=>path==='/api/conversation'?snapshot():job({status,message_id:'intro-message'}));e.tracker.start(job());await e.tracker.poll();
  assert.equal(e.applied.length,1);assert.equal(e.applied[0].messages[0].id,'intro-message');assert.equal(e.tracker.size(),0);assert.equal(e.host.children.length,0);assert.equal(e.timers.size,0);
 }
});

test('a user sending words while the job finishes keeps the latest local chat untouched until safe',async()=>{
 const e=setup(async path=>path==='/api/conversation'?snapshot():job({status:'completed',message_id:'intro-message'}));e.tracker.start(job());e.state.safe=false;
 await e.tracker.poll();assert.equal(e.applied.length,0);assert.equal(e.calls.length,1);
 e.state.safe=true;await e.tracker.poll();assert.equal(e.applied.length,1);
});

test('a mutation during the conversation read prevents an older snapshot replacing newer messages',async()=>{
 const waiting=deferred(),e=setup(async path=>path==='/api/conversation'?waiting.promise:job({status:'completed',message_id:'intro-message'}));e.tracker.start(job());
 const polling=e.tracker.poll();await flush();e.state.rev++;waiting.resolve(snapshot());await polling;
 assert.equal(e.applied.length,0);assert.equal(e.tracker.size(),1);
});

test('a late response after changing the ongoing conversation or leaving the page never applies data',async()=>{
 for(const change of ['session','stop']){
  const waiting=deferred(),e=setup(async path=>path==='/api/conversation'?waiting.promise:job({status:'completed',message_id:'intro-message'}));e.tracker.start(job());
  const polling=e.tracker.poll();await flush();if(change==='session')e.state.sid='other';else e.tracker.stop();waiting.resolve(snapshot());await polling;assert.equal(e.applied.length,0);
 }
});

test('a declared completed response must actually contain the saved intro message before merging',async()=>{
 const e=setup(async path=>path==='/api/conversation'?{session:{id:'same'},messages:[]}:job({status:'completed',message_id:'intro-message'}));e.tracker.start(job());await e.tracker.poll();
 assert.equal(e.applied.length,0);assert.equal(e.tracker.size(),1);
});

test('withdrawn or superseded jobs quietly end instead of restarting model work',async()=>{
 const e=setup(async()=>job({status:'superseded'}));e.tracker.start(job());await e.tracker.poll();await e.tracker.poll();assert.equal(e.calls.length,1);assert.equal(e.tracker.size(),0);assert.equal(e.applied.length,0);
});

test('failed, interrupted and missing records retain an honest status without polling terminal jobs forever',async()=>{
 for(const type of ['failed','interrupted','missing']){
  const e=setup(async()=>{if(type==='missing'){const error=Error('not found');error.status=404;throw error;}return job({status:type,error:'合成中断'});});
  e.tracker.start(job());await e.tracker.poll();await e.tracker.poll();assert.equal(e.calls.length,1);assert.equal(e.timers.size,0);assert.equal(e.host.children.length,1);assert.equal(e.applied.length,0);
 }
});

test('network failures are shown without replaying connect/intro creation, then can recover',async()=>{
 let failed=true;const e=setup(async path=>{if(failed)throw Error('offline');return path==='/api/conversation'?snapshot():job({status:'completed',message_id:'intro-message'});});
 e.tracker.start(job());await e.tracker.poll();assert.match(e.host.children[0].textContent,/正在核对洞察回复/);assert.equal(e.applied.length,0);failed=false;await e.tracker.poll();assert.equal(e.applied.length,1);assert.ok(e.calls.every(([path])=>path!=='/api/connections/intro'));
});

test('reload storage contains job IDs only, and resume merely checks existing work',async()=>{
 const e=setup();e.tracker.start(job({error:'PRIVATE_SENTINEL',scope:{text:'PRIVATE_SENTINEL'}}));const saved=e.saved.get('nianxiang_connection_intro_same');assert.equal(saved,'["one"]');assert.doesNotMatch(saved,/PRIVATE/);
 e.tracker.stop();e.tracker.resume();await e.tracker.poll();assert.equal(e.calls.length,1);assert.equal(e.calls[0][1],undefined);
});

test('unconnected, stale and snapshots from another connector cannot gain a checkmark',()=>{
 const e=setup(),badge=node(),control=node();badge.dataset={connectionSource:'apple_calendar',connectionIdle:'需授权'};control.dataset={connectionControl:'apple_calendar',connectionIdle:'连接'};
 const root={querySelectorAll:selector=>selector==='[data-connection-source]'?[badge]:[control]};
 for(const sources of [[],[{connector_id:'other'}],[{connector_id:'apple_calendar',stale:true}]]){e.module.syncBadges(root,{sources});assert.equal(badge.textContent,'需授权');assert.equal(control.textContent,'连接');}
 e.module.syncBadges(root,{sources:[{connector_id:'apple_calendar',stale:false}]});assert.equal(badge.textContent,'✓ 已连接');assert.equal(control.textContent,'管理');
});

test('an intro creation failure without a job ID stays visible and performs no polling or retries',async()=>{
 const e=setup();assert.equal(e.tracker.start({id:null,session_id:'same',source_id:'feishu',status:'failed',error:'这次整理没有开始'}),true);assert.match(e.host.children[0].textContent,/没有开始/);await e.tracker.poll();assert.equal(e.calls.length,0);assert.equal(e.timers.size,0);assert.equal(e.applied.length,0);
});
