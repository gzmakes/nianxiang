const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('web/memory-proposal.js', 'utf8');
function node() { return {className:'',textContent:'',style:{},disabled:false,children:[],
  classList:{add(){},remove(){}},replaceChildren(...children){this.children=children}}; }
const quote = '我希望你先听我说';
function saved(extra={}) { return {id:'new-memory',text:quote,kind:'fact',status:'confirmed',
  source_message_id:'user-message',source:'对话原话 · 用户选存',created:true,...extra}; }
function setup(handler) {
  const box=node(),toggle=node(),state={session:{id:'s'},messages:Array.from({length:3},()=>({role:'user'})),memories:[]};
  const calls=[],toasts=[];let refreshes=0;
  const context={window:{},localStorage:{getItem(key){return key === "xinji_memory_proposals" ? "on" : null},setItem(){}},
    document:{createElement:()=>node()},Map,Set};
  vm.runInNewContext(source,context);
  const proposal=context.window.createMemoryProposal({box,toggle,state,
    api:async(path,options)=>{calls.push({path,options});return handler(path,options);},
    toast:text=>toasts.push(text),refresh(){refreshes++;}});
  function offer(message='user-message') {
    proposal.offer(state.session.id,{memory_proposal:{quote,message_id:message}});
    return box.children[3];
  }
  return {box,toggle,state,calls,toasts,proposal,offer,get refreshes(){return refreshes;}};
}

test('one clear click confirms exact quote and gives memory edit/delete route',async()=>{
  const s=setup(async()=>saved());const button=s.offer();
  assert.equal(button.textContent,'记住这句');
  assert.match(s.box.children[2].textContent,/记忆.*修改或删除/);
  await button.onclick();
  assert.equal(s.calls.length,1);
  assert.deepEqual(JSON.parse(s.calls[0].options.body),{session_id:'s',message_id:'user-message',confirm:true});
  assert.equal(s.state.memories[0].status,'confirmed');
  assert.equal(s.refreshes,1);assert.equal(s.box.children.length,0);
  assert.match(s.toasts[0],/已记住.*修改或删除/);
});

test('repeated clicks while save is running issue one POST',async()=>{
  let resolve;const s=setup(()=>new Promise(r=>{resolve=r}));const button=s.offer();
  const first=button.onclick();await button.onclick();assert.equal(s.calls.length,1);
  resolve(saved());await first;assert.equal(s.state.memories.length,1);
});

test('lost POST response reconciles exact confirmed source without POSTing again',async()=>{
  const s=setup(async path=>{if(path==='/api/memory/proposal')throw new Error('response lost');return {memories:[saved()]}});
  const button=s.offer();await button.onclick();
  assert.equal(s.calls.length,2);assert.equal(s.calls.filter(c=>c.options?.method==='POST').length,1);
  assert.equal(s.state.memories[0].status,'confirmed');assert.match(s.toasts[0],/已记住/);
});

test('unknown result is never reported as saved and never blindly retried',async()=>{
  const s=setup(async()=>{throw new Error('network unavailable')});const button=s.offer();
  await button.onclick();await button.onclick();
  assert.equal(s.calls.filter(c=>c.options?.method==='POST').length,1);
  assert.equal(s.state.memories.length,0);assert.equal(button.disabled,true);
  assert.match(s.box.children[2].textContent,/状态还不能确认/);
  assert.ok(s.toasts.every(t=>!t.startsWith('已记住')));
});

test('same text in unrelated provenance or candidate does not falsely reconcile',async()=>{
  const s=setup(async path=>{if(path==='/api/memory/proposal')throw new Error('lost');
    return {memories:[saved({source:'文档来源'}),saved({status:'candidate'}),saved({source_message_id:'different-message'})]};});
  await s.offer().onclick();assert.equal(s.state.memories.length,0);
  assert.match(s.toasts[0],/状态未知/);assert.equal(s.calls.length,2);
});

test('known validation error remains an explicit failed write',async()=>{
  const s=setup(async()=>{const error=new Error('来源不存在');error.status=409;throw error});
  const button=s.offer();await button.onclick();
  assert.equal(s.calls.length,1);assert.match(s.toasts[0],/^未保存：来源不存在/);
  assert.equal(s.state.memories.length,0);
});

test('old completion cannot clear a new session proposal or alter its memories',async()=>{
  let resolve;const s=setup(()=>new Promise(r=>{resolve=r}));const first=s.offer();
  const pending=first.onclick();s.state.session={id:'new-session'};s.proposal.sync();
  s.offer('new-user-message');const newQuote=s.box.children[1];
  resolve(saved());await pending;
  assert.equal(s.state.memories.length,0);assert.equal(s.box.children[1],newQuote);
  assert.equal(s.toasts.length,0);
});

test('existing confirmed response does not offer a delete action for an old memory',async()=>{
  const s=setup(async()=>saved({created:false}));await s.offer().onclick();
  assert.equal(s.calls.length,1);assert.ok(s.calls.every(c=>c.options?.method!=='DELETE'));
  assert.match(s.toasts[0],/记忆.*修改或删除/);
});
