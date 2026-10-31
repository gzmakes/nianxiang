const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const code = fs.readFileSync('web/chat-delivery.js', 'utf8');
function environment(api) {
 const timers = new Map(); let seq = 0;
 const win = {};
 vm.runInNewContext(code, {window:win, setTimeout:(fn)=>{timers.set(++seq,fn);return seq}, clearTimeout:id=>timers.delete(id)});
 const state = {session:{id:'s'}, messages:[{id:'m',role:'assistant',text:'第一段',bubbles:['第一段'],delivery_pending:true,delivery_next_ms:800}]};
 const hidden = new Set(); let renders = 0;
 const delivery = win.XinjiChatDelivery.create({state, api, render:()=>renders++, stopButton:{classList:{toggle:(name,off)=>off?hidden.add(name):hidden.delete(name)}}, busy:()=>false});
 return {state,delivery,timers,hidden,get renders(){return renders}};
}
test('pending reply is refreshed from the server and retains local drafts', async () => {
 const env = environment(async () => ({messages:[{id:'m',role:'assistant',text:'第一段\n\n第二段',bubbles:['第一段','第二段'],delivery_pending:false}]}));
 env.state.messages.push({id:'local-1',role:'user',text:'正在输入'}); env.delivery.schedule();
 assert.equal(env.timers.size,1); await [...env.timers.values()][0]();
 assert.equal(env.state.messages[0].text,'第一段\n\n第二段');
 assert.equal(env.state.messages[1].text,'正在输入'); assert.equal(env.renders,1);
});
test('a late pre-interruption poll cannot restore a stopped remainder', async () => {
 let resolveOld, reads=0; const old=new Promise(resolve=>resolveOld=resolve);
 const env=environment(async (_url,opts) => {
   if (_url==='/api/capabilities') return {features:{chat_delivery_targeted_stop:true}};
   if(opts?.method==='POST') { assert.deepEqual(JSON.parse(opts.body),{message_id:'m'}); return {ok:true,stopped:true,message_id:'m'}; }
   if(++reads===1) return old;
   return {messages:[{id:'m',role:'assistant',text:'第一段',bubbles:['第一段'],delivery_pending:false}]};
 });
 env.delivery.schedule(); const waiting=[...env.timers.values()][0]();
 await env.delivery.stop();
 resolveOld({messages:[{id:'m',role:'assistant',text:'第一段\n\n旧尾段',bubbles:['第一段','旧尾段'],delivery_pending:false}]});
 await waiting;
 assert.equal(env.state.messages[0].text,'第一段');
});
test('an older service cannot receive an unsafe unscoped stop', async()=>{
 const calls=[];const env=environment(async(path,opts)=>{calls.push([path,opts]);return {features:{}}});
 await env.delivery.stop();assert.equal(calls.length,1);assert.equal(calls[0][0],'/api/capabilities');assert.equal(env.state.messages[0].delivery_pending,true);
});
test('an outdated target never turns a newer pending reply into a stopped one',async()=>{
 let resolveStop;const env=environment(async(path,opts)=>path==='/api/capabilities'?{features:{chat_delivery_targeted_stop:true}}:opts?.method==='POST'?new Promise(r=>resolveStop=r):{messages:[{id:'new',role:'assistant',text:'新回复',delivery_pending:true}]});
 const stopping=env.delivery.stop();await new Promise(setImmediate);
 env.state.messages=[{id:'new',role:'assistant',text:'新回复',delivery_pending:true}];
 resolveStop({ok:true,stopped:false,message_id:'m',reason:'not_current'});await stopping;
 assert.equal(env.state.messages[0].id,'new');assert.equal(env.state.messages[0].delivery_pending,true);
});
test('a stable cross-device snapshot invalidates older delivery reads before replacing messages',async()=>{
 let release;const env=environment(()=>new Promise(r=>release=r));env.delivery.schedule();const read=[...env.timers.values()][0]();
 env.delivery.invalidateReads();env.state.messages=[{id:'m',role:'assistant',text:'已撤回旧来源后的当前内容',delivery_pending:false}];
 release({messages:[{id:'m',role:'assistant',text:'旧来源的晚到片段',delivery_pending:true}]});await read;
 assert.equal(env.state.messages[0].text,'已撤回旧来源后的当前内容');assert.equal(env.state.messages[0].delivery_pending,false);assert.equal(env.renders,0);
});

test('delivery polling preserves in-memory picture preview while updating remote message fields',async()=>{
 const data='data:image/png;base64,AAAA';
 const env=environment(async()=>({messages:[{id:'m',role:'assistant',text:'完成',delivery_pending:false},{id:'u',role:'user',text:'[图片]',persona_id:'updated'}]}));
 env.state.messages.push({id:'u',role:'user',text:'[图片]',persona_id:'old',image_data_url:data});
 env.delivery.schedule();await [...env.timers.values()][0]();
 assert.equal(env.state.messages[1].image_data_url,data);assert.equal(env.state.messages[1].persona_id,'updated');
});
