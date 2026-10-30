// Actual shipped transport/ledger and renderer chat functions, synthetic storage
// and HTTP only. Reload is a new VM using the same storage; no model is called.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function cut(src,a,b){const i=src.indexOf(a),j=src.indexOf(b,i);assert.ok(i>=0&&j>i);return src.slice(i,j)}
function storage(){const values=new Map();return{fail:false,getItem:k=>values.get(k)||null,setItem(k,v){if(this.fail)throw Error('quota');values.set(k,v)}}}
function element(){const hidden=new Set();return{value:'',textContent:'',style:{},disabled:false,classList:{add:x=>hidden.add(x),remove:x=>hidden.delete(x),contains:x=>hidden.has(x),toggle(x,on){if(on)hidden.add(x);else hidden.delete(x)}},focus(){},remove(){},replaceChildren(){}}}
const tick=()=>new Promise(setImmediate), result=(cancelled=false)=>({messages:[{id:'user-saved',role:'user',text:'合成原话'}],memories:[],user_message_id:'user-saved',state:'responding',cancelled,action:'model.reply'});
let serial=0;
for(const mobile of [false,true]){
 const label=mobile?'H5':'Web/Desktop',src=fs.readFileSync(mobile?'web/m.js':'web/app.js','utf8');
 function setup(api,store=storage(),proposals=true,zone){
  const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)},input=$(mobile?'#m-input':'#input');
  const timers=new Map(),state={session:{id:'synthetic-session'},messages:[],memories:[]},toasts=[];
  const ctx=vm.createContext({api,localStorage:store,$,state,els:{input,messages:{insertAdjacentHTML(){}}},document:{createTextNode:x=>x},
   memoryProposal:{shouldRequest:()=>proposals,offer(){}},toast:s=>toasts.push(s),setOrb(){},renderAll(){},renderMessages(){},chatScroll:{render:f=>f()},
   touchLastSeen(){},loadAudit(){},loadNextStep(){},setTimeout(fn){const id=++serial;timers.set(id,fn);return id},clearTimeout:id=>timers.delete(id),
   crypto:{randomUUID:()=> 'request-fixture-'+(++serial)},Date,Map,Set,Promise,encodeURIComponent});
  ctx.window=ctx;
  if(zone){ctx.XinjiContactContract={supported:()=>true,timeZone:()=>zone};state.companionBoundary={refresh(){},capabilities:()=>({features:{unified_contact_claim:true}})};}
  vm.runInContext(fs.readFileSync('web/chat-transport.js','utf8'),ctx);
  const declarations=mobile?`let mQueuedTurns=[],mTurnQueue=[],mActiveTurn=null,mChatBlocked=false,mChatStorageBlocked=false,mTurnTimer=null,mLocalTurnId=0;
    const mDisplayedTurns=new Map(),mUncertainTurns=new Map(),mChatLedger=XinjiChatTransport.createLedger('h5');
    const mChatTransport=XinjiChatTransport.create(api,{ledger:mChatLedger,pause:async()=>{},attempts:1});`
   :`let queuedTurns=[],turnQueue=[],activeTurn=null,chatBlocked=false,chatStorageBlocked=false,turnTimer=null,localTurnId=0;
    const displayedTurns=new Map(),uncertainTurns=new Map(),chatLedger=XinjiChatTransport.createLedger('web');
    const chatTransport=XinjiChatTransport.create(api,{ledger:chatLedger,pause:async()=>{},attempts:1});`;
  const code=mobile?cut(src,'  async function recoverMobileChat()', '  function setupVoice()')+cut(src,'  function mPendingMessages(', '  // ---------- boot ----------')
   :cut(src,'  function pendingMessages(', '  function showMemoryContextNotice()');
  const pre=mobile?'mChat':'chat';
  vm.runInContext(declarations+code+`\nthis.send=${mobile?'send':'sendMessage'};this.recover=${mobile?'recoverMobileChat':'recoverChat'};
    this.restoreLedger=${mobile?'restoreMobileChatLedger':'restoreChatLedger'};this.keepDraft=${mobile?'keepMobileChatDraft':'keepChatDraft'};
    this.ledger=${pre}Ledger;this.transport=${pre}Transport;this.blocked=${mobile?'mUncertainTurns':'uncertainTurns'};`,ctx);
  return{ctx,state,input,store,$,toasts,flush:async()=>{const jobs=[...timers.values()];timers.clear();jobs.forEach(f=>f());await tick()}};
 }
 test(`${label}: new queue snapshots time zone and a reload preserves its exact transport`,async()=>{
  const writes=[];const env=setup(async(path,opt)=>{if(path==='/api/chat'){writes.push(JSON.parse(opt.body));throw Error('lost')}return {status:'unknown'}},storage(),false,'Asia/Shanghai');env.input.value='今天先别问';env.ctx.send(env.input.value);assert.equal(env.ctx.ledger.snapshot().queued[0].time_zone,'Asia/Shanghai');await env.flush();assert.equal(writes[0].time_zone,'Asia/Shanghai');
  const restored=setup(async()=>({status:'unknown'}),env.store,false,'America/New_York');restored.ctx.restoreLedger();assert.equal(restored.ctx.ledger.snapshot().pending[0].time_zone,'Asia/Shanghai');
 });
 test(`${label}: 850ms unsent text survives reload once as draft without any HTTP`,async()=>{
  let calls=0;const env=setup(async()=>{calls++;throw Error('must not send')});
  env.input.value='第一句';env.ctx.send(env.input.value);env.input.value='第二句';env.ctx.send(env.input.value);
  assert.equal(env.input.value,'');assert.equal(env.ctx.ledger.snapshot().queued.length,2);assert.equal(calls,0);
  const reopened=setup(async()=>{calls++;throw Error('must not send')},env.store);reopened.ctx.restoreLedger();
  assert.equal(reopened.input.value,'第一句\n第二句');assert.equal(reopened.ctx.ledger.snapshot().queued.length,0);assert.equal(calls,0);
  const again=setup(async()=>{calls++},env.store);again.ctx.restoreLedger();assert.equal(again.input.value,'第一句\n第二句');assert.equal(calls,0);
 });
 test(`${label}: enqueue storage failure preserves input and does not send or cancel`,async()=>{
  let calls=0;const store=storage(),env=setup(async()=>{calls++},store);store.fail=true;
  env.input.value='不能丢掉';env.ctx.send(env.input.value);await env.flush();
  assert.equal(env.input.value,'不能丢掉');assert.equal(calls,0);assert.equal(env.ctx.ledger.snapshot().queued.length,0);assert.match(env.toasts[0],/无法保存/);
 });
 test(`${label}: storage failure when claiming queued text makes no POST and restores editable text`,async()=>{
  let calls=0;const env=setup(async()=>{calls++});env.input.value='发送前落盘';env.ctx.send(env.input.value);
  env.store.fail=true;await env.flush();assert.equal(calls,0);assert.equal(env.input.value,'发送前落盘');
  assert.equal(env.ctx.ledger.snapshot().pending.length,0);
  env.store.fail=false;const again=setup(async()=>{calls++},env.store);again.ctx.restoreLedger();assert.equal(again.input.value,'发送前落盘');assert.equal(calls,0);
 });
 for(const cancelled of [false,true]) test(`${label}: unknown reload reconciles ${cancelled?'cancelled':'completed'} with exact ID by GET only`,async()=>{
  let posts=0;const env=setup(async(path)=>{if(path==='/api/chat')posts++;throw Error('offline')});
  env.input.value='合成原话';env.ctx.send(env.input.value);await env.flush();
  assert.equal(posts,1);const saved=env.ctx.ledger.snapshot().pending[0];assert.ok(saved.request_id);assert.equal(saved.memory_proposals,true);assert.equal(saved.text,'合成原话');assert.equal(saved.session_id,env.state.session.id);
  const calls=[],again=setup(async(path,opts)=>{calls.push({path,opts});return{status:cancelled?'cancelled':'completed',result:result(cancelled)}},env.store,false);
  again.ctx.restoreLedger();assert.equal(calls.length,0);assert.equal(again.ctx.blocked.size,1);
  assert.match(again.$(mobile?'#m-chat-error':'#chat-error').textContent,/只读取结果/);
  await again.ctx.recover();assert.equal(calls.length,1);assert.equal(calls[0].opts,undefined);assert.match(calls[0].path,new RegExp(saved.request_id));
  assert.equal(again.ctx.ledger.snapshot().pending.length,0);assert.equal(again.ctx.blocked.size,0);assert.equal(posts,1);
 });
 for(const code of ['process_interrupted','execution_uncertain']) test(`${label}: ${code} restores original plus unsent queue and draft, never auto submits`,async()=>{
  const env=setup(async()=>{throw Error('offline')});env.input.value='合成原话';env.ctx.send(env.input.value);await env.flush();
  const queued={id:'local-unsubmitted',sessionId:env.state.session.id,text:'排队补充',role:'user'};env.ctx.ledger.enqueue(queued);env.ctx.ledger.saveDraft(env.state.session.id,'正在写');
  const calls=[],again=setup(async(path,opts)=>{calls.push({path,opts});return path.startsWith('/api/chat/turn/')?{status:'unknown',error_code:code}:{messages:[{id:'persisted-user',role:'user',text:'合成原话'}],memories:[]}},env.store);
  again.ctx.restoreLedger();assert.equal(again.input.value,'排队补充\n正在写');await again.ctx.recover();
  assert.equal(again.input.value,'合成原话\n排队补充\n正在写');assert.equal(calls.length,2);assert.ok(calls.every(c=>!c.opts));
  assert.equal(again.ctx.ledger.snapshot().pending.length,0);assert.equal(again.ctx.blocked.size,0);
  const third=setup(async()=>assert.fail('no automatic request'),env.store);third.ctx.restoreLedger();assert.equal(third.input.value,again.input.value);
  assert.match(again.$(mobile?'#m-chat-error':'#chat-error').textContent,/没有自动重发/);
 });
 test(`${label}: a sent cancellation is not an acknowledgement and reload never POSTs cancel`,async()=>{
  const env=setup(async()=>{throw Error('offline')});env.input.value='合成原话';env.ctx.send(env.input.value);await env.flush();
  const pending=[...env.ctx.blocked.values()][0];await env.ctx.transport.cancel(pending.transport);
  assert.equal(env.ctx.ledger.snapshot().pending[0].cancelWanted,true);
  const calls=[],again=setup(async(path,opts)=>{calls.push({path,opts});return{status:'completed',result:result(false)}},env.store);
  again.ctx.restoreLedger();await again.ctx.recover();assert.equal(calls.length,1);assert.equal(calls[0].opts,undefined);
  assert.equal(again.ctx.ledger.snapshot().pending.length,0);assert.equal(again.state.messages[0].id,'user-saved');
 });
 test(`${label}: ordinary draft is saved in ledger and survives a new VM`,()=>{
  const env=setup(async()=>{});env.ctx.restoreLedger();env.input.value='普通草稿';env.ctx.keepDraft();
  const again=setup(async()=>assert.fail('must not request'),env.store);again.ctx.restoreLedger();assert.equal(again.input.value,'普通草稿');
 });
 test(`${label}: initial HTTP429 returns queued words to a durable draft and releases only that request`,async()=>{
  let posts=0;const env=setup(async()=>{posts++;const e=Error('预算不足');e.status=429;throw e});
  env.input.value='未接受的文字';env.ctx.send(env.input.value);await env.flush();
  assert.equal(posts,1);assert.equal(env.input.value,'未接受的文字');assert.equal(env.ctx.ledger.snapshot().pending.length,0);assert.equal(env.ctx.ledger.snapshot().queued.length,0);
  const again=setup(async()=>assert.fail('no retry'),env.store);again.ctx.restoreLedger();assert.equal(again.input.value,'未接受的文字');
 });
 test(`${label}: failure to clear a completed request preserves its ID for a later GET rather than claiming unsent`,async()=>{
  const store=storage();let posts=0;const env=setup(async()=>{posts++;store.fail=true;return result(false)},store);
  env.input.value='合成原话';env.ctx.send(env.input.value);await env.flush();assert.equal(posts,1);assert.equal(env.ctx.ledger.snapshot().pending.length,1);assert.equal(env.ctx.blocked.size,1);
  assert.equal(env.input.value,'');store.fail=false;
  const calls=[],again=setup(async(path,opts)=>{calls.push({path,opts});return{status:'completed',result:result(false)}},store);again.ctx.restoreLedger();await again.ctx.recover();
  assert.equal(calls.length,1);assert.equal(calls[0].opts,undefined);assert.equal(again.ctx.ledger.snapshot().pending.length,0);
 });
 test(`${label}: an unreadable existing ledger is preserved and fails closed`,()=>{
  const store=storage(),key='xinji_chat_ledger_v1_'+(mobile?'h5':'web');store.setItem(key,'{broken-json');let calls=0;
  const env=setup(async()=>{calls++},store);env.input.value='保留草稿';env.ctx.restoreLedger();env.ctx.send(env.input.value);
  assert.equal(env.input.value,'保留草稿');assert.equal(calls,0);assert.equal(store.getItem(key),'{broken-json');
 });
}
