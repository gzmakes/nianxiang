const test=require('node:test'),assert=require('node:assert/strict'),http=require('node:http'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {DOMAINS,parseOrigin,sameOrigin,readJSON,metadata,probeService,partitionFor,selectionStore,createSelectionFlow}=require('../service-connection');
const caps=()=>({contract_version:'1.7.0',deployment_mode:'local_single_user',features:{conversation_change_cursor:true}});
const feed=(extra={})=>({service_instance_id:'instance-A',conversation_id:'conversation-A',cursor:'opaque_cursor',reset_required:true,reset_reason:'initial',domains:[...DOMAINS],...extra});
const profile=(origin='http://127.0.0.1:18787',extra={})=>metadata(origin,caps(),feed(extra));
async function server(t,handler){const s=http.createServer(handler);await new Promise(r=>s.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>{s.closeAllConnections();s.close(r)}));return 'http://127.0.0.1:'+s.address().port}
const json=(r,body)=>{r.writeHead(200,{'content-type':'application/json'});r.end(JSON.stringify(body))};
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};

test('only explicit canonical IPv4 loopback origin with valid port is accepted',()=>{
 for(const value of ['http://127.0.0.1:1','http://127.0.0.1:80','http://127.0.0.1:65535'])assert.equal(parseOrigin(value),value);
 for(const value of [null,'',' http://127.0.0.1:80','http://127.0.0.1:80 ','http://localhost:80','http://127.1:80','http://2130706433:80','http://127.0.0.1:080','https://127.0.0.1:80','http://127.0.0.1:0','http://127.0.0.1:65536','http://127.0.0.1:80/','http://127.0.0.1:80/a','http://127.0.0.1:80?a','http://127.0.0.1:80#x','http://u:p@127.0.0.1:80','http://[::1]:80'])assert.throws(()=>parseOrigin(value),String(value));
 assert.equal(sameOrigin('http://127.0.0.1/a','http://127.0.0.1:80'),true);assert.equal(sameOrigin('http://localhost:80','http://127.0.0.1:80'),false);
});
test('real HTTP probes only capabilities and initial feed, drops all extra data',async t=>{
 const requests=[];const origin=await server(t,(q,r)=>{requests.push([q.method,q.url]);json(r,q.url==='/api/capabilities'?{...caps(),private_config:'DO_NOT_KEEP'}:{...feed(),token:'DO_NOT_KEEP'})});
 const value=await probeService(origin);assert.deepEqual(requests,[['GET','/api/capabilities'],['GET','/api/conversation/changes']]);assert.deepEqual(Object.keys(value).sort(),['version','mode','origin','service_instance_id','conversation_id','contract_version'].sort());assert.ok(!JSON.stringify(value).includes('DO_NOT_KEEP'));
});
test('redirect is never followed, including same-origin trap',async t=>{
 let trap=0;const origin=await server(t,(q,r)=>{if(q.url==='/trap'){trap++;return json(r,caps())}r.writeHead(302,{location:'/trap'});r.end()});await assert.rejects(probeService(origin),/重定向/);assert.equal(trap,0);
});
test('real HTTP malformed and oversized length/stream are rejected',async t=>{
 const origin=await server(t,(q,r)=>{if(q.url==='/length'){r.writeHead(200,{'content-length':'999999'});return r.end()}if(q.url==='/stream'){r.writeHead(200);return r.end('a'.repeat(17000))}r.end('{bad')});
 await assert.rejects(readJSON(origin+'/length'),/大小/);await assert.rejects(readJSON(origin+'/stream'),/大小/);await assert.rejects(readJSON(origin+'/bad'),/格式/);
});
test('real HTTP overall timeout and cancellation do not wait for a slow response',async t=>{
 const origin=await server(t,()=>{});await assert.rejects(readJSON(origin,{timeoutMs:25}),/超时/);const c=new AbortController(),p=readJSON(origin,{signal:c.signal});c.abort();await assert.rejects(p,/取消/);const d=new AbortController();d.abort();await assert.rejects(readJSON(origin,{signal:d.signal}),/取消/);
});
test('identity changes and unsupported/malformed contract fail closed',async()=>{
 for(const changed of [{contract_version:'1.6.9'},{contract_version:'2.7.0'},{deployment_mode:'paired_personal_core'},{features:{conversation_change_cursor:false}}])assert.throws(()=>metadata('http://127.0.0.1:80',{...caps(),...changed},feed()));
 for(const changed of [{reset_required:false},{reset_reason:null},{cursor:'x x'},{domains:DOMAINS.slice(1)},{domains:[...DOMAINS.slice(1),'turns']},{service_instance_id:'bad id'},{conversation_id:''}])assert.throws(()=>metadata('http://127.0.0.1:80',caps(),feed(changed)));
 const original=profile();await assert.rejects(probeService(original.origin,{expected:original,read:async url=>url.endsWith('capabilities')?caps():feed({service_instance_id:'replacement'})}),/身份/);
});
test('partition is stable for same identity and separates every identity component',()=>{
 const original=profile(),key=partitionFor(original);assert.equal(key,partitionFor({...original,contract_version:'1.8.0'}));for(const changed of [{origin:'http://127.0.0.1:18788'},{service_instance_id:'B'},{conversation_id:'B'}])assert.notEqual(key,partitionFor({...original,...changed}));assert.match(key,/^persist:xinji-shared-v1-[0-9a-f]{64}$/);
});
test('selection store contains known metadata only, atomic 0600, and keeps old record if invalid',t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'echo-selection-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));const store=selectionStore(path.join(dir,'profile'));assert.equal(store.load(),null);store.save({...profile(),password:'PRIVATE',token:'PRIVATE'});assert.deepEqual(store.load(),profile());assert.ok(!fs.readFileSync(store.file,'utf8').includes('PRIVATE'));assert.equal(fs.statSync(store.file).mode&0o777,0o600);assert.throws(()=>store.save({mode:'shared'}));assert.deepEqual(store.load(),profile());store.save({version:1,mode:'own'});assert.deepEqual(store.load(),{version:1,mode:'own'});
});
test('selection store rejects symlinks, oversized and malformed persisted state',t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'echo-selection-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));const store=selectionStore(dir),other=path.join(dir,'other');fs.writeFileSync(other,JSON.stringify(profile()));fs.symlinkSync(other,store.file);assert.deepEqual(store.load(),{invalid:true});fs.unlinkSync(store.file);fs.writeFileSync(store.file,'x'.repeat(5000));assert.deepEqual(store.load(),{invalid:true});fs.writeFileSync(store.file,'{}');assert.deepEqual(store.load(),{invalid:true});
});
function flow(extra={}){const saves=[],activations=[];const f=createSelectionFlow({probe:async origin=>profile(origin),save:v=>saves.push(v),activate:async v=>activations.push(v),...extra});return {f,saves,activations}}
test('verification is read-only and connect requires explicit fresh matching candidate',async()=>{
 let now=0;const {f,saves,activations}=flow({clock:()=>now});const v=await f.verify('http://127.0.0.1:18787');assert.equal(saves.length,0);assert.equal(activations.length,0);for(const body of [{},{nonce:v.nonce,origin:v.origin},{nonce:'bad',origin:v.origin,confirmed:true},{nonce:v.nonce,origin:'http://127.0.0.1:18788',confirmed:true}])await assert.rejects(f.connect(body));now=60001;await assert.rejects(f.connect({nonce:v.nonce,origin:v.origin,confirmed:true}));assert.equal(saves.length,0);
});
test('connect reprobes identity, persists only before activation, and cannot reuse nonce',async()=>{
 const calls=[],{f,saves,activations}=flow({probe:async(origin,options)=>{calls.push(options?.expected);return profile(origin)}});const v=await f.verify('http://127.0.0.1:18787');assert.equal(await f.connect({nonce:v.nonce,origin:v.origin,confirmed:true}),true);assert.equal(calls.length,2);assert.equal(calls[1].service_instance_id,'instance-A');assert.equal(saves.length,1);assert.equal(activations.length,1);await assert.rejects(f.connect({nonce:v.nonce,origin:v.origin,confirmed:true}));
});
test('latest verification wins, old response cannot become confirmable',async()=>{
 const first=deferred(),{f}=flow({probe:origin=>origin.endsWith('18787')?first.promise:Promise.resolve(profile(origin))});const old=f.verify('http://127.0.0.1:18787');const next=await f.verify('http://127.0.0.1:18788');first.resolve(profile());assert.deepEqual(await old,{ok:false,reason:'superseded'});assert.equal(await f.connect({nonce:next.nonce,origin:next.origin,confirmed:true}),true);
});
test('invalidating in-flight confirmation prevents persistence and activation',async()=>{
 const pending=deferred();let call=0;const {f,saves,activations}=flow({probe:origin=>++call===1?Promise.resolve(profile(origin)):pending.promise});const v=await f.verify('http://127.0.0.1:18787');const result=f.connect({nonce:v.nonce,origin:v.origin,confirmed:true});assert.equal(f.busy,true);await assert.rejects(f.own(true));f.invalidate();pending.resolve(profile());assert.equal(await result,false);assert.equal(saves.length,0);assert.equal(activations.length,0);
});
test('replacement between preview and confirmation and disk errors never activate',async()=>{
 let call=0;let env=flow({probe:async origin=>{if(++call>1)throw Error('identity changed');return profile(origin)}});let v=await env.f.verify('http://127.0.0.1:18787');await assert.rejects(env.f.connect({...v,confirmed:true}),/identity/);assert.equal(env.saves.length,0);assert.equal(env.activations.length,0);env=flow({save:()=>{throw Error('disk full')}});v=await env.f.verify('http://127.0.0.1:18787');await assert.rejects(env.f.connect({...v,confirmed:true}),/disk/);await assert.rejects(env.f.own(true),/disk/);assert.equal(env.activations.length,0);
});
test('return to original space requires explicit confirmation',async()=>{const {f,saves,activations}=flow();await assert.rejects(f.own(false));assert.equal(saves.length,0);assert.equal(await f.own(true),true);assert.deepEqual(saves,[{version:1,mode:'own'}]);assert.deepEqual(activations,saves)});
