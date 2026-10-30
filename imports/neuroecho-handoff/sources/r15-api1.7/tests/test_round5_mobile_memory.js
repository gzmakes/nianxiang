// Real memory action handler, synthetic network responses and UI state only.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/m.js','utf8');
function setup(){
 const sheet={_xinjiEpoch:3,_xinjiKind:'understand'},body={innerHTML:'原有记忆页'},nodes=new Map([['#m-sheet',sheet],['#m-sheet-body',body]]),$=id=>nodes.get(id);
 const memory={id:'memory',text:'原合成内容',status:'candidate',version:1},state={session:{id:'canonical'},memories:[memory]},calls=[],renders=[],notices=[];
 let resolve,reject;const waiting=new Promise((ok,no)=>{resolve=ok;reject=no;});
 const context=vm.createContext({$,state,prompt:()=> '用户纠正的准确内容',toast:text=>notices.push(text),api:async(path,opts)=>{calls.push({path,opts});return waiting;},
  renderAll:()=>renders.push('chat'),renderUnderstanding:()=>{renders.push('memories');body.innerHTML='更新后的记忆页';},loadNextStep:()=>renders.push('next'),showMemoryContextNotice:()=>renders.push('context'),esc:String});
 context.window={XinjiDialogs:{prompt:async()=>context.prompt(),confirm:async()=>true}};
 vm.runInContext(fs.readFileSync('web/client-sync.js','utf8'),context);
 const rawApi=context.api;context.api=async(path,opts)=>path==='/api/capabilities'?{features:{memory_expected_version_patch:true,memory_expected_version_delete:true}}:rawApi(path,opts);
 const i=source.indexOf('  async function onMemAction('),j=source.indexOf('  function renderBookmark(',i);assert.ok(i>=0&&j>i);vm.runInContext(source.slice(i,j)+'\nthis.run=onMemAction;',context);
 const event=act=>({target:{closest:selector=>selector==='[data-act]'?{dataset:{id:'memory',act}}:null}});
 return{context,state,sheet,body,memory,calls,renders,notices,resolve,reject,event};
}
test('saving a memory correction changes the actual stored text while keeping the active memory view current',async()=>{
 const e=setup(),pending=e.context.run(e.event('edit'));await new Promise(setImmediate);assert.equal(e.calls.length,1);assert.equal(e.calls[0].path,'/api/memory/memory');assert.equal(JSON.parse(e.calls[0].opts.body).text,'用户纠正的准确内容');
 e.resolve({id:'memory',text:'用户纠正的准确内容',status:'confirmed',version:2});await pending;
 assert.equal(e.memory.text,'用户纠正的准确内容');assert.equal(e.memory.version,2);assert.ok(e.renders.includes('memories'));
});
test('a completed memory edit cannot repaint a task sheet opened while the save was pending',async()=>{
 const e=setup(),pending=e.context.run(e.event('edit'));await new Promise(setImmediate);e.sheet._xinjiEpoch++;e.sheet._xinjiKind='tasks';e.body.innerHTML='用户刚打开的任务';
 e.resolve({id:'memory',text:'用户纠正的准确内容',status:'confirmed',version:2});await pending;
 assert.equal(e.body.innerHTML,'用户刚打开的任务');assert.ok(!e.renders.includes('memories'));
});
test('a late confirmation for another session does not render or mutate the newly loaded memories',async()=>{
 const e=setup(),pending=e.context.run(e.event('confirm'));e.state.session={id:'other'};e.state.memories=[{id:'new-memory',text:'另一个上下文',version:1}];e.body.innerHTML='另一个上下文';
 e.resolve({id:'memory',text:'旧会话结果',status:'confirmed',version:2});await pending;
 assert.equal(e.state.memories[0].id,'new-memory');assert.equal(e.body.innerHTML,'另一个上下文');assert.equal(e.renders.length,0);
});
