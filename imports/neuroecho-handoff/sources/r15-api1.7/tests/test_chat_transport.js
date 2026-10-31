const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'),vm=require('node:vm');
function setup(api){const c=vm.createContext({setTimeout,Map,Date,Math,Promise,crypto:{randomUUID:()=> 'request-fixture-123'}});vm.runInContext(fs.readFileSync('web/chat-transport.js','utf8'),c);return c.XinjiChatTransport.create(api,{pause:async()=>{},attempts:2});}
const result={reply:'合成回复',messages:[{id:'user-1',role:'user',text:'原话'}],memories:[],action:'model.reply'};
test('lost response recovers original completion without another POST',async()=>{let posts=0,queries=0;const transport=setup(async(path)=>{if(path==='/api/chat'){posts++;throw Error('response lost')}queries++;return{status:'completed',result}});const turn={session_id:'s',text:'原话'};assert.equal((await transport.send(turn)).reply,'合成回复');assert.equal(posts,1);assert.equal(queries,1);assert.equal(turn.request_id,'request-fixture-123');});
test('explicit retry preserves original request id',async()=>{let bodies=[];const transport=setup(async(path,opts)=>{bodies.push(JSON.parse(opts.body));return result});const turn={session_id:'s',text:'原话'};await transport.send(turn);await transport.send(turn);assert.equal(bodies[0].request_id,bodies[1].request_id);assert.equal(bodies[0].text,'原话');});
test('supplement requests cancel before the completed result is displayed',async()=>{let paths=[],release;const transport=setup(async(path)=>{paths.push(path);if(path==='/api/chat')return new Promise(r=>release=r);return{status:'completed',result:{...result,reply:'',cancelled:true}}});const turn={session_id:'s',text:'原话'};const pending=transport.send(turn);await transport.cancel(turn);release(result);const received=await pending;assert.equal(received.cancelled,true);assert.equal(received.reply,'');assert.ok(paths.some(p=>p.endsWith('/cancel')));});
test('unknown interrupted work is not reexecuted automatically',async()=>{let posts=0;const transport=setup(async(path)=>{if(path==='/api/chat'){posts++;throw Error('lost')}return{status:'unknown',error_code:'process_interrupted'}});await assert.rejects(transport.send({session_id:'s',text:'原话'}),e=>e.uncertain&&e.code==='process_interrupted');assert.equal(posts,1);});
test('not received yet does not get a fresh id or duplicate automatic POST',async()=>{let posts=0;const transport=setup(async(path)=>{if(path==='/api/chat'){posts++;throw Error('lost')}const e=Error('not found');e.status=404;throw e});await assert.rejects(transport.send({session_id:'s',text:'原话'}),e=>e.uncertain);assert.equal(posts,1);});
test('safety response is retained even if cancellation was requested',async()=>{let release;const transport=setup(async(path)=>path==='/api/chat'?new Promise(r=>release=r):{status:'running'});const turn={session_id:'s',text:'synthetic'};const pending=transport.send(turn);await transport.cancel(turn);release({...result,action:'safety'});assert.equal((await pending).action,'safety');});
test('a failed cancellation stays uncertain and never returns the obsolete reply for display',async()=>{
 let release,cancelAttempts=0;
 const transport=setup(async path=>{
  if(path==='/api/chat')return new Promise(resolve=>release=resolve);
  if(path.endsWith('/cancel')){cancelAttempts++;throw Error('offline')}
  throw Error('unexpected request');
 });
 const turn={session_id:'s',text:'原话'},pending=transport.send(turn);
 await transport.cancel(turn);release(result);
 await assert.rejects(pending,error=>error.uncertain===true);
 assert.equal(turn.cancelWanted,true);assert.ok(cancelAttempts>=2);
 assert.equal(turn.request_id,'request-fixture-123');
});

test('new request preserves frozen time_zone on explicit replay; old payload omits it entirely',async()=>{
 const bodies=[],transport=setup(async(path,options)=>{bodies.push(JSON.parse(options.body));return result});
 const turn={session_id:'s',text:'今天先别问',memory_proposals:false,time_zone:'Asia/Shanghai'};
 await transport.send(turn);await transport.send(turn);assert.equal(bodies[0].time_zone,'Asia/Shanghai');assert.deepEqual(bodies[0],bodies[1]);
 await transport.send({session_id:'s',text:'旧请求',request_id:'legacy-stable',memory_proposals:false});assert.equal(Object.hasOwn(bodies[2],'time_zone'),false);
});

test('image is sent once, but never written into the recovery ledger',async()=>{
 const data='data:image/png;base64,c2Vuc2l0aXZl', store=new Map(), writes=[];
 const storage={getItem:k=>store.get(k)||null,setItem:(k,v)=>{store.set(k,v);writes.push(v)}};
 const context=vm.createContext({setTimeout,Map,Date,Math,Promise,crypto:{randomUUID:()=> 'image-request'}});
 vm.runInContext(fs.readFileSync('web/chat-transport.js','utf8'),context);
 const ledger=context.XinjiChatTransport.createLedger('web',storage);
 const part={id:'p',sessionId:'s',text:'[图片]',image_data_url:data};
 ledger.enqueue(part);
 let body;
 const transport=context.XinjiChatTransport.create(async(path,opts)=>{body=JSON.parse(opts.body);return result},{ledger});
 await transport.send({session_id:'s',text:'[图片]',image_data_url:data},()=>{},[part]);
 assert.equal(body.image_data_url,data);
 assert.ok(writes.every(value=>!value.includes(data)));
 assert.ok(writes.some(value=>value.includes('has_image')));
});

test('a queued image lost on reload does not become a fake text-only send',()=>{
 const store=new Map(),storage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)};
 const context=vm.createContext({setTimeout,Map,Date,Math,Promise});
 vm.runInContext(fs.readFileSync('web/chat-transport.js','utf8'),context);
 const ledger=context.XinjiChatTransport.createLedger('web',storage);
 ledger.enqueue({id:'p',sessionId:'s',text:'[图片]',image_data_url:'data:image/png;base64,AAAA'});
 const restored=ledger.restore('s');
 assert.equal(restored.draft,'');assert.equal(restored.imageLost,true);
});
