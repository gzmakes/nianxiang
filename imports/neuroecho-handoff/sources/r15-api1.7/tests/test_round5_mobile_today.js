// Exercise the shipped Today handler with delayed synthetic responses. No accounts.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/m.js','utf8');
function clip(a,b){const i=source.indexOf(a),j=source.indexOf(b,i);assert.ok(i>=0&&j>i);return source.slice(i,j);}
function element(){const classes=new Set();return{innerHTML:'',textContent:'',value:'',disabled:false,
 classList:{add:(...xs)=>xs.forEach(x=>classes.add(x)),remove:(...xs)=>xs.forEach(x=>classes.delete(x)),contains:x=>classes.has(x),toggle:(x,on)=>on?classes.add(x):classes.delete(x)},
 querySelectorAll:()=>[],addEventListener(type,fn){this['on'+type]=fn;},focus(){this.focused=true;}};}
function setup(){
 const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
 const sheet=$('#m-sheet');sheet._xinjiEpoch=7;sheet._xinjiKind='today';
 const state={session:{id:'original',mode:'empty'},messages:[],memories:[],context:{sources:[]}},calls=[],actions=[];
 let resolve,reject;const waiting=new Promise((ok,no)=>{resolve=ok;reject=no;});
 const context=vm.createContext({$,state,followups:{mount(){},stop(){}},window:{},esc:String,Date,encodeURIComponent,
  api:async(path,opts)=>{calls.push({path,opts});if(path.startsWith('/api/session/'))return waiting;if(path.startsWith('/api/next-step'))return{step:'合成的当前建议',rationale:'合成依据'};if(path.startsWith('/api/actions'))return{actions:[]};return{sources:[]};},
  send:(...args)=>actions.push(['send',...args]),openMobileAction:(...args)=>actions.push(['action',...args]),openSheet:(...args)=>actions.push(['sheet',...args]),closeSheet:()=>actions.push(['close-sheet']),toast:()=>{},
  mobileSources:(context=state.context)=>context?.sources||[],mobileSourceTitle:source=>source.title||source.label||'',
 });
 vm.runInContext(clip('  async function renderTodayMobile()', '  async function renderPersonaMobile()')+'\nthis.run=renderTodayMobile;',context);
 return{context,$,sheet,state,calls,actions,resolve,reject};
}
const sessionData=()=>({session:{id:'original'},bookmark:null,memories:[],context:{sources:[]}});
test('H5 Today cannot overwrite a memory sheet opened while its requests were pending',async()=>{
 const e=setup(),pending=e.context.run();e.sheet._xinjiEpoch++;e.sheet._xinjiKind='understand';e.$('#m-sheet-body').innerHTML='后来打开的记忆页';e.resolve(sessionData());await pending;
 assert.equal(e.$('#m-sheet-body').innerHTML,'后来打开的记忆页');assert.equal(e.actions.length,0);
});
test('H5 Today cannot paint an old session into a newly selected conversation',async()=>{
 const e=setup(),pending=e.context.run();e.state.session={id:'new-session'};e.$('#m-sheet-body').innerHTML='新对话的任务';e.resolve(sessionData());await pending;
 assert.equal(e.$('#m-sheet-body').innerHTML,'新对话的任务');assert.equal(e.state.session.id,'new-session');assert.equal(e.actions.length,0);
});
test('a late Today error does not replace a task sheet or trigger a silent action',async()=>{
 const e=setup(),pending=e.context.run();e.sheet._xinjiEpoch++;e.sheet._xinjiKind='tasks';e.$('#m-sheet-body').innerHTML='后来打开的任务';e.reject(Error('合成网络中断'));await pending;
 assert.equal(e.$('#m-sheet-body').innerHTML,'后来打开的任务');assert.equal(e.actions.length,0);assert.ok(e.calls.every(call=>!call.opts?.method||call.opts.method==='GET'));
});
test('opening Today reads saved context and never silently sends, authorizes, or writes an action',async()=>{
 const e=setup(),pending=e.context.run(),data=sessionData();
 data.context.sources=[{id:'source-a',title:'合成生活笔记',label:'本机资料',stale:false},{id:'source-b',title:'合成日程',label:'日历',stale:false}];
 data.memories=[{id:'memory-a',text:'确认过的合成偏好',status:'confirmed'}];e.resolve(data);await pending;
 assert.equal(e.actions.length,0);assert.ok(e.calls.some(call=>call.path.startsWith('/api/actions?session_id=original')));
 assert.ok(e.calls.every(call=>!call.opts?.method||call.opts.method==='GET'));assert.ok(!e.calls.some(call=>/\/auth\/|\/commit|\/api\/chat/.test(call.path)));
 assert.match(e.$('#m-sheet-body').innerHTML,/合成生活笔记|2\s*份来源/);
});
test('Today continuation keeps the current draft, carries the actual bookmark into chat, and waits for Send',async()=>{
 const e=setup(),pending=e.context.run(),data=sessionData();e.$('#m-input').value='已有未发送的心事';
 data.bookmark={id:'bookmark',note:'合成停留点',next_step:'继续整理这张卡里的准确下一步'};e.resolve(data);await pending;
 const before=e.calls.length;assert.equal(typeof e.$('#m-today-continue').onclick,'function');e.$('#m-today-continue').onclick();
 const draft=e.$('#m-input').value;assert.ok(draft.includes('已有未发送的心事'));assert.ok(draft.includes(data.bookmark.next_step));assert.ok(draft.indexOf('已有未发送的心事')<draft.indexOf(data.bookmark.next_step));
 assert.equal(e.$('#m-input').focused,true);assert.ok(e.actions.some(action=>action[0]==='close-sheet'));assert.ok(!e.actions.some(action=>action[0]==='send'||action[0]==='action'));assert.equal(e.calls.length,before);assert.equal(e.state.session.id,'original');
});
test('Today without a bookmark brings the displayed candidate back to the composer without sending',async()=>{
 const e=setup(),pending=e.context.run();e.resolve(sessionData());await pending;e.$('#m-today-continue').onclick();
 assert.ok(e.$('#m-input').value.includes('合成的当前建议'));assert.ok(!e.actions.some(action=>action[0]==='send'));assert.ok(e.calls.every(call=>!call.opts?.method||call.opts.method==='GET'));
});
for(const [id,target] of [['#m-today-tasks','tasks'],['#m-today-memories','understand'],['#m-today-sources','more']]){
 test(`${id} opens its real destination and a stale card cannot open it for another session`,async()=>{
  const e=setup(),pending=e.context.run();e.resolve(sessionData());await pending;
  const button=e.$(id);assert.equal(typeof button.onclick,'function');button.onclick();assert.equal(e.actions[0][0],'sheet');assert.equal(e.actions[0][1],target);
  e.actions.length=0;e.state.session={id:'other'};button.onclick();assert.equal(e.actions.length,0);
 });
}
