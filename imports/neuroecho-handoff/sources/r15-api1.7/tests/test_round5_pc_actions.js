// Shipped PC action flows with synthetic records and no external writes.
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('web/app.js', 'utf8');
function clip(a,b) { const start=source.indexOf(a), end=source.indexOf(b,start); assert.ok(start>=0&&end>start); return source.slice(start,end); }
function node() { const classes=new Set(); return {value:'',textContent:'',innerHTML:'',disabled:false,checked:false,readOnly:false,lastChild:{textContent:''},classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),toggle:(x,yes)=>yes?classes.add(x):classes.delete(x),contains:x=>classes.has(x)},focus(){this.focused=true},querySelectorAll(){return[]},addEventListener(name,fn){this[name]=fn}}; }
function fixture() {
 const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id)}, calls=[],notes=[],refresh=[];
 const state={session:{id:'one'},messages:[],nextStep:{step:'另一个面板的建议'}};
 let actions=[],lost=false,deferredCreate=null;
 const ctx=vm.createContext({$,state,els:{input:node(),bmNote:node(),bmNext:node()},Date,encodeURIComponent,toast:text=>notes.push(text),insightEntries:()=>[],connectedSources:()=>[],switchTab:name=>refresh.push(name),loadTaskActions:async()=>{calls.push(['/api/actions?session_id=one',{method:'GET'}]);refresh.push('tasks')},loadToday:()=>refresh.push('today'),loadAudit(){},touchLastSeen(){},openBookmarkModal(){ctx.els.bmNext.value=state.nextStep.step},api:async(path,options={})=>{calls.push([path,options]);if(path.startsWith('/api/actions?'))return {actions};if(path==='/api/action')return deferredCreate || {id:'created-one',status:'previewed'};if(path.endsWith('/commit')){if(lost)throw Error('response lost');return{status:'committed',real:0}};throw Error(path)}});
 vm.runInContext('let pendingAction=null;'+clip('  function closeAction(', '  function actionStatusLabel(')+clip('  function putTodayDraft(', '  async function loadToday(')+'\nObject.assign(this,{closeAction,openAction,openSavedAction,confirmAction,checkActionStatus,putTodayDraft,bookmarkTodayStep,getPending:()=>pendingAction});',ctx);
 return {ctx,$,calls,notes,refresh,state,setActions:value=>actions=value,lose:()=>lost=true,deferCreate:value=>deferredCreate=value};
}
test('manual draft is editable and creates one local record only after confirmation',async()=>{
 const f=fixture();f.ctx.openAction('message',-1,{title:'',text:'',manual:true});assert.equal(f.calls.length,0);
 f.$('#action-name').value='给朋友';f.$('#action-message').value='完整正文\n第二行';await f.ctx.confirmAction();
 const create=f.calls.find(([path])=>path==='/api/action');assert.deepEqual(JSON.parse(create[1].body),{session_id:'one',kind:'message',title:'给朋友',detail:'完整正文\n第二行',when:''});
 const commit=f.calls.find(([path])=>path==='/api/action/created-one/commit');assert.deepEqual(JSON.parse(commit[1].body),{real:false});assert.ok(f.refresh.includes('tasks'));assert.ok(f.refresh.includes('today'));
});
test('pending saved action confirms the same id without creating another action',async()=>{
 const f=fixture(),action={id:'previous',session_id:'one',kind:'message',status:'previewed',title:'原草稿',detail:'原正文'};f.setActions([action]);f.ctx.openSavedAction(action);assert.equal(f.$('#action-name').readOnly,true);await f.ctx.confirmAction();
 assert.equal(f.calls.some(([path])=>path==='/api/action'),false);assert.equal(f.calls.filter(([path])=>path==='/api/action/previous/commit').length,1);
});
test('a saved preview that became unknown is never committed or recreated',async()=>{
 const f=fixture(),action={id:'previous',session_id:'one',kind:'reminder',status:'previewed',title:'提醒',detail:''};f.ctx.openSavedAction(action);f.setActions([{...action,status:'unknown'}]);await f.ctx.confirmAction();
 assert.equal(f.calls.some(([,opt])=>opt.method==='POST'),false);assert.match(f.$('#action-result').textContent,/没有再次写入/);
});
test('lost commit response retains the created id and blocks duplicate creation',async()=>{
 const f=fixture();f.ctx.openAction('message',-1,{title:'草稿',text:'保留正文'});f.lose();await f.ctx.confirmAction();await f.ctx.confirmAction();
 assert.equal(f.calls.filter(([path])=>path==='/api/action').length,1);assert.equal(f.ctx.getPending().existingId,'created-one');assert.equal(f.$('#action-confirm').disabled,true);assert.match(f.$('#action-result').textContent,/暂勿重复保存/);
});
test('unknown action check reads local status and never posts an external retry',async()=>{
 const f=fixture();await f.ctx.checkActionStatus({id:'unknown',session_id:'one',status:'unknown'});assert.ok(f.calls.length);assert.equal(f.calls.some(([,opt])=>opt.method==='POST'),false);assert.match(f.notes.at(-1),/没有再次写入系统/);
});
test('Today continuation preserves the unsent draft and never sends',()=>{
 const f=fixture();f.ctx.els.input.value='还没说完';f.ctx.putTodayDraft('想接着聊的话','one');assert.equal(f.ctx.els.input.value,'还没说完\n想接着聊的话');assert.equal(f.ctx.els.input.focused,true);assert.equal(f.calls.length,0);
 f.state.session.id='other';f.ctx.putTodayDraft('旧卡片','one');assert.doesNotMatch(f.ctx.els.input.value,/旧卡片/);
});
test('Today bookmark uses its own card step rather than the other panel state',()=>{
 const f=fixture();f.ctx.bookmarkTodayStep('这张卡自己的下一步','one');assert.equal(f.ctx.els.bmNext.value,'这张卡自己的下一步');
});
test('normal PC contains no welcome/history/reset or legacy demo read endpoints',()=>{
 const html=fs.readFileSync('web/index.html','utf8');assert.doesNotMatch(html,/id="(?:companion-welcome|reopen-welcome|history-btn|reset-btn)"/);assert.doesNotMatch(source,/\/api\/onboarding\/(?:catalog|read|start)["`]/);assert.doesNotMatch(clip('  async function commitBookmark()', '  // ---------------- misc ----------------'),/\/api\/device\/display/);
});

test('cancel while local preview creation is pending never proceeds to commit',async()=>{
 const f=fixture();let release;f.deferCreate(new Promise(resolve=>release=resolve));f.ctx.openAction('message',-1,{title:'想保存的话',text:'完整正文'});const pending=f.ctx.confirmAction();f.ctx.closeAction();release({id:'late-preview',status:'previewed'});await pending;assert.equal(f.ctx.getPending(),null);assert.equal(f.calls.filter(([path])=>path==='/api/action').length,1);assert.equal(f.calls.some(([path])=>path.endsWith('/commit')),false);assert.ok(f.refresh.includes('tasks'));
});

test('an older calendar preview without a time can still be confirmed locally using its existing id',async()=>{
 const f=fixture(),action={id:'legacy-calendar',session_id:'one',kind:'calendar',status:'previewed',title:'未设时间的本机安排',detail:'旧内容',when_text:''};f.setActions([action]);f.ctx.openSavedAction(action);await f.ctx.confirmAction();assert.equal(f.calls.some(([path])=>path==='/api/action'),false);const commit=f.calls.find(([path])=>path==='/api/action/legacy-calendar/commit');assert.ok(commit);assert.deepEqual(JSON.parse(commit[1].body),{real:false});
});
