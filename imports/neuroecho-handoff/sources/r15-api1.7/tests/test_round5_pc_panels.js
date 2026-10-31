const connectionContext = require("./helpers/connection-context.cjs");
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const src=fs.readFileSync('web/app.js','utf8');
function clip(a,b){const x=src.indexOf(a),y=src.indexOf(b,x);assert.ok(x>=0&&y>x);return src.slice(x,y)}
function element(){
 const c=new Set();let html='',controls=[];
 return {value:'',textContent:'',classList:{add:x=>c.add(x),remove:x=>c.delete(x),toggle:(x,b)=>b?c.add(x):c.delete(x)},
  set innerHTML(value){html=value;controls=[];
   // Build the card nodes affected by syncAppsSourceControls, rather than
   // pretending innerHTML is automatically updated when a DOM child changes.
   const card=/<div class="app-card">.*?<span class="status"[^>]*>(.*?)<\/span><\/div><button([^>]*data-app-source="([^"]+)"[^>]*)>(.*?)<\/button><\/div>/g;
   for(const match of html.matchAll(card)){
    const attrs=Object.fromEntries([...match[2].matchAll(/data-([\w-]+)="([^"]*)"/g)].map(x=>[x[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase()),x[2]]));
    const status={textContent:match[1]},wrapper={querySelector:selector=>selector==='.status'?status:null};
    controls.push({dataset:attrs,textContent:match[4],status,attributes:{},closest:selector=>selector==='.app-card'?wrapper:null,setAttribute(k,v){this.attributes[k]=v}});
   }
  },get innerHTML(){return html},
  addEventListener(k,f){this[k]=f},focus(){this.focused=true},querySelectorAll(selector){return selector==='[data-app-source]'?controls:[]},
  control(id){return controls.find(node=>node.dataset.appSource===id)}
 }
}
function fixture(){const n=new Map(),$=id=>{if(!n.has(id))n.set(id,element());return n.get(id)},calls=[],opened=[],state={session:{id:'one'},tab:'today',nextStep:{step:'另一面板的旧建议'}};let background=false,handler;
const ctx=connectionContext({$,$$:()=>[],pairedDevicesPanel:null,state,els:{input:element(),bmNote:element(),bmNext:element()},encodeURIComponent,esc:x=>String(x||''),connectedSources:x=> (x || state.context)?.sources || [],sourceDisplayName:x=>x.title,sourceListMarkup:()=>'',bindSourceRemoval(){},openCompanionSource:id=>opened.push(id),openSavedAction:x=>opened.push(x.id),openAction:kind=>opened.push(kind),actionStatusLabel:x=>x.status,loadTaskActions(){},loadAudit(){},loadMetrics(){},loadData(){},openBookmarkModal(){ctx.els.bmNext.value=state.nextStep.step},api:async(path,opt={})=>{calls.push([path,opt]);if(handler)return handler(path,opt);if(path.startsWith('/api/session/'))return{session:{id:'one'},memories:background?[{status:'confirmed',text:'确认的偏好'}]:[],context:{sources:background?[{id:'source',title:'用户选择的资料'}]:[]}};if(path.startsWith('/api/actions?'))return{actions:[{id:'saved',session_id:'one',kind:'message',title:'本机草稿',status:'previewed'}]};if(path.startsWith('/api/next-step?'))return{step:'本卡自己的建议'};if(path.startsWith('/api/lark/account?'))return{enabled:false,ready:true};if(path==='/api/onboarding/sources')return{sources:[{id:'feishu',name:'飞书',status:'needs_auth',blurb:'单篇文档',icon:'飞'}]};throw Error(path)}});
vm.runInContext('let sourceUiEpoch=0,larkConnectedThisPage=false;'+clip('  function larkCanChooseDocuments()', '  function reserveLarkAuthWindow()')+clip('  function switchTab(', '  let todaySources')+clip('  function putTodayDraft(', '  let authPollTimer')+clip('  async function readFeishuAccountState()', '  async function loadRealSources(')+clip('  let appsCatalogRequest', '  async function loadTaskActions(')+'\nObject.assign(this,{loadToday,openApps,syncAppsSourceControls,markConnected:()=>larkConnectedThisPage=true});',ctx);return{ctx,$,calls,opened,state,background:()=>background=true,handle:fn=>handler=fn}}
test('connection directory switches the right tab, preserves composer and checks only real availability',async()=>{const f=fixture();f.ctx.els.input.value='未发草稿';await f.ctx.openApps();assert.equal(f.state.tab,'apps');assert.equal(f.ctx.els.input.value,'未发草稿');assert.deepEqual(f.calls.map(([p])=>p),['/api/onboarding/sources','/api/lark/account?session_id=one']);assert.equal(f.opened.length,0);assert.equal(f.$('#apps-grid').control('feishu').status.textContent,'待连接');assert.equal(f.$('#apps-grid').control('feishu').textContent,'连接');assert.match(f.$('#apps-grid').innerHTML,/尚未可用/)});
test('Today empty state offers real manual actions and suppresses zero-context placeholders',async()=>{const f=fixture();await f.ctx.loadToday();assert.doesNotMatch(f.$('#today-body').innerHTML,/本卡自己的建议|today-bookmark"|today-understand"/);f.$('#today-new-draft').click();f.$('#today-new-reminder').click();assert.deepEqual(f.opened,['message','reminder']);assert.equal(f.calls.some(([,o])=>o.method==='POST'),false)});
test('Today card owns its bookmark step and continuation preserves unsent words without sending',async()=>{const f=fixture();f.background();f.ctx.els.input.value='还没发';await f.ctx.loadToday();f.$('#today-bookmark').click();assert.equal(f.ctx.els.bmNext.value,'本卡自己的建议');f.$('#today-continue').click();assert.equal(f.ctx.els.input.value,'还没发\n本卡自己的建议');assert.equal(f.calls.some(([,o])=>o.method==='POST'),false);assert.match(f.$('#today-body').innerHTML,/本机草稿/)});
test('late catalog response does not replace a newly chosen conversation',async()=>{const f=fixture();let release;f.handle(path=>path.startsWith('/api/lark/account?')?Promise.resolve({enabled:false}):new Promise(r=>release=r));const pending=f.ctx.openApps();f.state.session.id='other';f.$('#apps-grid').innerHTML='新面板';release({sources:[{id:'feishu',name:'旧状态',status:'ready'}]});await pending;assert.equal(f.$('#apps-grid').innerHTML,'新面板')});
test('normal boot uses canonical restore even with obsolete demo and fresh query flags',async()=>{let restored=0,focused=0;const ctx=connectionContext({api:async()=>{throw Error("not part of this boot fixture")},state:{session:null},bind(){},mountPersonaPanels(){},setupCompanionExperience(){},setupDesign(){},setDesignPanel(){},restoreChatLedger(){},keepChatDraft(){},window:{innerWidth:1400,addEventListener(){},XinjiForegroundSync:{draft:()=>({save(){}}),create:()=>async()=>false},XinjiContentUpdates:{mountStatus:()=>()=>{},create:()=>({start(){},stop(){},visibilityChanged(){},check:async()=>false,state:()=>({supported:null})})}},document:{querySelector:()=>null,documentElement:{dataset:{}},addEventListener(){}},restore:async()=>{restored++;ctx.state.session={id:'canonical'}},els:{input:{focus(){focused++},addEventListener(){}}},URLSearchParams,location:{search:'?demo=1&fresh=1'},openApps(){throw Error('no forced directory')}});vm.runInContext(clip('  async function boot()', '\n  boot();')+'\nthis.boot=boot;',ctx);await ctx.boot();assert.equal(restored,1);assert.equal(focused,1);assert.equal(ctx.state.session.id,'canonical');const code=clip('  async function restore()', '  function mountPersonaPanels()');assert.doesNotMatch(code,/getItem\("xinji_session"\)|已恢复|会话 \$\{/);assert.match(code,/api\("\/api\/conversation"\)/)});

test('Feishu account and saved snapshots have independent checkmark states',async()=>{
 const f=fixture();let account={enabled:false,ready:true};
 f.handle(async path=>path.startsWith('/api/lark/account?')?account:{sources:[{id:'feishu',name:'飞书',status:'ready',blurb:'按问题查阅',icon:'飞'}]});
 const control=()=>f.$('#apps-grid').control('feishu');
 await f.ctx.openApps();assert.equal(control().status.textContent,'待连接');assert.equal(control().textContent,'连接');
 f.ctx.markConnected();await f.ctx.openApps();assert.equal(control().status.textContent,'待连接');assert.equal(control().textContent,'连接');
 account={enabled:true,ready:false};await f.ctx.openApps();assert.equal(control().status.textContent,'连接需核对');assert.equal(control().textContent,'管理');
 account={enabled:true,ready:true};await f.ctx.openApps();assert.equal(control().status.textContent,'已启用 · 搜索曾通过验证');assert.equal(control().textContent,'✓');assert.match(control().attributes['aria-label'],/已启用/);await control().onclick();assert.deepEqual(f.opened,['feishu']);
 // A saved snapshot gets its own check but does not assert that the account is enabled.
 account={enabled:false,ready:true};f.state.context={sources:[{connector_id:'feishu',stale:false}]};await f.ctx.openApps();assert.equal(control().status.textContent,'已保存资料快照');assert.equal(control().textContent,'✓');assert.match(control().attributes['aria-label'],/已保存资料快照/);
 account={enabled:true,ready:false};await f.ctx.openApps();assert.equal(control().status.textContent,'已保存资料快照 · 账号需核对');assert.equal(control().textContent,'✓');assert.match(control().attributes['aria-label'],/已保存资料快照/);
 f.state.context.sources[0].stale=true;f.ctx.syncAppsSourceControls();assert.equal(control().status.textContent,'连接需核对');assert.equal(control().textContent,'管理');
 assert.equal(f.calls.some(([,o])=>o.method==='POST'),false);
});

test('account status failure stays unconfirmed while a saved snapshot remains independently visible',async()=>{
 const f=fixture();f.state.context={sources:[{connector_id:'feishu',stale:false}]};
 f.handle(async path=>{if(path.startsWith('/api/lark/account?'))throw Error('offline');return {sources:[{id:'feishu',name:'飞书',status:'ready',icon:'飞'}]}});
 await f.ctx.openApps();const control=f.$('#apps-grid').control('feishu');assert.equal(control.textContent,'✓');assert.equal(control.status.textContent,'已保存资料快照');assert.doesNotMatch(control.attributes['aria-label'],/已启用/);
 f.state.context.sources=[];f.ctx.syncAppsSourceControls();assert.equal(control.textContent,'连接');assert.equal(control.status.textContent,'状态未确认');
});


test('late account response cannot overwrite another conversation account state',async()=>{
 const f=fixture();let release;f.handle(path=>path.startsWith('/api/lark/account?')?new Promise(resolve=>release=resolve):Promise.resolve({sources:[{id:'feishu',name:'飞书',status:'ready'}]}));
 const pending=f.ctx.openApps();f.state.session.id='other';f.state.feishuAccount={enabled:false,ready:true};f.$('#apps-grid').innerHTML='新面板';release({enabled:true,ready:true});await pending;
 assert.equal(f.state.feishuAccount.enabled,false);assert.equal(f.$('#apps-grid').innerHTML,'新面板');
});
