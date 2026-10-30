// PC multi-source UI uses synthetic labels/summaries only; no account or raw document reads.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const src=fs.readFileSync('web/app.js','utf8');
function clip(a,b){const i=src.indexOf(a),j=src.indexOf(b,i);assert.ok(i>=0&&j>i);return src.slice(i,j)}
function element(){const hidden=new Set();return{innerHTML:'',textContent:'',value:'',disabled:false,classList:{add:x=>hidden.add(x),remove:x=>hidden.delete(x),toggle:(x,on)=>on?hidden.add(x):hidden.delete(x),contains:x=>hidden.has(x)},querySelectorAll:()=>[],focus(){}}}
function fixture(extra={}){
 const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)};
 const sources=[{id:'source-a',connector_id:'local_files',label:'本地文件 · 用户选择',title:'合成周记A',items:[{title:'周记A'}],insights:[{title:'A的理解',text:'A内容'}],starters:['先聊A']},{id:'source-b',connector_id:'local_files',label:'本地文件 · 用户选择',title:'合成计划B',items:[{title:'计划B'}],insights:[{title:'B的理解',text:'B内容'}],starters:['先聊B']}];
 const state={session:{id:'s',mode:'connector',source_label:'两份合成来源'},context:{sources},messages:[{id:'local-user',role:'user',text:'尚在发送的原话'}],memories:[{text:'旧候选'}],tab:'memory'};
 const toasts=[],confirms=[],entered=[];
 const ctx=vm.createContext({$,state,els:{sourceLabel:element(),input:element()},esc:value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])),toast:s=>toasts.push(s),confirm:s=>{confirms.push(s);return true},api:async()=>({}),renderAll(){},renderInsightPanel(){},renderNextStep(){},loadNextStep(){},loadAudit(){},
  enterSession(data,opts){entered.push([data,opts]);state.session=data.session;state.memories=data.memories;state.context=data.context;if(!opts.preserveDrafts)state.messages=data.messages},...extra});
 ctx.window = {XinjiDialogs: {confirm: async options => ctx.confirm(options.message)}};
 vm.runInContext('let sourceUiEpoch=0;'+clip('  function connectedSources(', '  function openInsightBookmark(')+clip('  async function revokeSource()', '  function resetAll()')+'\nthis.sources=connectedSources;this.markup=sourceListMarkup;this.memoryLabel=memorySourceLabel;this.entries=insightEntries;this.bind=bindSourceRemoval;this.render=renderConnectedSources;this.revoke=revokeSelectedSource;this.all=revokeSource;this.bump=()=>sourceUiEpoch++;',ctx);
 return{ctx,state,sources,$,toasts,confirms,entered};
}
test('same-connector sources retain distinct document titles without exposing raw text',()=>{
 const env=fixture();env.sources[0].raw_text='RAW-MUST-NOT-RENDER';env.sources[1].title='<合成计划B>';
 const html=env.ctx.markup(env.ctx.sources());assert.match(html,/合成周记A/);assert.match(html,/&lt;合成计划B&gt;/);assert.doesNotMatch(html,/RAW-MUST-NOT-RENDER|<合成计划B>/);
 assert.match(html,/data-source-remove="0"/);assert.match(html,/data-source-remove="1"/);
 assert.equal(env.ctx.entries()[0].sourceLabel,'本地文件 · 用户选择 · 合成周记A');
});
test('an explicit empty sources array wins over legacy fields; old contexts still display one source',()=>{
 const env=fixture();assert.equal(env.ctx.sources({sources:[],items:[{title:'旧字段'}]},env.state.session).length,0);
 const old=env.ctx.sources({connector_id:'feishu',items:[{title:'合成旧文档'}]}, {id:'s',mode:'paste',source_label:'飞书文档'});
 assert.equal(old.length,1);assert.equal(old[0].id,null);assert.match(env.ctx.markup(old),/合成旧文档/);
 assert.equal(env.ctx.sources({}, {id:'empty',mode:'empty'}).length,0);
});
test('stale sources remain individually removable but do not supply insight actions',()=>{
 const env=fixture();env.sources[0].stale=true;assert.match(env.ctx.markup(env.sources),/暂停用于回复/);assert.equal(env.ctx.entries().length,1);assert.match(env.ctx.entries()[0].sourceLabel,/合成计划B/);
});
test('individual removal sends only its source id and preserves draft messages and other source context',async()=>{
 const env=fixture(),calls=[],original=env.state.messages;env.ctx.api=async(path,opt)=>{calls.push([path,opt]);return path==='/api/source/revoke'?{ok:true,cleaned:1,review_required:2}:{session:{id:'s'},messages:[{text:'服务端原话'}],memories:[{text:'仍保留的手动记忆'}],context:{sources:[env.sources[1]]}}};
 env.ctx.els.input.value='未发送的输入草稿';await env.ctx.revoke('source-a');
 assert.deepEqual(JSON.parse(calls[0][1].body),{session_id:'s',source_id:'source-a'});assert.equal(calls[1][0],'/api/session/s');assert.equal(env.entered[0][1].preserveDrafts,true);
 assert.equal(env.state.messages,original);assert.equal(env.ctx.els.input.value,'未发送的输入草稿');assert.equal(env.state.context.sources[0].id,'source-b');assert.match(env.confirms[0],/合成周记A.*其他已接入来源/);assert.match(env.$('#chat-error').textContent,/2 条来源待核对/);
});
test('all-source removal is explicit and omits source_id',async()=>{
 const env=fixture(),calls=[];env.ctx.api=async(path,opt)=>{calls.push([path,opt]);return path==='/api/source/revoke'?{ok:true,cleaned:2}:{session:{id:'s'},messages:[],memories:[],context:{sources:[]}}};await env.ctx.all();assert.deepEqual(JSON.parse(calls[0][1].body),{session_id:'s'});assert.match(env.confirms[0],/全部已接入来源/);
});
test('a late removal refresh cannot replace another conversation',async()=>{
 const env=fixture();env.ctx.api=async path=>{if(path==='/api/source/revoke')return{ok:true,cleaned:1};env.state.session={id:'other'};env.state.memories=[{text:'其他会话记忆'}];return{session:{id:'s'},memories:[],context:{sources:[]}}};await env.ctx.revoke('source-a');assert.equal(env.entered.length,0);assert.equal(env.state.memories[0].text,'其他会话记忆');
});
test('a newer source state prevents an older refresh from overwriting it',async()=>{
 const env=fixture();env.ctx.api=async path=>{if(path==='/api/source/revoke')return{ok:true,cleaned:1};env.ctx.bump();return{session:{id:'s'},memories:[],context:{sources:[]}}};await env.ctx.revoke('source-a');assert.equal(env.entered.length,0);assert.equal(env.state.context.sources.length,2);
});
test('duplicate removal clicks do not issue concurrent writes',async()=>{
 let release;const pending=new Promise(r=>release=r),env=fixture(),calls=[];env.ctx.api=async(path,opt)=>{calls.push([path,opt]);return path==='/api/source/revoke'?pending:{session:{id:'s'},memories:[],context:{sources:[env.sources[1]]}}};const first=env.ctx.revoke('source-a');await env.ctx.revoke('source-b');assert.equal(calls.length,1);release({ok:true,cleaned:1});await first;assert.equal(calls.length,2);
});
test('a button from an old conversation cannot remove a source in the new one',async()=>{
 const env=fixture(),button={dataset:{sourceRemove:'0'}},box={querySelectorAll:()=>[button]};env.ctx.bind(box,env.sources,'s');env.state.session={id:'other'};let calls=0;env.ctx.api=async()=>{calls++;return{}};button.onclick();assert.equal(calls,0);
});
test('each source has its own remove control and the global control says all',()=>{
 const env=fixture();env.ctx.render();assert.match(env.$('#connected-sources').innerHTML,/合成周记A/);assert.equal(env.$('#revoke-btn').textContent,'移除全部已接入来源');assert.equal(env.ctx.els.sourceLabel.textContent,'已接入 2 份来源');
});
test('onboarding keeps sources optional and no longer instructs users to revoke before adding',()=>{
 const copy=clip('  function prepareSourceDialog()', '  async function openCompanionSource(');assert.match(copy,/其他已接入来源.*分别移除/);assert.doesNotMatch(copy,/仅支持一个来源|更换前.*撤回/);assert.match(src,/preserveDrafts: true/);
});

test('memory provenance resolves the exact attachment title without inventing a reply citation',()=>{
 const env=fixture();assert.match(env.ctx.memoryLabel({source:'本地文件 · 用户选择',source_attachment_id:'source-a'}),/合成周记A/);assert.match(env.ctx.memoryLabel({source:'本地文件 · 用户选择',source_attachment_id:'source-b'}),/合成计划B/);
 assert.equal(env.ctx.memoryLabel({source:'用户手动添加'}),'用户手动添加');assert.doesNotMatch(clip('  function renderMessages(', '  function memByKind('),/citations\s*=/);
});

test('real enterSession refresh preserves pending words, composer draft and current view for the same session',()=>{
 const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)},words=[{id:'local-1',role:'user',text:'正在发送的话'}];
 const input=element();input.value='输入框还没发的草稿';const state={session:{id:'s'},messages:words,memories:[],tab:'memory'},tabs=[];
 const ctx=vm.createContext({$,state,els:{input,onboarding:element(),app:element(),sourceLabel:element(),sessionMeta:element()},localStorage:{setItem(){}},location:{search:''},URLSearchParams,Date,clearTimeout(){},setTimeout(){},clearCredentialForms(){},loadEngine(){},setOrb(){},renderAll(){},loadAudit(){},loadNextStep(){},switchTab:name=>tabs.push(name),loadToday(){},renderInsightPanel(){},loadCarryover(){},bindIntro(){},showIntro(){}});
 vm.runInContext('let onboardingExitTimer=null,sourceUiEpoch=0;'+clip('  function enterSession(', '  async function startSession(')+'\nthis.enter=enterSession;',ctx);
 const remaining={sources:[{id:'b',title:'剩余资料'}]};ctx.enter({session:{id:'s'},messages:[{text:'权威已保存的旧消息'}],memories:[{text:'权威剩余记忆'}],context:remaining},{preserveDrafts:true});
 assert.equal(state.messages,words);assert.equal(input.value,'输入框还没发的草稿');assert.equal(state.memories[0].text,'权威剩余记忆');assert.equal(state.context,remaining);assert.equal(tabs[0],'memory');
});

test('insight bookmarks keep the exact attachment id and reject a withdrawn source',async()=>{
 const bmNote=element(),bmChoice=element(),bmNext=element(),modal=element(),env=fixture({els:{sourceLabel:element(),input:element(),bmNote,bmChoice,bmNext,modal},renderBookmark(){},switchTab(){}});
 vm.runInContext(clip('  function openInsightBookmark(', '  let pendingAction')+clip('  async function saveBookmark()', '  async function commitBookmark()')+'\nthis.bookmark=openInsightBookmark;this.save=saveBookmark;',env.ctx);
 env.ctx.bookmark(1,'source-b');assert.equal(env.state.bmSource.source_attachment_id,'source-b');assert.match(env.state.bmSource.source_label,/合成计划B/);
 const calls=[];env.ctx.api=async(path,opts)=>{calls.push([path,opts]);return{id:'bookmark-b'}};await env.ctx.save();assert.equal(JSON.parse(calls[0][1].body).source_attachment_id,'source-b');
 env.state.context.sources=[env.sources[0]];await env.ctx.save();assert.equal(calls.length,1);assert.match(env.toasts.at(-1),/来源已移除/);
});
test('an old insight index cannot bind the different source that moved into that position',()=>{
 const env=fixture({els:{sourceLabel:element(),input:element(),bmNote:element(),bmChoice:element(),bmNext:element(),modal:element()}});vm.runInContext(clip('  function openInsightBookmark(', '  let pendingAction')+'\nthis.bookmark=openInsightBookmark;',env.ctx);
 env.state.context.sources=[env.sources[1]];env.ctx.bookmark(0,'source-a');assert.equal(env.state.bmSource,undefined);assert.match(env.toasts[0],/来源已变化/);
});

test('a correction refreshes scoped source status without touching conversation drafts',async()=>{
 const env=fixture({renderStarterBar(){}}),original=env.state.messages;env.ctx.els.input.value='保留草稿';
 env.ctx.api=async()=>({session:{id:'s',source_label:'两份资料'},context:{sources:[{...env.sources[0],stale:true},env.sources[1]]}});
 vm.runInContext(clip('  function showMemoryContextNotice()', '  // ---------------- memory actions')+'\nthis.notice=showMemoryContextNotice;this.refresh=refreshSourceContext;',env.ctx);
 env.ctx.notice();await new Promise(setImmediate);assert.equal(env.state.context.sources[0].stale,true);assert.equal(env.ctx.entries().length,1);assert.equal(env.state.messages,original);assert.equal(env.ctx.els.input.value,'保留草稿');assert.match(env.$('#chat-error').textContent,/相关来源.*其他已接入来源/);
});
test('late correction metadata cannot replace a newly selected conversation',async()=>{
 let release;const pending=new Promise(r=>release=r),env=fixture({renderStarterBar(){}});env.ctx.api=()=>pending;
 vm.runInContext(clip('  function showMemoryContextNotice()', '  // ---------------- memory actions')+'\nthis.refresh=refreshSourceContext;',env.ctx);const running=env.ctx.refresh();env.state.session={id:'other'};const other={sources:[{id:'other-source'}]};env.state.context=other;release({session:{id:'s'},context:{sources:[]}});await running;assert.equal(env.state.context,other);
});
