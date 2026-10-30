// Exercise the actual Web boot publication and existing renderers, not a copy
// of their logic. All service records and views are disposable synthetic data.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/app.js','utf8');
function clip(a,b){const start=source.indexOf(a),end=source.indexOf(b,start);assert.ok(start>=0&&end>start,a);return source.slice(start,end);}
function node(){return {value:'',innerHTML:'',textContent:'',className:'',classList:{add(){},remove(){},toggle(){}},addEventListener(){},focus(){},querySelectorAll(){return[]}};}
async function fixture(tab='today'){
 const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id)},calls=[],pending=[];
 let options;const state={session:{id:'one'},messages:[],memories:[],tab,companionBoundary:{canRefresh:()=>true,acceptSnapshot:()=>true},delivery:{pending:()=>false,invalidateReads(){calls.push('invalidate-delivery')}}};
 const ctx=vm.createContext({state,$,$$:()=>[],sourceUiEpoch:0,contentMutationEpoch:0,contentMutationCount:0,activeTurn:null,turnQueue:[],queuedTurns:[],chatBlocked:false,memoryDrafts:new Map(),
  followups:{canRefresh:()=>true,acceptSnapshot:()=>true},mood:{canRefresh:()=>true,acceptSnapshot:()=>true},
  document:{hidden:false,documentElement:{dataset:{}},activeElement:{matches:()=>false},querySelector:()=>null,addEventListener(){}},
  window:{innerWidth:1280,addEventListener(){},XinjiForegroundSync:{draft:()=>({save(){}}),create:()=>async()=>false},XinjiContentUpdates:{mountStatus:()=>()=>{},create:opts=>{options=opts;return{start(){}}}},XinjiActionCards:{html:actions=>actions.map(a=>a.title).join('|'),bind(){}}},
  els:{input:node(),bookmarkCard:node()},URLSearchParams,location:{search:''},encodeURIComponent,esc:value=>String(value??''),
  bind(){},mountPersonaPanels(){},setupCompanionExperience(){},setupDesign(){},restore:async()=>{},restoreChatLedger(){},keepChatDraft(){},setDesignPanel(){},
  renderMessages(){},renderUnderstanding(){},renderMemoryList(){},renderConnectedSources(){},renderStarterBar(){},renderNextStep(){calls.push('next-step')},
  connectedSources:context=>context?.sources||[],sourceDisplayName:item=>item.title,sourceListMarkup:sources=>sources.map(s=>s.title).join('|'),bindSourceRemoval(){},
  actionStatusLabel:action=>action.status,commitBookmark(){},openSavedAction(){},checkActionStatus(){},toast(){},
  api:path=>new Promise(resolve=>pending.push({path,resolve})),
 });
 vm.runInContext(clip('  function renderBookmark()', '  async function loadPlugins()')+clip('  async function loadToday(', '  let authPollTimer')+clip('  async function loadTaskActions(', '  async function loadData()')+clip('  async function boot()', '\n  boot();')+'\nthis.boot=boot;this.loadToday=loadToday;this.loadTaskActions=loadTaskActions;',ctx);
 await ctx.boot();return{ctx,state,$,calls,pending,get options(){return options}};
}
function snapshot(extra={}){return {conversation:{session:{id:'one'},messages:[],memories:[],bookmark:null,context:null},moods:{moods:[]},followups:{followups:[]},boundary:{},actions:{actions:[]},next:{step:'',rationale:''},...extra};}
test('late pre-publication Today read cannot revive withdrawn text after cursor publication',async()=>{
 const f=await fixture();const old=f.ctx.loadToday();assert.equal(f.pending.length,3);
 assert.equal(f.options.apply(snapshot()),true);assert.equal(f.ctx.sourceUiEpoch,1);
 for(const r of f.pending)r.resolve(r.path.startsWith('/api/session/')?{session:{id:'one'},memories:[{status:'confirmed',text:'WITHDRAWN_OLD'}],context:null}:r.path.startsWith('/api/actions')?{actions:[]}:{step:'WITHDRAWN_OLD'});
 await old;assert.doesNotMatch(f.$('#today-body').innerHTML,/WITHDRAWN_OLD/);assert.match(f.$('#today-body').innerHTML,/先从一件小事开始/);
});
test('stable update immediately replaces current task and bookmark views without unchecked GET',async()=>{
 const f=await fixture('bookmark'),fresh=snapshot();fresh.conversation.bookmark={note:'新书签',choice:'新取舍',next_step:'新下一步',status:'draft'};fresh.actions={actions:[{id:'new',title:'另一端新增的动作',status:'previewed'}]};
 assert.equal(f.options.apply(fresh),true);assert.match(f.ctx.els.bookmarkCard.innerHTML,/新书签/);assert.match(f.$('#task-actions').innerHTML,/另一端新增的动作/);assert.equal(f.pending.length,0);
});
test('an old task GET cannot overwrite the accepted action snapshot',async()=>{
 const f=await fixture('bookmark'),old=f.ctx.loadTaskActions(),fresh=snapshot();fresh.actions={actions:[{id:'new',title:'当前动作',status:'previewed'}]};f.options.apply(fresh);
 assert.equal(f.pending.length,1);f.pending[0].resolve({actions:[{id:'old',title:'过期动作',status:'unknown'}]});await old;assert.equal(f.$('#task-actions').innerHTML,'当前动作');
});
test('data summary updates sources while the model settings draft is left untouched',async()=>{
 const f=await fixture('data'),fresh=snapshot();f.$('#ms-model').value='未保存的模型名称';fresh.conversation.context={sources:[{title:'保留来源B'}]};
 f.options.apply(fresh);assert.match(f.$('#data-body').innerHTML,/保留来源B/);assert.equal(f.$('#ms-model').value,'未保存的模型名称');assert.equal(f.pending.length,0);
});
test('cross-device publication adopts the refreshed next step and invalidates prior source reads',async()=>{
 const f=await fixture('memory'),fresh=snapshot();f.state.nextStep={step:'旧来源的建议'};fresh.next={step:'新建议',rationale:'当前依据'};
 f.options.apply(fresh);assert.equal(f.state.nextStep.step,'新建议');assert.ok(f.calls.includes('next-step'));assert.ok(f.calls.includes('invalidate-delivery'));
});
