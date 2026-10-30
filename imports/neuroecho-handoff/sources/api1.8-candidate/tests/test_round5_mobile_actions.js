// Shared task cards used by H5: resuming a preview is distinct from checking an unknown write.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const shared=fs.readFileSync('web/action-cards.js','utf8');
function cards(){const context=vm.createContext({window:{},navigator:{}});vm.runInContext(shared,context);return context.window.XinjiActionCards;}
const actions=()=>[
 {id:'existing-preview',kind:'calendar',title:'用户已核对的安排',detail:'完整合成内容',status:'previewed'},
 {id:'unknown-write',kind:'reminder',title:'待核对提醒',status:'unknown'},
 {id:'active-write',kind:'calendar',title:'执行中安排',status:'executing'},
 {id:'saved-message',kind:'message',title:'已保存草稿',detail:'完整合成草稿',status:'committed',real:0},
 {id:'failed-write',kind:'calendar',title:'失败安排',status:'failed'},
];
function button(key,index){return{dataset:{[key]:String(index)},disabled:false};}
test('interactive saved tasks only offer confirmation for previewed records and status checks for unknown writes',()=>{
 const all=actions(),html=cards().html(all,{interactive:true});
 assert.equal((html.match(/data-action-continue=/g)||[]).length,1);assert.match(html,/data-action-continue="0"/);
 assert.equal((html.match(/data-action-check=/g)||[]).length,2);assert.match(html,/data-action-check="1"/);assert.match(html,/data-action-check="2"/);
 assert.match(html,/重新读取本机记录，不会再次写入系统/);assert.match(html,/草稿已保存 · 未发送/);assert.ok(html.includes(all[3].detail));
 const legacy=cards().html(all);assert.doesNotMatch(legacy,/data-action-continue|data-action-check/);
});
test('task card callbacks receive the existing record without creating or approving an action during render',()=>{
 const all=actions(),continued=[],checked=[],confirm=button('actionContinue',0),check=button('actionCheck',1);
 const container={querySelectorAll:selector=>selector==='[data-action-continue]'?[confirm]:selector==='[data-action-check]'?[check]:[]};
 cards().bind(container,all,{onContinue:action=>continued.push(action),onCheck:action=>checked.push(action)});
 assert.equal(continued.length,0);assert.equal(checked.length,0);confirm.onclick();check.onclick();
 assert.equal(continued[0],all[0]);assert.equal(continued[0].id,'existing-preview');assert.equal(checked[0],all[1]);
});
test('tampered or stale task buttons cannot turn unknown or completed records into confirmable previews',()=>{
 const all=actions(),continued=[],checked=[],wrongContinue=button('actionContinue',1),wrongCheck=button('actionCheck',0),stale=button('actionContinue',0);
 const container={querySelectorAll:selector=>selector==='[data-action-continue]'?[wrongContinue,stale]:selector==='[data-action-check]'?[wrongCheck]:[]};
 cards().bind(container,all,{onContinue:action=>continued.push(action),onCheck:action=>checked.push(action)});
 wrongContinue.onclick();wrongCheck.onclick();all[0].status='committed';stale.onclick();assert.equal(continued.length,0);assert.equal(checked.length,0);
});

const mobile=fs.readFileSync('web/m.js','utf8');
function clip(a,b){const i=mobile.indexOf(a),j=mobile.indexOf(b,i);assert.ok(i>=0&&j>i);return mobile.slice(i,j);}
function actionEnvironment(reply){
 const nodes=new Map(),$=id=>{if(!nodes.has(id)){const classes=new Set();nodes.set(id,{value:'',textContent:'',disabled:false,readOnly:false,checked:false,lastChild:{textContent:''},classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),toggle:(x,on)=>on?classes.add(x):classes.delete(x),contains:x=>classes.has(x)}});}return nodes.get(id);};
 const state={session:{id:'canonical'},context:{insights:[]}},calls=[],notes=[],refreshed=[];$('#m-sheet')._xinjiEpoch=4;$('#m-sheet')._xinjiKind='tasks';
 const context=vm.createContext({$,state,Date,encodeURIComponent,toast:text=>notes.push(text),mobileInsightUsable:()=>true,
  loadMobileTaskActions:()=>refreshed.push('tasks'),api:async(path,opts={})=>{calls.push({path,opts});return reply(path,opts);}});
 vm.runInContext(clip('  let mobileAction = ', '  function renderInsights()')+
  clip('  function openMobileSavedAction(', '  async function saveBookmark()')+
  '\nObject.assign(this,{open:openMobileAction,openSaved:openMobileSavedAction,check:checkMobileSavedAction,confirm:confirmMobileAction,close:closeMobileAction,current:()=>mobileAction});',context);
 return{context,state,$,calls,notes,refreshed};
}
const savedPreview=()=>({id:'old-preview',session_id:'canonical',kind:'message',status:'previewed',title:'原已核对标题',detail:'原已核对正文\n第二行'});
test('H5 resumes the same saved preview, rechecks its status, and commits its original id without creating another record',async()=>{
 const action=savedPreview(),e=actionEnvironment(async path=>path.startsWith('/api/actions?')?{actions:[action]}:{status:'committed',real:0});
 e.context.openSaved(action);assert.equal(e.calls.length,0);assert.equal(e.$('#m-action-name').readOnly,true);assert.equal(e.$('#m-action-message').readOnly,true);assert.equal(e.$('#m-action-message').value,action.detail);
 await e.context.confirm();assert.deepEqual(e.calls.map(call=>call.path),['/api/actions?session_id=canonical','/api/action/old-preview/commit']);assert.equal(e.calls[1].opts.method,'POST');assert.deepEqual(JSON.parse(e.calls[1].opts.body),{real:false});assert.ok(e.refreshed.includes('tasks'));assert.match(e.notes.at(-1),/未发送/);
});
test('a saved H5 preview that became unknown or executing cannot be committed or recreated',async()=>{
 for(const status of ['unknown','executing','committed']){
  const action=savedPreview(),e=actionEnvironment(async()=>({actions:[{...action,status}]}));e.context.openSaved(action);await e.context.confirm();
  assert.equal(e.calls.length,1);assert.ok(e.calls.every(call=>call.opts.method!=='POST'));assert.match(e.$('#m-action-result').textContent,/不会再次写入/);assert.equal(e.$('#m-action-confirm').disabled,true);
 }
});
test('H5 status checks for unknown results only read the local record and do not retry an external write',async()=>{
 const action={...savedPreview(),status:'unknown'},e=actionEnvironment(async()=>({actions:[action]}));await e.context.check(action);
 assert.deepEqual(e.calls.map(call=>call.path),['/api/actions?session_id=canonical']);assert.ok(e.calls.every(call=>call.opts.method!=='POST'));assert.ok(e.refreshed.includes('tasks'));assert.match(e.notes.at(-1),/当前不会再次写入/);
});
test('new H5 actions are editable previews and only save after the user confirms their exact content',async()=>{
 const e=actionEnvironment(async path=>path==='/api/action'?{id:'new-id'}:{status:'committed',real:0});e.context.open('message',null,{title:'',text:''});assert.equal(e.calls.length,0);assert.equal(e.$('#m-action-real').checked,false);
 e.$('#m-action-name').value='给自己的话';e.$('#m-action-message').value='完整合成正文\n第二行';await e.context.confirm();
 assert.deepEqual(JSON.parse(e.calls[0].opts.body),{session_id:'canonical',kind:'message',title:'给自己的话',detail:'完整合成正文\n第二行',when:''});assert.equal(e.calls[1].path,'/api/action/new-id/commit');assert.deepEqual(JSON.parse(e.calls[1].opts.body),{real:false});
});
test('a lost H5 commit response retains the created id and blocks blind duplicate saving',async()=>{
 const e=actionEnvironment(async path=>{if(path==='/api/action')return{id:'retained-id'};throw Error('合成响应丢失');});e.context.open('message',null,{title:'标题',text:'完整正文'});await e.context.confirm();await e.context.confirm();
 assert.equal(e.calls.filter(call=>call.path==='/api/action').length,1);assert.equal(e.calls.filter(call=>call.path==='/api/action/retained-id/commit').length,1);assert.equal(e.context.current().existingId,'retained-id');assert.equal(e.$('#m-action-confirm').disabled,true);assert.match(e.$('#m-action-result').textContent,/暂勿重复保存/);
});
test('a late status response cannot commit an old preview after the active context changes',async()=>{
 let resolve;const waiting=new Promise(r=>resolve=r),action=savedPreview(),e=actionEnvironment(async()=>waiting);e.context.openSaved(action);const pending=e.context.confirm();e.state.session={id:'other'};resolve({actions:[action]});await pending;
 assert.equal(e.calls.length,1);assert.ok(e.calls.every(call=>call.opts.method!=='POST'));
});
test('duplicate clicks while a H5 confirmation is pending create and commit only one record',async()=>{
 let resolve;const waiting=new Promise(r=>resolve=r),e=actionEnvironment(async path=>path==='/api/action'?waiting:{status:'committed',real:0});e.context.open('message',null,{title:'准确标题',text:'准确正文'});const pending=e.context.confirm();await e.context.confirm();assert.equal(e.calls.length,1);resolve({id:'one-id'});await pending;
 assert.equal(e.calls.filter(call=>call.path==='/api/action').length,1);assert.equal(e.calls.filter(call=>call.path==='/api/action/one-id/commit').length,1);
});
test('cancelling a H5 action during creation prevents a late response from committing it',async()=>{
 let resolve;const waiting=new Promise(r=>resolve=r),e=actionEnvironment(async()=>waiting);e.context.open('message',null,{title:'取消的预览',text:'保留为未确认草稿'});const pending=e.context.confirm();
 e.context.close();assert.equal(e.context.current(),null);assert.equal(e.$('#m-action').classList.contains('is-hidden'),true);resolve({id:'saved-but-not-approved'});await pending;
 assert.equal(e.calls.length,1);assert.equal(e.calls[0].path,'/api/action');assert.ok(!e.calls.some(call=>call.path.endsWith('/commit')));assert.ok(!e.notes.some(note=>/已保存|已写入/.test(note)));
});
