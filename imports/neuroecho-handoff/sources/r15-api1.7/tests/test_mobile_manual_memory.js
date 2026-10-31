const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const src=fs.readFileSync('web/m.js','utf8'),start=src.indexOf('  let mobileManualMemoryOperation='),end=src.indexOf('  async function onMemAction(',start);
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve}}
function setup(api,prompt=async()=> '  合成偏好  '){
 const sheet={_xinjiEpoch:1,_xinjiKind:'understand'},button={disabled:false},state={session:{id:'synthetic'},memories:[]},toasts=[];let renders=0;
 const ctx=vm.createContext({state,$:id=>id==='#m-sheet'?sheet:button,api,window:{XinjiDialogs:{prompt}},renderUnderstanding(){renders++},toast:t=>toasts.push(t),encodeURIComponent});
 vm.runInContext(src.slice(start,end)+'\nthis.add=addMobileMemoryPrompt;',ctx);return{ctx,state,sheet,toasts,renders:()=>renders};
}
test('H5 manual memory explicitly adds a user-asserted fact and reads it back without another confirmation',async()=>{
 const calls=[],memory={id:'mem-synthetic',session_id:'synthetic',kind:'fact',text:'合成偏好',status:'auto'};
 const env=setup(async(path,opts)=>{calls.push({path,opts});return opts?memory:{memories:[memory]}});await env.ctx.add();
 assert.equal(calls.length,2);assert.equal(calls[0].path,'/api/memory');const body=JSON.parse(calls[0].opts.body);assert.equal(body.session_id,'synthetic');assert.equal(body.text,'合成偏好');assert.equal(body.status,undefined);assert.equal(body.user_asserted,true);assert.equal(body.source,'用户手动添加');
 assert.equal(calls[1].path,'/api/memory?session_id=synthetic');assert.equal(env.state.memories[0].status,'auto');assert.equal(env.renders(),1);assert.match(env.toasts[0],/已记下/);
});
test('H5 cancelled prompt and sheet change during prompt make no write',async()=>{
 for(const cancel of [true,false]){let calls=0;const d=deferred(),env=setup(async()=>{calls++},()=>d.promise);const work=env.ctx.add();if(!cancel)env.sheet._xinjiEpoch++;d.resolve(cancel?null:'原话');await work;assert.equal(calls,0)}
});
test('H5 late memory response cannot overwrite another conversation or reopened sheet',async()=>{
 for(const change of ['session','sheet']){const d=deferred();let calls=0;const env=setup(async()=>{calls++;return d.promise});const work=env.ctx.add();await new Promise(setImmediate);if(change==='session')env.state.session={id:'new'};else env.sheet._xinjiEpoch++;
 d.resolve({id:'mem-synthetic',session_id:'synthetic',status:'auto'});await work;assert.equal(calls,1);assert.equal(env.state.memories.length,0);assert.equal(env.renders(),0);assert.equal(env.toasts.length,0)}
});
