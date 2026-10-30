const test=require('node:test'), assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const code=fs.readFileSync('web/followups.js','utf8');
function element(){return {value:'',hidden:false,disabled:false,textContent:'',className:'',children:[],isConnected:true,
  append(...args){this.children.push(...args)},replaceChildren(...args){this.children=args},focus(){},querySelectorAll(){return []}};}
function makeHost(){const h=element(),elements=new Map();h.querySelector=s=>{if(!elements.has(s)) elements.set(s,element());return elements.get(s)};return h;}
function setup(api,savedStore,savedSessionStore,options={}){
 const listeners={},intervals=new Set(),store=savedStore||new Map(),sessionStore=savedSessionStore||store;let sid='one',random=0;
 const document={hidden:false,addEventListener:(k,v)=>listeners[k]=v,createElement:()=>element()};
 const context={window:{addEventListener:(k,v)=>listeners[k]=v},document,sessionStorage:{getItem:k=>sessionStore.get(k),setItem:(k,v)=>sessionStore.set(k,v)},localStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)},
   crypto:{randomUUID:()=>`request-${++random}`},setInterval:fn=>{intervals.add(fn);return fn},clearInterval:fn=>intervals.delete(fn),Map,Set,Date,JSON,encodeURIComponent,Number};context.globalThis=context;
 if(options.contact){vm.runInNewContext(fs.readFileSync('web/contact-contract.js','utf8'),context);const invoke=api;api=(path,opt)=>path==='/api/capabilities'?Promise.resolve({features:{companion_boundaries:true,bounded_followup_contact:true,unified_contact_claim:true}}):invoke(path,opt);}
 if(options.copy)context.window.EchoShared={copy:options.copy};
 vm.runInNewContext(code,context);const widget=context.window.XinjiFollowups.create({api,getSessionId:()=>sid});const h=makeHost();widget.mount(h);
 return {widget,h,store,intervals,listeners,setSid:x=>sid=x,getRandom:()=>random,document};
}
const empty={followups:[]};
const flush=()=>new Promise(r=>setImmediate(r));
function fill(h){h.querySelector('[data-f-open]').onclick();const content=h.querySelector('[data-f-content]'),time=h.querySelector('[data-f-time]');content.value='周五回看';time.value='2099-01-02T09:30';content.oninput({target:content});time.oninput({target:time})}
function submit(h){h.querySelector('[data-f-form]').onsubmit({preventDefault(){}})}
function receipt(body,status='pending',extra={}){return {...body,id:'f1',session_id:body.session_id,request_id:body.request_id,content:body.content,due_at:body.due_at,status,...extra};}
test('confirmation is required, double click is guarded and sends local time as UTC',async()=>{
 let resolve;const calls=[];const e=setup(async(path,opt)=>{calls.push([path,opt]);return opt?new Promise(r=>resolve=r):empty});await flush();fill(e.h);assert.equal(calls.filter(x=>x[1]).length,0);
 submit(e.h);submit(e.h);assert.equal(calls.filter(x=>x[1]).length,1);const body=JSON.parse(calls[1][1].body);assert.equal(body.confirmed,true);assert.equal(body.content,'周五回看');assert.equal(body.due_at,new Date('2099-01-02T09:30').toISOString());assert.equal(e.getRandom(),1);
 resolve(receipt(body));await flush();assert.equal(e.h.querySelector('[data-f-status]').textContent,'已保存，打开回响时可以看到。');
});
test('network uncertainty retains the original request and retry does not create a new ID',async()=>{
 const writes=[];let n=0;const e=setup(async(path,opt)=>{if(!opt)return empty;writes.push(JSON.parse(opt.body));if(++n===1)throw Error('断线');return receipt(writes.at(-1))});await flush();fill(e.h);submit(e.h);await flush();
 assert.match(e.h.querySelector('[data-f-status]').textContent,/结果尚未确认/);submit(e.h);await flush();assert.deepEqual(writes[0],writes[1]);assert.equal(e.getRandom(),1);
});
test('closing or switching prevents late responses painting on a later screen',async()=>{
 let resolve;const e=setup(()=>new Promise(r=>resolve=r));const old=e.h;e.widget.stop();e.setSid('two');const later=makeHost();e.widget.mount(later);resolve({followups:[{session_id:'one',status:'pending',content:'不应显示',due_at:'2099-01-01T00:00:00Z'}]});await flush();assert.equal(old.querySelector('[data-f-list]').children.length,0);
 e.widget.stop();assert.equal(e.intervals.size,0);
});
test('failed list shows error instead of an empty state; visibility restarts refresh',async()=>{
 let calls=0;const e=setup(async()=>{calls++;throw Error('网络不可用')});await flush();assert.match(e.h.querySelector('[data-f-list]').children[0].textContent,/未能读取跟进/);
 e.document.hidden=true;e.listeners.visibilitychange();assert.equal(e.intervals.size,0);e.document.hidden=false;e.listeners.visibilitychange();await flush();assert.equal(e.intervals.size,1);assert.equal(calls,2);
});
test('long user content is inserted as text and a completed item uses its existing id',async()=>{
 const calls=[];const evil='<img src=x onerror=alert(1)>';const e=setup(async(path,opt)=>{calls.push([path,opt]);return opt?{id:'f1',status:'done'}:{followups:[{id:'f1',session_id:'one',status:'pending',content:evil,due_at:'2099-01-01T00:00:00Z'}]}});await flush();
 const card=e.h.querySelector('[data-f-list]').children[0];assert.equal(card.children[1].textContent,evil);card.children[3].children[0].onclick();await flush();assert.equal(calls[1][0],'/api/followups/f1');assert.equal(JSON.parse(calls[1][1].body).status,'done');
});
test('a rejected request unlocks the preserved draft and allows correction',async()=>{
 let bad=true;const e=setup(async(path,opt)=>{if(!opt)return empty;if(bad){bad=false;const error=Error('时间无效');error.status=422;throw error}return receipt(JSON.parse(opt.body))});await flush();fill(e.h);submit(e.h);await flush();
 assert.equal(e.h.querySelector('[data-f-content]').disabled,false);assert.equal(e.h.querySelector('[data-f-content]').value,'周五回看');assert.match(e.h.querySelector('[data-f-status]').textContent,/未保存/);
 submit(e.h);await flush();assert.equal(e.getRandom(),2);
});
test('reopening during an in-flight save keeps the form locked and reconciles it on success',async()=>{
 let resolve,body;const e=setup(async(path,opt)=>{if(!opt)return empty;body=JSON.parse(opt.body);return new Promise(r=>resolve=r)});await flush();fill(e.h);submit(e.h);e.widget.stop();const next=makeHost();e.widget.mount(next);
 assert.equal(next.querySelector('[data-f-submit]').disabled,true);assert.equal(next.querySelector('[data-f-content]').disabled,true);
 resolve(receipt(body));await flush();assert.equal(next.querySelector('[data-f-submit]').disabled,false);assert.equal(next.querySelector('[data-f-form]').hidden,true);
});
test('a repeated completion click submits only once while its receipt is pending',async()=>{
 let resolve,count=0;const e=setup(async(path,opt)=>{if(!opt)return {followups:[{id:'f1',session_id:'one',status:'pending',content:'测试',due_at:'2099-01-01T00:00:00Z'}]};count++;return new Promise(r=>resolve=r)});await flush();const complete=e.h.querySelector('[data-f-list]').children[0].children[3].children[0];complete.onclick();complete.onclick();assert.equal(count,1);resolve({id:'f1',status:'done'});await flush();
});
test('a nonexistent local clock time in the spring DST transition is rejected without saving',async()=>{
 const previous=process.env.TZ;process.env.TZ='America/New_York';try {
  let writes=0;const e=setup(async(path,opt)=>{if(opt)writes++;return empty});await flush();
  e.h.querySelector('[data-f-open]').onclick();e.h.querySelector('[data-f-content]').oninput({target:{value:'测试夏令时'}});
  e.h.querySelector('[data-f-time]').oninput({target:{value:'2030-03-10T02:30'}});submit(e.h);
  assert.equal(writes,0);assert.match(e.h.querySelector('[data-f-status]').textContent,/本地时间不存在/);
 } finally { if(previous===undefined)delete process.env.TZ;else process.env.TZ=previous; }
});

for(const terminal of ['done','cancelled']) test(`timeout then 400 retains ID until exact GET ${terminal} receipt unlocks without a new POST`,async()=>{
 const writes=[];let serverRecord=null;
 const e=setup(async(path,opt)=>{
  if(!opt)return {followups:serverRecord?[serverRecord]:[]};
  writes.push(JSON.parse(opt.body));
  if(writes.length===1)throw Error('response lost after possible commit');
  const error=Error('later validation rejection');error.status=400;throw error;
 });await flush();fill(e.h);submit(e.h);await flush();submit(e.h);await flush();
 assert.equal(writes.length,2);assert.deepEqual(writes[0],writes[1]);assert.equal(e.getRandom(),1);
 assert.equal(e.h.querySelector('[data-f-content]').disabled,true);
 const pending=JSON.parse(e.store.get('xinji_followup_pending_v2_web'));assert.equal(pending[0][1].request.request_id,writes[0].request_id);
 serverRecord=receipt(writes[0],terminal,{due_at:writes[0].due_at.replace('.000Z','+00:00')});
 await e.widget.refresh();await flush();
 assert.equal(e.h.querySelector('[data-f-content]').disabled,false);assert.equal(e.h.querySelector('[data-f-form]').hidden,true);
 assert.match(e.h.querySelector('[data-f-status]').textContent,terminal==='done'?/已完成/:/已取消/);
 assert.deepEqual(JSON.parse(e.store.get('xinji_followup_pending_v2_web')),[]);assert.equal(writes.length,2);assert.equal(e.getRandom(),1);
});
test('GET requires exact request ID, content, time, session and known status before unlocking',async()=>{
 let body,serverRecord;const e=setup(async(path,opt)=>{if(!opt)return {followups:serverRecord?[serverRecord]:[]};body=JSON.parse(opt.body);throw Error('uncertain')});
 await flush();fill(e.h);submit(e.h);await flush();
 for(const patch of [{request_id:'different'},{content:'different'},{due_at:'2098-01-01T00:00:00Z'},{session_id:'another'},{status:'future-state'}]){
  serverRecord=receipt(body,'pending',patch);await e.widget.refresh();assert.equal(e.h.querySelector('[data-f-content]').disabled,true);
  assert.equal(JSON.parse(e.store.get('xinji_followup_pending_v2_web'))[0][1].request.request_id,body.request_id);
 }
 serverRecord=receipt(body);await e.widget.refresh();assert.equal(e.h.querySelector('[data-f-content]').disabled,false);
});
test('a restored uncertain request does not release its ID after a validation rejection',async()=>{
 let original;const first=setup(async(path,opt)=>{if(!opt)return empty;original=JSON.parse(opt.body);throw Error('lost reply')});
 await flush();fill(first.h);submit(first.h);await flush();first.widget.stop();
 const writes=[];const reopened=setup(async(path,opt)=>{if(!opt)return empty;writes.push(JSON.parse(opt.body));const error=Error('invalid now');error.status=422;throw error},first.store);
 await flush();submit(reopened.h);await flush();
 assert.deepEqual(writes,[original]);assert.equal(reopened.getRandom(),0);assert.equal(reopened.h.querySelector('[data-f-content]').disabled,true);
});
test('retry POST with a matching terminal receipt unlocks and displays its actual status',async()=>{
 let attempts=0,body;const e=setup(async(path,opt)=>{if(!opt)return empty;body=JSON.parse(opt.body);if(++attempts===1)throw Error('lost reply');return receipt(body,'cancelled')});
 await flush();fill(e.h);submit(e.h);await flush();submit(e.h);await flush();
 assert.equal(e.h.querySelector('[data-f-form]').hidden,true);assert.match(e.h.querySelector('[data-f-status]').textContent,/已取消/);assert.equal(e.getRandom(),1);
});
test('mismatched POST receipt never claims saved and preserves the pending request',async()=>{
 const e=setup(async(path,opt)=>opt?receipt(JSON.parse(opt.body),'pending',{content:'different'}):empty);
 await flush();fill(e.h);submit(e.h);await flush();
 assert.equal(e.h.querySelector('[data-f-content]').disabled,true);assert.equal(JSON.parse(e.store.get('xinji_followup_pending_v2_web')).length,1);
 assert.doesNotMatch(e.h.querySelector('[data-f-status]').textContent,/^已保存/);
});
test('a timeout followed by HTTP 400 keeps the original payload locked',async()=>{
 const writes=[];let attempt=0;const e=setup(async(path,opt)=>{if(!opt)return empty;writes.push(JSON.parse(opt.body));if(++attempt===1)throw Error('timeout');const error=Error('无效');error.status=400;throw error});await flush();fill(e.h);submit(e.h);await flush();submit(e.h);await flush();
 assert.deepEqual(writes[0],writes[1]);assert.deepEqual(Object.keys(writes[0]).sort(),['confirmed','content','due_at','quiet_end','quiet_start','repeat_rule','request_id','session_id','time_zone']);
 assert.equal(e.h.querySelector('[data-f-content]').disabled,true);assert.match(e.h.querySelector('[data-f-status]').textContent,/结果尚未确认/);assert.equal(e.getRandom(),1);
});
test('a page reload followed by HTTP 400 retains the first in-flight request',async()=>{
 const store=new Map(),writes=[];let firstResolve;
 const first=setup(async(path,opt)=>{if(!opt)return empty;writes.push(JSON.parse(opt.body));return new Promise(r=>firstResolve=r)},store);await flush();fill(first.h);submit(first.h);
 first.listeners.pagehide();const second=setup(async(path,opt)=>{if(!opt)return empty;writes.push(JSON.parse(opt.body));const error=Error('无效');error.status=400;throw error},store);await flush();submit(second.h);await flush();
 assert.deepEqual(writes[0],writes[1]);assert.equal(second.h.querySelector('[data-f-content]').disabled,true);assert.equal(second.getRandom(),0);assert.match(second.h.querySelector('[data-f-status]').textContent,/结果尚未确认/);
 firstResolve({id:'f1',session_id:'one',status:'pending'});await flush();
});
test('a first HTTP 400 unlocks the draft because no earlier attempt was uncertain',async()=>{
 const e=setup(async(path,opt)=>{if(!opt)return empty;const error=Error('请求不合法');error.status=400;throw error});await flush();fill(e.h);submit(e.h);await flush();
 assert.equal(e.h.querySelector('[data-f-content]').disabled,false);assert.equal(e.h.querySelector('[data-f-content]').value,'周五回看');assert.match(e.h.querySelector('[data-f-status]').textContent,/未保存/);
});
test('HTTP 429 marks the request uncertain and a later 422 keeps it locked',async()=>{
 let attempts=0;const e=setup(async(path,opt)=>{if(!opt)return empty;const error=Error('暂不可用');error.status=++attempts===1?429:422;throw error});await flush();fill(e.h);submit(e.h);await flush();submit(e.h);await flush();
 assert.equal(e.h.querySelector('[data-f-content]').disabled,true);assert.equal(e.getRandom(),1);
});
test('unavailable session storage prevents a request that could not be reconciled after reload',async()=>{
 const store=new Map();store.set=()=>{throw Error('storage disabled')};let writes=0;
 const e=setup(async(path,opt)=>{if(opt)writes++;return empty},store);await flush();fill(e.h);submit(e.h);await flush();
 assert.equal(writes,0);assert.equal(e.h.querySelector('[data-f-content]').value,'周五回看');assert.match(e.h.querySelector('[data-f-status]').textContent,/本地会话存储/);
});

test('daily schedule sends chosen quiet hours and reuses payload on retry',async()=>{
 let write;const e=setup(async(path,opt)=>{if(!opt)return empty;write=JSON.parse(opt.body);return {id:'f1',session_id:'one',status:'pending'}});await flush();fill(e.h);
 e.h.querySelector('[data-f-repeat]').onchange({target:{value:'daily'}});
 e.h.querySelector('[data-f-quiet-start]').oninput({target:{value:'22:00'}});
 e.h.querySelector('[data-f-quiet-end]').oninput({target:{value:'08:00'}});submit(e.h);await flush();
 assert.equal(write.repeat_rule,'daily');assert.equal(write.quiet_start,'22:00');assert.equal(write.quiet_end,'08:00');assert.ok(write.time_zone);
});
test('daily completion carries occurrence identifier for safe retry',async()=>{
 let change;const date='2026-10-30T02:00:00.000000+00:00';const item={id:'daily1',session_id:'one',status:'pending',content:'散步',repeat_rule:'daily',due_at:date,available:true};
 const e=setup(async(path,opt)=>{if(!opt)return {followups:[item]};change=JSON.parse(opt.body);return {id:'daily1',status:'pending',last_occurrence_at:date}});await flush();
 const card=e.h.querySelector('[data-f-list]').children[0];card.children[4].children[0].onclick();await flush();
 assert.equal(change.status,'done');assert.equal(change.occurrence_at,date);assert.match(e.h.querySelector('[data-f-status]').textContent,/下一次已安排/);
});
test('a conversation proposal fills a reviewable followup and requires explicit confirmation',async()=>{
 const writes=[];const e=setup(async(path,opt)=>{if(!opt)return empty;writes.push(JSON.parse(opt.body));return receipt(writes.at(-1))});await flush();
 assert.equal(e.widget.offer({kind:'reminder',title:'准备演示',detail:'核对演示重点',when:'2099-01-02T09:30'}),'ready');
 assert.equal(e.h.querySelector('[data-f-content]').value,'准备演示\n核对演示重点');
 assert.equal(e.h.querySelector('[data-f-time]').value,'2099-01-02T09:30');
 assert.equal(e.h.querySelector('[data-f-suggested]').hidden,false);assert.equal(writes.length,0);
 submit(e.h);await flush();assert.equal(writes.length,1);assert.equal(writes[0].confirmed,true);
 assert.equal(writes[0].content,'准备演示\n核对演示重点');assert.equal(writes[0].due_at,new Date('2099-01-02T09:30').toISOString());
 assert.match(e.h.querySelector('[data-f-status]').textContent,/已保存/);
});
test('invalid model time stays blank and no followup can be saved without user time',async()=>{
 let writes=0;const e=setup(async(path,opt)=>{if(opt)writes++;return empty});await flush();
 assert.equal(e.widget.offer({kind:'reminder',title:'散步',when:'明天大概'}),'ready');
 assert.equal(e.h.querySelector('[data-f-time]').value,'');submit(e.h);await flush();assert.equal(writes,0);
 assert.match(e.h.querySelector('[data-f-status]').textContent,/选择未来的时间/);
});
test('offering another suggestion never overwrites the existing unsaved draft',async()=>{
 const e=setup(async()=>empty);await flush();fill(e.h);
 assert.equal(e.widget.offer({kind:'reminder',title:'新建议',when:'2099-01-02T10:00'}),'draft');
 assert.equal(e.h.querySelector('[data-f-content]').value,'周五回看');assert.equal(e.h.querySelector('[data-f-time]').value,'2099-01-02T09:30');
});
test('a proposal can be offered before the Today view mounts and retains its review form',async()=>{
 const e=setup(async()=>empty);await flush();e.widget.stop();
 assert.equal(e.widget.offer({kind:'reminder',title:'复习',when:''}),'ready');
 const next=makeHost();e.widget.mount(next);assert.equal(next.querySelector('[data-f-form]').hidden,false);
 assert.equal(next.querySelector('[data-f-content]').value,'复习');assert.equal(next.querySelector('[data-f-time]').value,'');
});

test('full renderer close keeps the original request in persistent storage and accepts a moved daily receipt',async()=>{
 const persistent=new Map();let body;
 const first=setup(async(path,opt)=>{if(!opt)return empty;body=JSON.parse(opt.body);throw Error('lost after possible commit')},persistent,new Map());
 await flush();fill(first.h);first.h.querySelector('[data-f-repeat]').onchange({target:{value:'daily'}});submit(first.h);await flush();first.widget.stop();
 const later=new Date(new Date(body.due_at).getTime()+86400000).toISOString();let writes=0;
 const second=setup(async(path,opt)=>{if(opt){writes++;throw Error('must reconcile with GET');}return {followups:[receipt(body,'pending',{created_due_at:body.due_at,due_at:later})]};},persistent,new Map());
 await flush();assert.equal(writes,0);assert.equal(second.h.querySelector('[data-f-form]').hidden,true);assert.equal(second.h.querySelector('[data-f-content]').disabled,false);assert.deepEqual(JSON.parse(persistent.get('xinji_followup_pending_v2_web')),[]);
});

const activeBoundary={revision:0,suppression_revision:0,mode:'active',until:null,time_zone:'UTC'};
function consent(h){h.querySelector('[data-f-contact]').onchange({target:{checked:true}});h.querySelector('[data-f-window]').onchange({target:{value:'15'}});h.querySelector('[data-f-topic]').oninput({target:{value:'  只聊这件事  '}});}
test('new followup defaults to passive and uses shared consent copy at runtime',async()=>{
 const writes=[];const e=setup(async(path,opt)=>{if(!opt)return empty;const body=JSON.parse(opt.body);writes.push(body);return receipt(body)},undefined,undefined,{contact:true,copy:{'followup.contact.consent':'共享许可文案','followup.contact.default':'共享默认文案'}});await flush();fill(e.h);
 assert.equal(e.h.querySelector('[data-f-contact]').checked,false);assert.equal(e.h.querySelector('[data-f-contact-label]').textContent,'共享许可文案');assert.equal(e.h.querySelector('[data-f-contact-default]').textContent,'共享默认文案');
 submit(e.h);await flush();assert.equal(writes[0].allow_contact,false);assert.equal(writes[0].contact_window_minutes,30);assert.equal(writes[0].contact_topic,'周五回看');
});
test('explicit contact preflight freezes the reviewed topic/window and blocks double submission',async()=>{
 let release;const writes=[];const e=setup(async(path,opt)=>{if(path.startsWith('/api/companion-boundary?'))return new Promise(r=>release=r);if(!opt)return empty;const body=JSON.parse(opt.body);writes.push(body);return receipt(body)},undefined,undefined,{contact:true});await flush();fill(e.h);consent(e.h);submit(e.h);submit(e.h);
 assert.equal(writes.length,0);assert.equal(e.h.querySelector('[data-f-contact]').disabled,true);assert.equal(e.h.querySelector('[data-f-content]').disabled,true);release(activeBoundary);await flush();
 assert.equal(writes.length,1);assert.equal(writes[0].allow_contact,true);assert.equal(writes[0].contact_window_minutes,15);assert.equal(writes[0].contact_topic,'只聊这件事');assert.equal(e.getRandom(),1);
});
test('paused or unknown boundary keeps the full draft and makes no contact request',async()=>{
 for(const boundary of [{...activeBoundary,mode:'paused'},null]){let writes=0;const e=setup(async(path,opt)=>{if(path.startsWith('/api/companion-boundary?')){if(boundary===null)throw Error('lost read');return boundary}if(opt)writes++;return empty},undefined,undefined,{contact:true});await flush();fill(e.h);consent(e.h);submit(e.h);await flush();assert.equal(writes,0);assert.equal(e.getRandom(),0);assert.equal(e.h.querySelector('[data-f-content]').value,'周五回看');assert.equal(e.h.querySelector('[data-f-contact]').checked,true);assert.equal(e.h.querySelector('[data-f-content]').disabled,false);}
});
test('contact options must match the committed receipt before an uncertain draft can unlock',async()=>{
 let body,serverRecord;const e=setup(async(path,opt)=>{if(path.startsWith('/api/companion-boundary?'))return activeBoundary;if(!opt)return {followups:serverRecord?[serverRecord]:[]};body=JSON.parse(opt.body);throw Error('reply lost')},undefined,undefined,{contact:true});await flush();fill(e.h);consent(e.h);submit(e.h);await flush();
 for(const patch of [{allow_contact:false},{contact_window_minutes:30},{contact_topic:'其他话题'}]){serverRecord=receipt(body,'pending',patch);await e.widget.refresh();assert.equal(e.h.querySelector('[data-f-content]').disabled,true);}
 serverRecord=receipt(body);await e.widget.refresh();assert.equal(e.h.querySelector('[data-f-content]').disabled,false);
});
test('legacy pending replay keeps its original body without newly defaulted contact fields',async()=>{
 const original={session_id:'one',request_id:'legacy',content:'原待办',due_at:'2099-01-02T00:00:00Z',confirmed:true};const store=new Map([['xinji_followup_pending_v2_web',JSON.stringify([['one',{request:original,uncertain:true}]])]]),writes=[];
 const e=setup(async(path,opt)=>{if(!opt)return empty;writes.push(JSON.parse(opt.body));return receipt(writes[0])},store,undefined,{contact:true});await flush();submit(e.h);await flush();assert.deepEqual(writes,[original]);assert.equal(e.getRandom(),0);
});

test('followup dates use the item IANA zone across travel, with honest missing/invalid zone fallback',async()=>{
 const previous=process.env.TZ;process.env.TZ='Asia/Shanghai';try{
  const due_at='2026-10-30T12:00:00Z';
  for(const [time_zone,expected] of [['America/New_York','08:00'],['UTC','12:00'],[undefined,'原时区未提供'],['Invalid/zone','时区无效']]){const item={id:'zone',session_id:'one',status:'pending',content:'跨时区跟进',due_at,time_zone};const e=setup(async()=>({followups:[item]}));await flush();const text=e.h.querySelector('[data-f-list]').children[0].children.find(n=>n.className==='followup-time').textContent;assert.match(text,new RegExp(expected));if(time_zone==='America/New_York'){assert.match(text,/America\/New_York/);assert.doesNotMatch(text,/20:00/);}e.widget.stop();}
 }finally{if(previous===undefined)delete process.env.TZ;else process.env.TZ=previous;}
});
test('contact rows show literal topic and explain invalid, quiet and consumed permissions without a future promise',async()=>{
 for(const [reason,expected] of [['boundary_changed',/许可已失效，需重新约定/],['expired',/重新约定/],['quiet',/安静.*不会轻问/],['item_quiet',/安静.*不会轻问/],['item_paused',/已暂停，不会轻问/],['already_claimed',/不再重复/],['topic_window_claimed',/不再重复/],['not_due',/仍需符合当前许可/],['unknown',/当前不会主动轻问/]]){const item={id:'contact-row',session_id:'one',status:'pending',content:'事项内容',due_at:'2026-10-30T12:00:00Z',time_zone:'Asia/Shanghai',allow_contact:true,contact_reason:reason,contact_topic:'<指定话题，只当文本>'};const e=setup(async()=>({followups:[item]}));await flush();const children=e.h.querySelector('[data-f-list]').children[0].children;assert.equal(children.find(n=>n.className==='followup-contact-topic').textContent,'轻问话题：'+item.contact_topic);assert.match(children.find(n=>n.className==='followup-contact-status').textContent,expected);e.widget.stop();}
});
test('pause/resume success requires the exact Boolean receipt, never truthiness or omitted defaults',async()=>{
 for(const status of ['paused','resumed']){for(const value of [undefined,null,0,1,'false','true',{},[],status==='paused'?false:true]){const item={id:'pause-receipt',session_id:'one',status:'pending',content:'核对暂停',due_at:'2099-01-01T12:00:00Z',paused:status==='resumed'};const e=setup(async(path,opt)=>opt?{id:item.id,paused:value}:{followups:[item]});await flush();const actions=e.h.querySelector('[data-f-list]').children[0].children.find(n=>n.className==='followup-actions');await actions.children[1].onclick();await flush();assert.match(e.h.querySelector('[data-f-status]').textContent,/更新结果未确认/);assert.doesNotMatch(e.h.querySelector('[data-f-status]').textContent,/^已暂停|^已恢复/);e.widget.stop();}
 const item={id:'pause-valid',session_id:'one',status:'pending',content:'明确布尔',due_at:'2099-01-01T12:00:00Z',paused:status==='resumed'},e=setup(async(path,opt)=>opt?{id:item.id,paused:status==='paused'}:{followups:[item]});await flush();await e.h.querySelector('[data-f-list]').children[0].children.find(n=>n.className==='followup-actions').children[1].onclick();await flush();assert.match(e.h.querySelector('[data-f-status]').textContent,status==='paused'?/^已暂停/:/^已恢复/);e.widget.stop();}
});
