// R14 read cursors never acknowledge writes or skip an unobserved change.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function receipt(cursor='c0',domains=['messages'],extra={}){return {service_instance_id:'test-service',conversation_id:'test-conversation',cursor,reset_required:cursor==='c0',domains,...extra};}
function fixture(overrides={}){
 const window={};vm.runInNewContext(fs.readFileSync('web/client-sync.js','utf8'),{window,AbortController,document:{hidden:false},setTimeout,clearTimeout});
 let id='test-conversation',version=0,editable=true,visible=true,now=10000;const calls=[],states=[],applied=[],timers=new Map();let seq=0;
 const options={api:async(path,opts)=>{calls.push({path,opts});if(path==='/api/capabilities')return{features:{conversation_change_cursor:true}};return path.includes('?after=')?receipt('c0',[],{reset_required:false}):receipt();},identity:()=>id,revision:()=>version,canApply:()=>editable,visible:()=>visible,clock:()=>now,
  read:async()=>({messages:['new-synthetic']}),apply:snapshot=>{applied.push(snapshot);return true},onState:state=>states.push(state),setTimer:(callback,ms)=>{const k=++seq;timers.set(k,{callback,ms});return k},clearTimer:k=>timers.delete(k),...overrides};
 const sync=window.XinjiContentUpdates.create(options);
 return {sync,calls,states,applied,timers,setId:v=>id=v,setVersion:v=>version=v,setEditable:v=>editable=v,setVisible:v=>visible=v,async start(){sync.start();await flush()},async check(){now+=1600;return sync.check()},fireDeadline(){const [id,t]=[...timers].find(([,t])=>t.ms===12000);timers.delete(id);t.callback()},window};
}
test('baseline precedes snapshot and stable second GET; all calls are read only',async()=>{
 const order=[];const f=fixture({read:async changes=>{order.push('snapshot:'+changes.cursor);return {messages:['new']}}});
 await f.start();assert.equal(f.applied.length,1);assert.equal(f.sync.state().cursor,'c0');assert.deepEqual(f.calls.map(c=>c.path),['/api/capabilities','/api/conversation/changes','/api/conversation/changes?after=c0']);assert.deepEqual(order,['snapshot:c0']);assert.ok(f.calls.every(c=>!c.opts.method&&c.opts.cache==='no-store'));f.sync.stop();
});
test('unchanged poll never reads a snapshot or any CLI endpoint',async()=>{
 let reads=0;const f=fixture({read:async()=>{reads++;return{}}});await f.start();await f.check();assert.equal(reads,1);assert.equal(f.calls.length,4);assert.equal(f.applied.length,1);f.sync.stop();
});
test('an open editor discovers updates but cannot publish or advance its cursor',async()=>{
 const f=fixture();f.setEditable(false);await f.start();assert.equal(f.sync.state().cursor,null);assert.equal(f.applied.length,0);assert.equal(f.states.at(-1),'pending');assert.equal(f.calls.length,2);f.setEditable(true);await f.check();assert.equal(f.applied.length,1);assert.equal(f.sync.state().cursor,'c0');f.sync.stop();
});
test('editor opening during read discards snapshot and retains original cursor',async()=>{
 let release;const f=fixture({read:()=>new Promise(r=>release=r)});await f.start();f.setEditable(false);release({private:'synthetic'});await flush();assert.equal(f.applied.length,0);assert.equal(f.sync.state().cursor,null);assert.equal(f.states.at(-1),'pending');f.sync.stop();
});
test('local mutation that starts and ends during read still invalidates its epoch',async()=>{
 let release;const f=fixture({read:()=>new Promise(r=>release=r)});await f.start();f.setVersion(2);release({});await flush();assert.equal(f.applied.length,0);assert.equal(f.sync.state().cursor,null);f.sync.stop();
});
test('snapshot failure retains cursor, backs off, and never retries a mutation',async()=>{
 const f=fixture({read:async()=>{throw Error('synthetic network loss')}});await f.start();assert.equal(f.sync.state().cursor,null);assert.equal(f.states.at(-1),'offline');assert.equal([...f.timers.values()][0].ms,30000);assert.equal(f.calls.length,2);f.sync.stop();
});
test('source withdrawal during snapshot rejects a mixed publication',async()=>{
 const calls=[];const f=fixture({api:async path=>{calls.push(path);return path==='/api/capabilities'?{features:{conversation_change_cursor:true}}:path.includes('?')?receipt('c1',['sources'],{reset_required:false}):receipt()}});await f.start();assert.equal(f.applied.length,0);assert.equal(f.sync.state().cursor,null);assert.equal(f.states.at(-1),'pending');assert.equal(calls.length,3);f.sync.stop();
});
test('a newer second cursor cannot become baseline even with empty domains',async()=>{
 const f=fixture({api:async path=>path==='/api/capabilities'?{features:{conversation_change_cursor:true}}:path.includes('?')?receipt('c1',[],{reset_required:false}):receipt()});await f.start();assert.equal(f.applied.length,0);assert.equal(f.sync.state().cursor,null);f.sync.stop();
});
test('wrong conversation or malformed domain receipts cannot publish',async()=>{
 for(const invalid of [receipt('c0',['messages'],{conversation_id:'another'}),receipt('c0',['unknown-domain']),receipt('c0',['messages','messages']),receipt('')]){
  const f=fixture({api:async path=>path==='/api/capabilities'?{features:{conversation_change_cursor:true}}:invalid});await f.start();assert.equal(f.applied.length,0);assert.equal(f.sync.state().cursor,null);f.sync.stop();
 }
});
test('instance replacement quarantines instead of silently migrating drafts',async()=>{
 let instance='test-service';const f=fixture({api:async path=>path==='/api/capabilities'?{features:{conversation_change_cursor:true}}:receipt('c0',path.includes('?')?[]:['messages'],{reset_required:!path.includes('?'),service_instance_id:instance})});await f.start();instance='replacement-service';await f.check();assert.equal(f.sync.state().instance,'test-service');assert.equal(f.applied.length,1);assert.equal(f.states.at(-1),'identity');f.sync.stop();
});
test('background aborts read and its late response cannot paint or schedule',async()=>{
 let release;const f=fixture({read:()=>new Promise(r=>release=r)});await f.start();f.setVisible(false);f.sync.visibilityChanged();release({});await flush();assert.equal(f.applied.length,0);assert.equal(f.sync.state().running,false);assert.equal(f.timers.size,0);f.sync.stop();
});
test('deadline releases slot even if a transport ignores abort',async()=>{
 const f=fixture({read:()=>new Promise(()=>{})});await f.start();f.fireDeadline();await flush();assert.equal(f.sync.state().running,false);assert.equal(f.states.at(-1),'offline');assert.equal(f.sync.state().cursor,null);f.sync.stop();
});
test('single flight remains held through cancellation until the old read unwinds',async()=>{
 const resolvers=[];const f=fixture({read:()=>new Promise(r=>resolvers.push(r))});await f.start();assert.equal(await f.check(),false);assert.equal(resolvers.length,1);
 f.sync.stop();f.sync.start();await flush();assert.equal(resolvers.length,1);assert.equal(f.sync.state().running,true);
 resolvers[0]({old:true});await flush();assert.equal(f.applied.length,0);assert.equal(f.sync.state().running,false);
 const [timerId,timer]=[...f.timers].find(([,t])=>t.ms===0);f.timers.delete(timerId);timer.callback();await flush();assert.equal(resolvers.length,2);
 resolvers[1]({new:true});await flush();assert.equal(f.applied.length,1);assert.equal(f.applied[0].new,true);f.sync.stop();
});
test('old service probes capabilities only and requires explicit fallback refresh',async()=>{
 const f=fixture({api:async path=>{f.calls.push({path});return{features:{}}}});await f.start();await f.check();assert.equal(f.calls.length,1);assert.equal(f.calls[0].path,'/api/capabilities');assert.equal(f.applied.length,0);assert.equal(f.states.at(-1),'unsupported');f.sync.stop();
});
test('refused publication retains cursor without claiming updated',async()=>{
 const f=fixture({apply:()=>false});await f.start();assert.equal(f.sync.state().cursor,null);assert.equal(f.states.at(-1),'pending');f.sync.stop();
});
