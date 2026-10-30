// Isolated tests of shipped UI functions; no user data, network or external auth.
const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const pc=fs.readFileSync('web/app.js','utf8'), mobile=fs.readFileSync('web/m.js','utf8');
function clip(src,a,b) { const x=src.indexOf(a), y=src.indexOf(b,x); assert.ok(x>=0&&y>x); return src.slice(x,y); }
function element(initial=[]) {const s=new Set(initial);return {classList:{add:(...v)=>v.forEach(x=>s.add(x)),remove:(...v)=>v.forEach(x=>s.delete(x)),toggle:(x,f)=>{if(f===undefined)f=!s.has(x); f?s.add(x):s.delete(x)},contains:x=>s.has(x)},textContent:'',value:'',style:{},setAttribute(){},focus(){},remove(){}};}
function nodeset(){const n=new Map(); return {n,$:s=>{if(!n.has(s))n.set(s,element());return n.get(s)}}}

test('desktop source catalog reopens in the sidebar and preserves the current conversation and draft',()=>{
  const {$}=nodeset(), onboarding=element(['is-hidden']), app=element(['is-hidden']);let next=0;const timers=new Map();
  const ctx=vm.createContext({$,window:{},state:{},els:{onboarding,app,sourceLabel:element(),sessionMeta:element(),input:element()},localStorage:{setItem(){}},location:{search:''},URLSearchParams,Date,
    clearCredentialForms(){},setTimeout:fn=>{const id=++next;timers.set(id,fn);return id},clearTimeout:id=>timers.delete(id),loadEngine(){},setOrb(){},renderAll(){},loadAudit(){},loadNextStep(){},switchTab:name=>{ctx.state.tab=name;},loadToday(){},renderInsightPanel(){},loadCarryover(){},bindIntro(){},showIntro(){},loadCatalog(){},loadRealSources(){},showWz(){}});
  vm.runInContext(clip(pc,'  // ---------------- onboarding ----------------','  async function startSession')+'\nthis.enterSession=enterSession;',ctx);
  vm.runInContext(clip(pc,'  async function openApps()','  async function loadAppsCatalog()')+clip(pc,'  function prepareSourceDialog()','  async function openCompanionSource(')+'\nthis.showOnboarding=showOnboarding;',ctx);
  ctx.enterSession({session:{id:'test-session'},messages:[],memories:[]});ctx.els.input.value='未发送的心事';ctx.showOnboarding();for(const fn of timers.values())fn();
  assert.equal(onboarding.classList.contains('is-hidden'),true);assert.equal(onboarding.classList.contains('leaving'),false);
  assert.equal(ctx.state.tab,'apps');assert.equal(app.classList.contains('is-hidden'),false);assert.equal(ctx.state.session.id,'test-session');
  assert.equal(ctx.els.input.value,'未发送的心事');
});

test('desktop restores conversation even if device status fails',async()=>{
  const {$}=nodeset();let removed=false;const ctx=vm.createContext({$,state:{},els:{onboarding:element(),app:element(),sourceLabel:element(),sessionMeta:element(),deviceNote:element()},
    localStorage:{getItem:()=> 'test-session',setItem(){},removeItem:()=>{removed=true}},api:async path=>{if(path==='/api/device/frame')throw Error('down');assert.equal(path,'/api/conversation');return {session:{id:'test-session'},messages:[],memories:[]}},
    loadEngine(){},setOrb(){},renderAll(){},renderInsightPanel(){},showResumeBanner(){},loadCarryover(){},loadAudit(){},switchTab(){},loadToday(){},loadNextStep(){},startPolling(){}});
  vm.runInContext(clip(pc,'  function showRestoreFailure()','  function mountPersonaPanels()')+'\nthis.restore=restore;',ctx);
  assert.equal(await ctx.restore(),true);assert.equal(ctx.state.session.id,'test-session');assert.equal(removed,false);assert.match(ctx.els.deviceNote.textContent,/设备状态暂不可用/);
});

for(const [label,source,start,end,queue,local,active,blocked,dispatch,inputId] of [
 ['desktop',pc,'  function pendingMessages(','  function stopWaiting()','queuedTurns','turnQueue','activeTurn','chatBlocked','dispatchTurn',null],
 ['mobile',mobile,'  function mPendingMessages(','  // ---------- boot ----------','mQueuedTurns','mTurnQueue','mActiveTurn','mChatBlocked','dispatchSend','#m-input']]){
 test(`${label} 429 returns unsent messages and preserves draft`,async()=>{
  const {n,$}=nodeset();let message='';const input=element();if(inputId)n.set(inputId,input);input.value='正在输入';
  const p1={id:'local-1',role:'user',text:'第一条',sessionId:'s'},p2={id:'local-2',role:'user',text:'第二条',sessionId:'s'};
  const ctx=vm.createContext({$,state:{session:{id:'s'},messages:[p1,p2],memories:[]},els:{input,messages:{insertAdjacentHTML(){},scrollTop:0,scrollHeight:0}},
    window:{},chatLedger:{returnDraft(){}},mChatLedger:{returnDraft(){}},memoryProposal:{shouldRequest(){return false},offer(){}}, chatTransport:{send:async()=>{const e=Error('本次会话已达到 40 轮预算上限');e.status=429;e.notSent=true;throw e}}, mChatTransport:{send:async()=>{const e=Error('本次会话已达到 40 轮预算上限');e.status=429;e.notSent=true;throw e}},toast:s=>{message=s},setOrb(){},chatScroll:{render(fn){fn()}},renderMessages(){},renderAll(){},loadAudit(){},loadNextStep(){},touchLastSeen(){},setTimeout(){},clearTimeout(){},Date,Map,Set});
  const init=`let ${queue}=[{sessionId:'s',parts:[${JSON.stringify(p1)}],standalone:true},{sessionId:'s',parts:[${JSON.stringify(p2)}],standalone:true}],${local}=[],${active}=null,${blocked}=false;`+(label==='desktop'?'let chatStorageBlocked=false,turnTimer=null, localTurnId=0; const displayedTurns=new Map(), uncertainTurns=new Map();':'let mChatStorageBlocked=false,mTurnTimer=null, mLocalTurnId=0; const mDisplayedTurns=new Map(), mUncertainTurns=new Map();');
  vm.runInContext(init+'\n'+clip(source,start,end)+`\nthis.run=${dispatch};this.getBlocked=()=>${blocked};`,ctx);await ctx.run();
  assert.equal(input.value,'第一条\n第二条\n正在输入');assert.match(message,/未发送/);assert.match($(inputId?'#m-chat-error':'#chat-error').textContent,/40 轮.*未发送/);assert.equal(ctx.getBlocked(),false);assert.equal(ctx.state.messages.length,0);
 });
}

test('available sources and simulated hardware are clearly labeled',()=>{
 assert.match(clip(mobile,'  async function renderTodayMobile()','  async function renderPersonaMobile()'),/份已接入来源/);
 for(const s of [pc,mobile]){assert.match(s,/模拟显示（无真实设备）/);assert.match(s,/模拟按钮事件/);assert.doesNotMatch(s,/实体按钮已按下/)}
});


test('mobile task tab opens the task sheet', () => {
 const {$}=nodeset(); let opened=false; const ctx=vm.createContext({$,pairedDevicesPanel:null,followups:{mount(){},stop(){}},renderUnderstanding(){},renderBookmark(){opened=true},renderTodayMobile(){},renderPersonaMobile(){},renderDevice(){},renderMore(){}});
 $('#m-sheet').querySelector=() => $('#update-context');
 vm.runInContext(clip(mobile,'  function openSheet(', '  async function renderTodayMobile()')+'\nthis.openSheet=openSheet;',ctx);
 ctx.openSheet('tasks'); assert.equal(opened,true); assert.equal($('#m-sheet-title').textContent,'任务');
 assert.match($('#update-context').textContent,/正在填写的部分不会被更新替换/);
});


for (const [label, begin, end, previewButton, startButton, tokenInput, urlInput, prefix] of [
 ['gmail','  function renderGmailReal()', '  function renderFeishuPicker()', '#wz-gmail-preview','#wz-gmail-start','#wz-gmail-password','#wz-gmail-address','gmail'],
 ['notion','  function renderNotionReal()', '  function renderInsights()', '#wz-notion-preview','#wz-notion-start','#wz-notion-token','#wz-notion-url','notion']
]) test(`${label} starts from one preview without resending credentials`, async()=>{
  const {n,$}=nodeset(); const head=element();head.querySelector=()=>null;head.insertAdjacentHTML=()=>{};n.set('#read-head',head);
  let calls=[],entered=false;
  const store = new Map(); const localStorage={getItem:k=>store.get(k)??null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)};
  const ctx=vm.createContext({$,state:{session:null},AbortController,localStorage,esc:s=>s,api:async(path,opt)=>{calls.push([path,JSON.parse(opt.body)]);return path.endsWith('/preview')?{ok:true,preview_id:'preview-fixture',items:[],title:'x'}:{session:{id:'s'}}},enterSession:()=>{entered=true}});
  vm.runInContext('let activeTurn=null, queuedTurns=[], turnQueue=[];'+clip(pc,'  const credentialPendingKey = ', '  function showWz(n)')+clip(pc,begin,end)+`\nthis.open=render${label==='gmail'?'Gmail':'Notion'}Real;`,ctx);ctx.open();
  $(tokenInput).value='dummy-credential';$(urlInput).value='dummy-value';await $(previewButton).onclick();assert.equal($(tokenInput).value,'');await $(startButton).onclick();
  assert.equal(entered,true);assert.equal(calls[1][0],`/api/${prefix}/start`);assert.deepEqual(calls[1][1],{preview_id:'preview-fixture'});
});

for (const [label,src,start,end,actionVar,fn,prefix] of [
 ['desktop',pc,'  async function confirmAction()', '  function actionStatusLabel(', 'pendingAction','confirmAction',''],
 ['mobile',mobile,'  async function confirmMobileAction()', '  function renderInsights()', 'mobileAction','confirmMobileAction','m-']
]) test(`${label} real calendar validates time and never reports unknown as success`,async()=>{
 const {$}=nodeset();let calls=0, shown=[];const real=$(`#${prefix}action-real`),when=$(`#${prefix}action-when`),button=$(`#${prefix}action-confirm`),result=$(`#${prefix}action-result`);
 real.checked=true;when.value='';$(`#${prefix}action-name`).value='测试';$(`#${prefix}action-message`).value='测试';
 const ctx=vm.createContext({$,state:{session:{id:'s'}},api:async path=>{calls++;return path==='/api/action'?{id:'a'}:{status:'unknown',real:0}},toast:s=>shown.push(s),touchLastSeen(){},loadAudit(){},loadTaskActions(){},loadToday(){}});
 vm.runInContext(`let ${actionVar}={kind:'calendar',sessionId:'s',title:'测试',detail:'测试'};\n`+clip(src,start,end)+`\nthis.run=${fn};`,ctx);
 await ctx.run();assert.equal(calls,0);assert.match(result.textContent,/选择.*时间/);assert.notEqual(button.disabled,true);
 when.value='2026-10-30T10:00';await ctx.run();assert.equal(calls,2);assert.match(result.textContent,/未确认写入.*系统检查/);assert.equal(button.disabled,true);assert.equal(shown.length,0);
});

for (const src of [pc,mobile]) test('Feishu picker rejects app paths and accepts supported document paths',()=>{
 const ctx=vm.createContext({URL});vm.runInContext(clip(src,'  function readableFeishuUrl(', '  const state = ')+'\nthis.readable=readableFeishuUrl;',ctx);
 assert.equal(ctx.readable('https://example.feishu.cn/docx/ABC'),true);
 assert.equal(ctx.readable('https://example.feishu.cn/wiki/ABC'),true);
 assert.equal(ctx.readable('https://example.feishu.link/app/app_ABC'),false);
});

for (const [label,src,start,end,fn,decl] of [
  ['desktop',pc,'  async function confirmFeishuPreview(', '  function renderRealLark()', 'confirmFeishuPreview','let activeTurn=null, queuedTurns=[], turnQueue=[];'],
  ['mobile',mobile,'  async function confirmMobileFeishu(', '  function openMobileFeishu()', 'confirmMobileFeishu','let mActiveTurn=null, mQueuedTurns=[], mTurnQueue=[];']
]) {
  test(`${label} attaches selected preview to the existing session without replacing it`,async()=>{
    let calls=[],entered=null; const hint=element(),button=element();
    const ctx=vm.createContext({state:{session:{id:'existing'}},api:async(path,opt)=>{calls.push([path,JSON.parse(opt.body)]);return {session:{id:'existing'},messages:[{text:'prior'}],memories:[],bookmark:{id:'bookmark'}}},enterSession:d=>entered=d,enterSessionData:d=>entered=d,toast(){}});
    vm.runInContext(decl+'\n'+clip(src,start,end)+`\nthis.run=${fn};`,ctx);
    await ctx.run('https://example.feishu.cn/docx/doc','one-preview',hint,button);
    assert.equal(calls[0][0],'/api/lark/attach');assert.deepEqual(calls[0][1],{session_id:'existing',url:'https://example.feishu.cn/docx/doc',preview_id:'one-preview'});
    assert.equal(entered.session.id,'existing');assert.equal(entered.messages[0].text,'prior');assert.equal(entered.bookmark.id,'bookmark');
  });
  test(`${label} reports an existing source without switching the session`,async()=>{
    const hint=element(),button=element();let entered=false;
    const ctx=vm.createContext({state:{session:{id:'existing'}},api:async()=>{const e=Error('当前会话已有来源；请先撤回来源或新建会话。');e.status=409;throw e},enterSession(){entered=true},enterSessionData(){entered=true},toast(){}});
    vm.runInContext(decl+'\n'+clip(src,start,end)+`\nthis.run=${fn};`,ctx);await ctx.run('https://example.feishu.cn/docx/doc','fixture',hint,button);
    assert.match(hint.textContent,/已有来源/);assert.equal(button.disabled,false);assert.equal(entered,false);assert.equal(ctx.state.session.id,'existing');
  });
  test(`${label} does not attach while a message is pending`,async()=>{
    let calls=0;const hint=element(),button=element(),busy=decl.replace('=null','=({})');
    const ctx=vm.createContext({state:{session:{id:'existing'}},api:async()=>{calls++},enterSession(){},enterSessionData(){},toast(){}});
    vm.runInContext(busy+'\n'+clip(src,start,end)+`\nthis.run=${fn};`,ctx);await ctx.run('https://example.feishu.cn/docx/doc','fixture',hint,button);
    assert.equal(calls,0);assert.match(hint.textContent,/还在发送/);
  });
}
