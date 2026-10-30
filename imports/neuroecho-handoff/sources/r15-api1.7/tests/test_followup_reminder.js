const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const caps={features:{companion_boundaries:true,bounded_followup_contact:true,unified_contact_claim:true}};
function harness({hidden=false,store=new Map(),override,supported=true}={}){
 let sid='one',item={id:'f',session_id:'one',due_at:new Date(Date.now()-1000).toISOString(),contact_expires_at:new Date(Date.now()+1800000).toISOString(),status:'pending',due:true,available:true,paused:false,quiet:false,allow_contact:true,contact_eligible:true,contact_reason:null,boundary_revision:0,content:'<原话，只当文本>'};
 const calls=[],created=[],notices=[],events={},timers=new Set();let invalidate;
 function node(){return {children:[],removed:false,textContent:'',setAttribute(){},append(...a){this.children.push(...a)},remove(){this.removed=true}}}
 function listen(k,fn){(events[k]||=[]).push(fn)}function remove(k,fn){events[k]=(events[k]||[]).filter(f=>f!==fn)}
 const document={hidden,body:{append(n){created.push(n)}},createElement:node,addEventListener:listen,removeEventListener:remove};
 const window={addEventListener:listen,removeEventListener:remove,XinjiCompanionBoundary:{subscribe(fn){invalidate=fn;return()=>{invalidate=null}}}};
 function Notification(title,options){this.title=title;this.options=options;this.closed=false;this.close=()=>{this.closed=true};notices.push(this)}Notification.permission='granted';
 const ctx={window,document,Notification,localStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)},setInterval:fn=>(timers.add(fn),fn),clearInterval:fn=>timers.delete(fn),setTimeout:fn=>(timers.add(fn),fn),clearTimeout:fn=>timers.delete(fn),Date,JSON,Map,Set,Number,encodeURIComponent};ctx.globalThis=ctx;
 for(const file of ['contact-contract.js','proactive-contact.js','followups.js'])vm.runInNewContext(fs.readFileSync('web/'+file,'utf8'),ctx);
 let claim;
 const api=async(path,options)=>{calls.push({path,options});if(override){const value=await override(path,options,item);if(value!==undefined)return value;}
  if(path==='/api/capabilities')return supported?caps:{features:{}};
  if(path.startsWith('/api/companion-boundary?'))return {revision:0,suppression_revision:0,mode:'active',until:null,time_zone:'UTC'};
  if(path.startsWith('/api/followups?'))return {followups:[item]};
  if(path.startsWith('/api/followup-notification-settings?'))return {enabled:true,revision:0};
  if(path.endsWith('/claim'))return claim={claimed:true,claim_id:'claim',reason:null,followup_id:item.id,occurrence_at:item.due_at,channel:JSON.parse(options.body).channel,expires_at:new Date(Date.now()+60000).toISOString()};
  if(path.endsWith('/recheck'))return {...claim,allowed:true};
  if(path.endsWith('/finish'))return {state:'submitted',claim_id:'claim',channel:claim.channel};
  throw Error('unexpected '+path);
 };
 const widget=window.XinjiFollowups.startReminder({api,getSessionId:()=>sid});
 return {widget,document,calls,created,notices,store,timers,get item(){return item},setItem:value=>{item={...item,...value}},setSid:value=>sid=value,invalidate:()=>invalidate?.(),emit:(key,value={})=>(events[key]||[]).forEach(fn=>fn(value))};
}
const posts=h=>h.calls.filter(c=>c.options?.method==='POST');
test('an opted-in eligible foreground item claims and rechecks before one safe banner; dismissal never completes it',async()=>{
 const h=harness();await flush();assert.equal(h.created.length,1);assert.equal(h.created[0].children[1].textContent,h.item.content);
 assert.deepEqual(posts(h).map(c=>c.path.split('/').pop()),['claim','recheck','finish']);assert.equal(JSON.parse(posts(h)[0].options.body).channel,'in_app');
 h.created[0].children[3].onclick();assert.equal(h.created[0].removed,true);await h.widget.refresh();assert.equal(h.created.length,1);assert.equal(posts(h).length,3);h.widget.stop();
});
test('legacy, not permitted, expired, quiet and paused items remain passive without a claim',async()=>{
 for(const patch of [{allow_contact:false},{contact_eligible:false},{contact_expires_at:new Date(Date.now()-1).toISOString()},{quiet:true},{paused:true},{boundary_revision:1}]){
  const h=harness({override:async(path,options,item)=>path.startsWith('/api/followups?')?{followups:[{...item,...patch}]}:undefined});await flush();await h.widget.refresh();assert.equal(h.created.length,0);assert.equal(posts(h).length,0);h.widget.stop();
 }
});
test('missing capability and paused global boundary never present or claim',async()=>{
 for(const options of [{supported:false},{override:async path=>path.startsWith('/api/companion-boundary?')?{revision:1,suppression_revision:1,mode:'paused',until:null,time_zone:'UTC'}:undefined}]){
  const h=harness(options);await flush();assert.equal(h.created.length,0);assert.equal(posts(h).length,0);h.widget.stop();
 }
});
test('false or unknown claim is durably consumed locally and is not retried on refresh or renderer restart',async()=>{
 for(const reply of [{claimed:false,reason:'cooldown'},{},null]){
  const store=new Map(),override=async path=>path.endsWith('/claim')?reply:undefined;
  const h=harness({store,override});await flush();await h.widget.refresh();assert.equal(h.created.length,0);assert.equal(posts(h).length,1);const original=h.item;h.widget.stop();
  const again=harness({store,override:async(path,options,item)=>{if(path.startsWith('/api/followups?'))return {followups:[original]};return override(path,options,item)}});await flush();assert.equal(posts(again).length,0);again.widget.stop();
 }
});
test('a late recheck is ignored after control invalidation, visibility change or another conversation',async()=>{
 for(const action of [h=>h.invalidate(),h=>{h.document.hidden=true;h.emit('visibilitychange')},h=>h.setSid('another')]){
  let release;const h=harness({override:async path=>path.endsWith('/recheck')?new Promise(resolve=>release=resolve):undefined});await flush();action(h);release({allowed:true});await flush();assert.equal(h.created.length,0);assert.equal(h.notices.length,0);h.widget.stop();
 }
});
test('stale, expired or mismatched recheck metadata cannot present',async()=>{
 for(const check of [{allowed:false},{allowed:true,claim_id:'wrong'},{allowed:true,claim_id:'claim',followup_id:'f',channel:'in_app',occurrence_at:'bad',expires_at:new Date(Date.now()-1).toISOString()}]){
  const h=harness({override:async path=>path.endsWith('/recheck')?check:undefined});await flush();assert.equal(h.created.length,0);await h.widget.refresh();assert.equal(posts(h).filter(c=>c.path.endsWith('/claim')).length,1);h.widget.stop();
 }
});
test('hidden browser submits generic silent OS call via the same atomic system channel and closes it on control change',async()=>{
 const h=harness({hidden:true});await flush();assert.equal(h.notices.length,1);assert.equal(h.notices[0].options.silent,true);assert.ok(!JSON.stringify(h.notices[0].options).includes(h.item.content));
 assert.equal(JSON.parse(posts(h)[0].options.body).channel,'system');h.invalidate();assert.equal(h.notices[0].closed,true);await h.widget.refresh();assert.equal(h.notices.length,1);h.widget.stop();
});
test('pagehide clears visible UI and does not claim read or task completion',async()=>{
 const h=harness();await flush();h.emit('pagehide',{persisted:false});assert.equal(h.created[0].removed,true);assert.equal(h.timers.size,0);assert.equal(posts(h).some(c=>c.path.endsWith('/transition')),false);
});
test('two independent foreground/OS clients share one server opportunity',async()=>{
 let claimed=false;const shared=async(path)=>{if(path.endsWith('/claim')){if(claimed)return {claimed:false,reason:'topic_window_claimed'};claimed=true;}return undefined;};
 const a=harness({override:shared}),b=harness({hidden:true,override:shared});await flush();assert.equal(a.created.length+b.notices.length,1);a.widget.stop();b.widget.stop();
});

test('another client changing notification settings closes an active banner without reviving or retrying its permission',async()=>{
 let revision=0;const h=harness({override:async path=>path.startsWith('/api/followup-notification-settings?')?{enabled:true,revision}:undefined});await flush();assert.equal(h.created.length,1);
 revision=1;await h.widget.refresh();assert.equal(h.created[0].removed,true);assert.equal(h.created.length,1);assert.equal(posts(h).filter(c=>c.path.endsWith('/claim')).length,1);h.widget.stop();
});
