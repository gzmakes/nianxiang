const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function harness({features=true,confirm=true,putError,readDelay}={}){
 const elements=new Map(),calls=[],prompts=[],timers=new Set(),listeners={};let sid='one',boundary={revision:0,suppression_revision:0,mode:'active',until:null,time_zone:'UTC'},invalidations=0;
 const host={querySelector(key){if(!elements.has(key))elements.set(key,{hidden:false,disabled:false,textContent:''});return elements.get(key)}};
 const document={hidden:false,addEventListener(k,f){listeners[k]=f},removeEventListener(k){delete listeners[k]}};
 const window={addEventListener(k,f){listeners[k]=f},removeEventListener(k){delete listeners[k]},XinjiDialogs:{confirm:async value=>{prompts.push(value);return confirm}},xinjiDesktop:{proactiveChanged(){invalidations++}}};
 const ctx={window,document,setInterval:f=>(timers.add(f),f),clearInterval:f=>timers.delete(f),Date,Intl,Set,Promise,Number,encodeURIComponent};
 for(const file of ['contact-contract.js','companion-boundary.js'])vm.runInNewContext(fs.readFileSync('web/'+file,'utf8'),ctx);
 const api=async(path,options)=>{calls.push({path,options});if(path==='/api/capabilities')return {features:features?{companion_boundaries:true,bounded_followup_contact:true,unified_contact_claim:true}:{}};
  if(options){if(putError)throw putError;const body=JSON.parse(options.body);assert.equal(body.confirmed,true);assert.equal(body.expected_revision,boundary.revision);boundary={...boundary,...body,revision:boundary.revision+1,suppression_revision:boundary.suppression_revision+1};return {...boundary};}
  return readDelay?readDelay():{...boundary};
 };
 const widget=window.XinjiCompanionBoundary.create({api,getSessionId:()=>sid,host});
 return {widget,host,calls,prompts,window,document,listeners,get invalidations(){return invalidations},setSid:value=>sid=value,timers};
}
const writes=h=>h.calls.filter(c=>c.options?.method==='PUT');
test('reading boundary is read-only and old capability gives an honest disabled control',async()=>{
 const h=harness({features:false});await h.widget.refresh();assert.equal(h.calls.length,1);assert.equal(h.host.querySelector('[data-b-today]').disabled,true);assert.match(h.host.querySelector('[data-b-copy]').textContent,/暂不支持/);assert.equal(writes(h).length,0);h.widget.stop();
});
test('today quiet confirms the exact CAS change and sends next local midnight with timezone',async()=>{
 const h=harness();await h.widget.refresh();await h.host.querySelector('[data-b-today]').onclick();assert.equal(h.prompts.length,1);const body=JSON.parse(writes(h)[0].options.body);assert.equal(body.mode,'until');assert.equal(body.confirmed,true);assert.equal(body.expected_revision,0);assert.equal(new Date(body.until).getHours(),0);assert.ok(Date.parse(body.until)>Date.now());assert.equal(body.time_zone,Intl.DateTimeFormat().resolvedOptions().timeZone);assert.match(h.prompts[0].message,/已有轻问许可会失效/);assert.match(h.host.querySelector('[data-b-copy]').textContent,/先安静到/);h.widget.stop();
});
test('pause and explicit resume preserve tasks and never promise to restore old permission',async()=>{
 const h=harness();await h.widget.refresh();await h.host.querySelector('[data-b-pause]').onclick();assert.equal(JSON.parse(writes(h)[0].options.body).mode,'paused');assert.equal(h.host.querySelector('[data-b-resume]').hidden,false);
 await h.host.querySelector('[data-b-resume]').onclick();const body=JSON.parse(writes(h)[1].options.body);assert.equal(body.mode,'active');assert.equal(body.until,null);assert.equal(body.expected_revision,1);assert.match(h.prompts[1].message,/旧许可不会恢复/);assert.ok(h.invalidations>=3);h.widget.stop();
});
test('cancel, conflict and unknown save do not automatically repeat PUT',async()=>{
 const cancelled=harness({confirm:false});await cancelled.widget.refresh();await cancelled.host.querySelector('[data-b-pause]').onclick();assert.equal(writes(cancelled).length,0);cancelled.widget.stop();
 for(const error of [Object.assign(Error('changed'),{status:409}),Error('lost')]){
  const h=harness({putError:error});await h.widget.refresh();await h.host.querySelector('[data-b-pause]').onclick();assert.equal(writes(h).length,1);assert.match(h.host.querySelector('[data-b-copy]').textContent,error.status===409?/没有覆盖/:/待核对/);await h.widget.refresh();assert.equal(writes(h).length,1);h.widget.stop();
 }
});
test('late boundary GET cannot paint a different conversation and hiding invalidates active presentations',async()=>{
 let release;const h=harness({readDelay:()=>new Promise(r=>release=r)});const loading=h.widget.refresh();await flush();h.setSid('other');release({revision:1,suppression_revision:1,mode:'paused',until:null,time_zone:'UTC'});await loading;assert.doesNotMatch(h.host.querySelector('[data-b-copy]').textContent,/先不主动问/);
 const before=h.invalidations;h.document.hidden=true;h.listeners.visibilitychange();assert.ok(h.invalidations>before);h.widget.stop();assert.equal(h.timers.size,0);
});
