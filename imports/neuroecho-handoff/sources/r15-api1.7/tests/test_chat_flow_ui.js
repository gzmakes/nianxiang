// Real shipped dispatch/recovery functions with fake transport and synthetic conversations.
const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
function cut(src,a,b){const i=src.indexOf(a),j=src.indexOf(b,i);assert.ok(i>=0&&j>i);return src.slice(i,j)}
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}}
function element(){const hidden=new Set();return{value:'',textContent:'',disabled:false,style:{},classList:{add:x=>hidden.add(x),remove:x=>hidden.delete(x),contains:x=>hidden.has(x)},focus(){},remove(){},replaceChildren(){}}}
for(const mobile of [false,true]){
 const label=mobile?'mobile':'desktop',src=fs.readFileSync(mobile?'web/m.js':'web/app.js','utf8');
 function setup(send,api=async()=>({})){
  const nodes=new Map(),events={},$=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)};
  const input=$(mobile?'#m-input':'#input'),state={session:{id:'old'},messages:[],memories:[]},blocked=new Map(),toasts=[];
  const transport={send,recover:send,cancel:async()=>({}),requestId:()=> 'fixture-new-turn'};
  const ledger={enqueue(){},returnDraft(){},saveDraft(){}};
  const ctx=vm.createContext({$,state,api,uncertainTurns:blocked,mUncertainTurns:blocked,chatTransport:transport,mChatTransport:transport,
   memoryProposal:{shouldRequest:()=>false,offer(){}},delivery:{pending:()=>false,stop(){},schedule(){}},els:{input,messages:{insertAdjacentHTML(){}}},document:{createTextNode:s=>s,addEventListener:(name,fn)=>events[name]=fn},
   toast:s=>toasts.push(s),setOrb(){},chatScroll:{render:fn=>fn()},renderMessages(){},renderAll(){},loadAudit(){},loadNextStep(){},touchLastSeen(){},
   window:{},chatLedger:ledger,mChatLedger:ledger,setTimeout(){},clearTimeout(){},Date,Map,Set,encodeURIComponent});
  const declarations=mobile?'let mQueuedTurns=[],mTurnQueue=[],mActiveTurn=null,mChatBlocked=false,mChatStorageBlocked=false,mTurnTimer=null,mLocalTurnId=0;const mDisplayedTurns=new Map();':'let queuedTurns=[],turnQueue=[],activeTurn=null,chatBlocked=false,chatStorageBlocked=false,turnTimer=null,localTurnId=0;const displayedTurns=new Map();';
  const code=mobile?cut(src,'  async function recoverMobileChat()', '  function setupVoice()')+cut(src,'  let mobilePetChatSession', '  // ---------- boot ----------')
   :cut(src,'  let petChatSession', '  function showMemoryContextNotice()');
  const queue=mobile?'mQueuedTurns':'queuedTurns',local=mobile?'mTurnQueue':'turnQueue';
  vm.runInContext(declarations+code+`\nthis.run=${mobile?'dispatchSend':'dispatchTurn'};this.recover=${mobile?'recoverMobileChat':'recoverChat'};this.send=${mobile?'send':'sendMessage'};this.seed=a=>${queue}=a;this.queues=()=>${queue};this.local=()=>${local};`,ctx);
  return{ctx,state,blocked,input,$,toasts,events};
 }
 function part(sid,text){return{id:'local-'+text,role:'user',text,sessionId:sid}}
 function turn(sid,text){return{sessionId:sid,parts:[part(sid,text)],transport:{session_id:sid,text,request_id:'fixture-'+text}}}
 test(`${label}: an uncertain conversation keeps its queued draft while another conversation can send`,async()=>{
  const calls=[];const env=setup(async t=>{calls.push(t.session_id);if(t.session_id==='old'){const e=Error('unknown');e.uncertain=true;throw e}return{messages:[{id:'saved-new',role:'user',text:'新会话内容'}],memories:[],user_message_id:'saved-new',state:'responding'}});
  env.state.session={id:'new'};env.state.messages=[part('new','新会话内容')];env.input.value='尚未发送的草稿';
  env.ctx.seed([turn('old','旧条'),turn('old','旧待发'),turn('new','新条')]);
  await env.ctx.run();await new Promise(setImmediate);
  assert.deepEqual(calls,['old','new']);assert.equal(env.blocked.has('old'),true);
  assert.equal(env.ctx.queues().length,1);assert.equal(env.ctx.queues()[0].parts[0].text,'旧待发');
  assert.equal(env.state.session.id,'new');assert.equal(env.state.messages[0].id,'saved-new');assert.equal(env.input.value,'尚未发送的草稿');
  env.state.session={id:'old'};env.ctx.send('新补充');assert.equal(env.input.value,'尚未发送的草稿');assert.equal(env.ctx.local().length,0);
 });
 test(`${label}: recovering an old conversation cannot overwrite a newly selected conversation`,async()=>{
  const d=deferred(),env=setup(()=>d.promise);env.blocked.set('old',turn('old','原话'));
  const pending=env.ctx.recover();env.state.session={id:'new'};env.state.messages=[{text:'新会话'}];env.state.memories=[{text:'新记忆'}];
  d.resolve({messages:[{text:'旧回复'}],memories:[{text:'旧记忆'}]});await pending;
  assert.equal(env.state.messages[0].text,'新会话');assert.equal(env.state.memories[0].text,'新记忆');assert.equal(env.blocked.has('old'),true);
 });
 test(`${label}: restart reconciliation preserves the new conversation and its unsent input`,async()=>{
  const d=deferred();let snapshotRequested=false;const env=setup(async()=>{const e=Error('restarted');e.uncertain=true;e.code='process_interrupted';throw e},async()=>{snapshotRequested=true;return d.promise});
  env.blocked.set('old',turn('old','原话'));const pending=env.ctx.recover();await new Promise(setImmediate);assert.equal(snapshotRequested,true);
  env.state.session={id:'new'};env.state.messages=[{text:'新会话'}];env.input.value='新会话草稿';d.resolve({messages:[{text:'旧原话'}],memories:[]});await pending;
  assert.equal(env.state.messages[0].text,'新会话');assert.equal(env.input.value,'新会话草稿');assert.equal(env.blocked.has('old'),true);
 });
 test(`${label}: execution uncertainty reconciles records without inventing a restart or resending the original`,async()=>{
  let sends=0,reads=0;const env=setup(async()=>{sends++;const e=Error('uncertain');e.uncertain=true;e.code='execution_uncertain';throw e},async()=>{reads++;return{messages:[{id:'previous',role:'user',text:'已保存的原话'}],memories:[]}});
  env.blocked.set('old',turn('old','原话'));env.input.value='正在写的草稿';await env.ctx.recover();
  assert.equal(sends,1);assert.equal(reads,1);assert.equal(env.state.messages[0].id,'previous');
  assert.equal(env.input.value,'原话\n正在写的草稿');assert.equal(env.blocked.has('old'),false);
  const note=env.$(mobile?'#m-chat-error':'#chat-error').textContent;
  assert.doesNotMatch(note,/服务已重启/);assert.match(note,/没有自动重发/);
 });
 test(`${label}: a confirmed reconciliation consumes the old request once and preserves queued user input`,async()=>{
  const original=turn('old','原话'),env=setup(async t=>{assert.equal(t,original.transport);return{messages:[{id:'saved',role:'user',text:'原话'}],memories:[]}});
  env.blocked.set('old',original);env.ctx.seed([turn('blocked','待发')]);env.blocked.set('blocked',turn('blocked','未知'));env.input.value='输入框草稿';
  await env.ctx.recover();assert.equal(env.blocked.has('old'),false);assert.equal(env.state.messages[0].text,'原话');assert.equal(env.ctx.queues()[0].parts[0].text,'待发');assert.equal(env.input.value,'输入框草稿');
 });
 test(`${label}: sending a suggested topic preserves the unsent composer draft`,()=>{
  const env=setup(async()=>({})),writes=[];
  env.ctx.window.XinjiComposerDraft={save:()=>writes.push(env.input.value)};
  env.input.value='我还没写完的草稿';env.input.style.height='88px';
  if(mobile) env.ctx.send('聊聊海报',{preserveDraft:true});
  else env.ctx.send('聊聊海报',false,{preserveDraft:true});
  assert.equal(env.input.value,'我还没写完的草稿');assert.equal(env.input.style.height,'88px');
  assert.equal(env.state.messages.at(-1).text,'聊聊海报');assert.equal(env.ctx.local().at(-1).text,'聊聊海报');
  assert.deepEqual(writes,[]);
 });
 test(`${label}: only an enqueued chat can request task recording and failure is surfaced without stopping chat`,async()=>{
  const env=setup(async()=>({})),recorded=[];
  env.ctx.window.XinjiPersonalTasks={record:part=>{recorded.push(part);return Promise.reject(Error('storage'));}};
  env.input.value='我要创建任务：整理';env.ctx.send(env.input.value);await new Promise(setImmediate);
  assert.equal(recorded.length,1);assert.equal(recorded[0].text,'我要创建任务：整理');
  assert.equal(env.state.messages.length,1);assert.equal(env.input.value,'');assert.ok(env.toasts.some(note=>/任务未保存/.test(note)));
  const rejected=setup(async()=>({})),calls=[];
  rejected.ctx.window.XinjiPersonalTasks={record:part=>{calls.push(part);return Promise.resolve(true)}};
  rejected.ctx[mobile?'mChatLedger':'chatLedger'].enqueue=()=>{throw Error('queue failed')};
  rejected.input.value='我要创建任务：保留';rejected.ctx.send(rejected.input.value);await new Promise(setImmediate);
  assert.equal(calls.length,0);assert.equal(rejected.input.value,'我要创建任务：保留');assert.equal(rejected.state.messages.length,0);
 });

 for (const scenario of [
  {name:'completed reply', result:{messages:[{id:'reply',role:'assistant',text:'你好'}],memories:[]}, expected:['success']},
  {name:'server failure', result:{messages:[],memories:[],state:'failed',error:'failed'}, expected:['error']},
  {name:'cancelled request', result:{messages:[],memories:[],cancelled:true}, expected:[]},
  {name:'delayed or absent reply', result:{messages:[{id:'pending',role:'assistant',delivery_pending:true}],memories:[]}, expected:[]},
  {name:'transport status unknown', reject:Object.assign(Error('uncertain'),{uncertain:true}), expected:[]},
  {name:'message not sent', reject:Object.assign(Error('not sent'),{notSent:true}), expected:['error']},
 ]) test(`${label}: pet reflects only the known ${scenario.name}`,async()=>{
  const env=setup(async()=>{if(scenario.reject)throw scenario.reject;return scenario.result}),actual=[];
  env.ctx.window.NianxiangPet={setWork:status=>actual.push(status)};
  env.ctx.seed([turn('old','问候')]);
  await env.ctx.run();await new Promise(setImmediate);
  assert.deepEqual(actual,scenario.expected);
 });

 test(`${label}: a previous pet result cannot replace a new active turn`,async()=>{
  const second=deferred();let calls=0;
  const env=setup(async()=>++calls===1?{messages:[{id:'reply',role:'assistant',text:'你好'}],memories:[]}:second.promise),actual=[];
  env.ctx.window.NianxiangPet={setWork:status=>actual.push(status)};
  env.ctx.seed([turn('old','第一条'),turn('old','第二条')]);
  await env.ctx.run();await new Promise(setImmediate);assert.deepEqual(actual,[]);
  second.resolve({messages:[],memories:[],cancelled:true});await new Promise(setImmediate);
  assert.deepEqual(actual,[]);
 });

 test(`${label}: only an explicitly requested pet conversation shows that turn's actual reply`,async()=>{
  const env=setup(async()=>({messages:[{id:'reply',role:'assistant',text:'真实回复内容'}],memories:[]})),said=[];
  env.ctx.window.NianxiangPet={setWork(){},showReply:(...args)=>said.push(args)};
  env.events['xinji-pet-chat-request']({detail:{requestId:1}});env.input.value='你好';env.ctx.send('你好');
  const part=env.ctx.local()[0];env.ctx.seed([{sessionId:'old',parts:[part],transport:{session_id:'old',text:'你好'}}]);
  await env.ctx.run();await new Promise(setImmediate);
  assert.equal(said.length,1);assert.equal(said[0][0],'真实回复内容');assert.equal(said[0][1],1);assert.equal(said[0][2](),true);
  env.state.messages=[];env.ctx.seed([turn('old','普通消息')]);
  await env.ctx.run();await new Promise(setImmediate);assert.equal(said.length,1);assert.equal(said[0][2](),false);
 });

 test(`${label}: pet conversation cannot leak a reply after switching sessions`,async()=>{
  const deferredReply=deferred(),env=setup(()=>deferredReply.promise),said=[];
  env.ctx.window.NianxiangPet={setWork(){},showReply:text=>said.push(text)};
  env.events['xinji-pet-chat-request']({detail:{requestId:1}});env.input.value='你好';env.ctx.send('你好');
  const part=env.ctx.local()[0];env.ctx.seed([{sessionId:'old',parts:[part],transport:{session_id:'old',text:'你好'}}]);
  const pending=env.ctx.run();env.state.session={id:'new'};
  deferredReply.resolve({messages:[{id:'reply',role:'assistant',text:'旧会话回复'}],memories:[]});
  await pending;await new Promise(setImmediate);assert.deepEqual(said,[]);
 });

 test(`${label}: cancelled or uncertain pet chat clears only its own request`,async()=>{
  const env=setup(async()=>({messages:[],memories:[],cancelled:true})),cancelled=[];
  env.ctx.window.NianxiangPet={setWork(){},cancelConversation:id=>cancelled.push(id)};
  env.events['xinji-pet-chat-request']({detail:{requestId:7}});env.input.value='你好';env.ctx.send('你好');
  const part=env.ctx.local()[0];env.ctx.seed([{sessionId:'old',parts:[part],transport:{session_id:'old',text:'你好'}}]);
  await env.ctx.run();await new Promise(setImmediate);assert.deepEqual(cancelled,[7]);
 });

 test(`${label}: typing during an active turn does not clear thinking presence`,()=>{
  const marker=mobile?'$("#m-input").addEventListener("input", () => {':'els.input.addEventListener("input", () => {';
  const start=src.indexOf(marker),end=src.indexOf('    });',start);
  assert.ok(start>=0&&end>start);
  const input={value:'继续输入',addEventListener:(name,fn)=>{input.handler=fn}},presence=[];
  const context=vm.createContext({els:{input},$:()=>input,state:{session:{id:'old'}},
   document:{documentElement:{dataset:{presenceState:'thinking'}}},window:{XinjiMobilePresence:s=>presence.push(s)}});
  vm.runInContext(`let ${mobile?'mActiveTurn':'activeTurn'}={sessionId:'old'};`+src.slice(start,end+7)+`;this.endTurn=()=>${mobile?'mActiveTurn':'activeTurn'}=null;`,context);
  input.handler();
  assert.equal(context.document.documentElement.dataset.presenceState,'thinking');assert.deepEqual(presence,[]);
  context.endTurn();input.handler();
  if(mobile)assert.deepEqual(presence,['input']);else assert.equal(context.document.documentElement.dataset.presenceState,'input');
 });

}
