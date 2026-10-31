// Synthetic H5 source/history UI tests. No real credentials, accounts or devices.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const src=fs.readFileSync('web/m.js','utf8');
function clip(first,last){const a=src.indexOf(first),b=src.indexOf(last,a);assert.ok(a>=0&&b>a);return src.slice(a,b)}
function element(){
 const hidden=new Set();let html='',cache=new Map();
 const el={value:'',textContent:'',disabled:false,focus(){},dataset:{},style:{},classList:{add:x=>hidden.add(x),remove:x=>hidden.delete(x),contains:x=>hidden.has(x),toggle:(x,on)=>on?hidden.add(x):hidden.delete(x)},addEventListener(name,fn){this['on'+name]=fn},querySelectorAll(selector){
  if(cache.has(selector))return cache.get(selector);
  const attr=selector.slice(1,-1),key=attr.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase());
  const rows=[...html.matchAll(new RegExp(attr+'="([^"]*)"','g'))].map(match=>{const row=element();row.dataset[key]=match[1];row.textContent=match[1];return row});cache.set(selector,rows);return rows;
 }};
 Object.defineProperty(el,'innerHTML',{get:()=>html,set:value=>{html=value;cache=new Map()}});return el;
}
function storage(){const values=new Map();return {getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)}}
const source=(id,title)=>({id,connector_id:'local_files',label:'本地文件',title,items:[{title,summary:`${title} 摘要`}],insights:[],starters:[],stale:false,raw_text:'PRIVATE_RAW_SENTINEL'});
const A=source('source-a','第一份计划'),B=source('source-b','第二份计划');
function session(id='s',sources=[A,B]){return {session:{id,mode:'connector',source_label:'已接入资料'},context:sources.length?{sources,items:sources.flatMap(s=>s.items),insights:[]}:null,memories:[{id:'manual',text:'保留的手动记忆'}],messages:[{id:'server-only',text:'服务器消息'}],bookmark:null}}
function setup(handler){
 const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)};
 const initial=session(),state={...initial,messages:[{id:'local-unsent',text:'保留本地消息'}]},calls=[],shown=[],confirms=[],entered=[],counts={clears:0,rendered:0,reloads:0};
 $('#m-input').value='尚未发送的草稿';$('#m-sheet')._xinjiEpoch=1;$('#m-sheet')._xinjiKind='more';
 const ctx=vm.createContext({$,state,followups:{mount(){},stop(){}},localStorage:storage(),location:{reload(){counts.reloads++}},encodeURIComponent,
  esc:s=>String(s??'').replace(/[<>"']/g,c=>({'<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  api:async(...args)=>{calls.push(args);return handler(...args)},confirm:text=>{confirms.push(text);return true},toast:text=>shown.push(text),
  clearMobileSourceForm(){counts.clears++},renderAll(){counts.rendered++},renderStarters(){},loadNextStep(){},loadEngine(){},loadCarryover(){},
  closeSheet(){const sheet=$('#m-sheet');sheet._xinjiEpoch++;sheet._xinjiKind=null;sheet.classList.add('is-hidden')},
  openSheet(kind){$('#m-sheet')._xinjiEpoch++;$('#m-sheet')._xinjiKind=kind},showMobileOnboarding(){},renderBookmark(){},renderUnderstanding(){counts.understanding=(counts.understanding||0)+1}});
 ctx.document = {}; ctx.connectionIntro = {start(){}};
 ctx.window = {XinjiConnectionIntro:{syncBadges(){}},XinjiDialogs: {confirm: async options => ctx.confirm(options.message)}};
 vm.runInContext(clip('  function enterSessionData(', '  async function startSession(')+
  clip('  function mobileSources(', '  // ---------- chat ----------')+
  '\nthis.list=renderMobileSourceList;this.remove=revokeMobileSelectedSource;this.removeAll=revokeMobileSource;this.more=renderMore;this.openHistory=openMobileHistory;this.deleteHistory=deleteMobileHistory;this.enter=enterSessionData;this.insightBookmark=openMobileInsightBookmark;',ctx);
 return {ctx,state,$,calls,shown,confirms,counts};
}
test('H5 lists distinct document titles, exposes per-source removal, and never shows raw text',()=>{
 const e=setup(async()=>({}));e.ctx.list();const html=e.$('#m-connected-sources').innerHTML;
 assert.match(html,/第一份计划/);assert.match(html,/第二份计划/);assert.match(html,/source-a/);assert.match(html,/source-b/);assert.doesNotMatch(html,/PRIVATE_RAW_SENTINEL/);
 assert.equal(e.$('#m-connected-sources').querySelectorAll('[data-msource-remove]').length,2);
});
test('single removal sends source_id and reloads authority without replacing messages or draft',async()=>{
 const e=setup(async path=>path==='/api/source/revoke'?{ok:true,cleaned:2}:session('s',[B]));const messages=e.state.messages;
 await e.ctx.remove('source-a');assert.deepEqual(JSON.parse(e.calls[0][1].body),{session_id:'s',source_id:'source-a'});
 assert.equal(e.calls[1][0],'/api/session/s');assert.equal(e.state.messages,messages);assert.equal(e.$('#m-input').value,'尚未发送的草稿');
 assert.deepEqual(e.state.context.sources.map(s=>s.id),['source-b']);assert.match(e.confirms[0],/第一份计划/);assert.equal(e.state.revokingSource,false);
});
test('remove all omits source_id and preserves surviving manual memory',async()=>{
 const e=setup(async path=>path==='/api/source/revoke'?{ok:true,cleaned:3}:session('s',[]));await e.ctx.removeAll();
 assert.deepEqual(JSON.parse(e.calls[0][1].body),{session_id:'s'});assert.equal(e.state.context,null);assert.equal(e.state.memories[0].id,'manual');
});
test('repeated removal clicks send only one request while pending',async()=>{
 let resolve;const pending=new Promise(r=>resolve=r);const e=setup(async path=>path==='/api/source/revoke'?pending:session('s',[B]));
 const first=e.ctx.remove('source-a');await e.ctx.remove('source-a');assert.equal(e.calls.length,1);resolve({ok:true,cleaned:1});await first;
});
test('a missing source id cannot remove a different source',async()=>{
 const e=setup(async()=>assert.fail('must not call API'));await e.ctx.remove('missing');assert.match(e.shown[0],/已变化/);
});
test('late source refresh cannot overwrite another session',async()=>{
 let resolve;const pending=new Promise(r=>resolve=r);const e=setup(async path=>path==='/api/source/revoke'?{ok:true}:pending);
 const running=e.ctx.remove('source-a');await Promise.resolve();e.state.session={id:'other'};e.state.context={sources:[source('other','其他来源')]};resolve(session('s',[B]));await running;
 assert.equal(e.state.session.id,'other');assert.equal(e.state.context.sources[0].id,'other');
});
test('an older source refresh cannot replace a newer source state in the same session',async()=>{
 let resolve;const pending=new Promise(r=>resolve=r);const e=setup(async path=>path==='/api/source/revoke'?{ok:true}:pending);
 const running=e.ctx.remove('source-a');await Promise.resolve();e.ctx.enter(session('s',[B,source('new','后来接入的资料')]));resolve(session('s',[B]));await running;
 assert.deepEqual(e.state.context.sources.map(item=>item.id),['source-b','new']);
});
test('closing the source sheet does not revive it after removal',async()=>{
 let resolve;const pending=new Promise(r=>resolve=r);const e=setup(async path=>path==='/api/source/revoke'?{ok:true}:pending);
 const running=e.ctx.remove('source-a');await Promise.resolve();e.$('#m-sheet')._xinjiEpoch++;e.$('#m-sheet')._xinjiKind='tasks';e.$('#m-connected-sources').innerHTML='new panel';resolve(session('s',[B]));await running;
 assert.equal(e.$('#m-connected-sources').innerHTML,'new panel');assert.equal(e.state.context.sources[0].id,'source-b');
});
test('refresh failure distinguishes confirmed revoke and retains local sources pending review',async()=>{
 const e=setup(async path=>{if(path==='/api/source/revoke')return {ok:true};throw Error('offline')});await e.ctx.remove('source-a');
 assert.match(e.$('#m-chat-error').textContent,/已撤回.*未能同步/);assert.equal(e.state.context.sources.length,2);assert.equal(e.$('#m-input').value,'尚未发送的草稿');
});
test('review-required notice survives a later same-session source attachment',async()=>{
 const e=setup(async path=>path==='/api/source/revoke'?{ok:true,review_required:2}:session('s',[B]));await e.ctx.remove('source-a');e.ctx.enter(session('s',[B,source('c','新资料')]));
 assert.match(e.$('#m-chat-error').textContent,/2 条来源待核对/);assert.equal(e.$('#m-chat-error').classList.contains('is-hidden'),false);
});
test('legacy flat context retains one removable source',()=>{
 const e=setup(async()=>({}));e.state.context={connector_id:'feishu',items:[{title:'旧版文档'}]};e.ctx.list();assert.match(e.$('#m-connected-sources').innerHTML,/旧版文档/);assert.match(e.$('#m-connected-sources').innerHTML,/data-msource-remove=""/);
});
test('history restore preserves each conversation draft and restores all source data',async()=>{
 const e=setup(async()=>session('target',[B]));e.state.mobileDrafts={target:'目标会话草稿'};await e.ctx.openHistory('target');
 assert.equal(e.state.session.id,'target');assert.equal(e.state.mobileDrafts.s,'尚未发送的草稿');assert.equal(e.$('#m-input').value,'目标会话草稿');assert.equal(e.state.context.sources[0].id,'source-b');
});
test('a late history read cannot override a newer chosen session',async()=>{
 let resolve;const old=new Promise(r=>resolve=r);const e=setup(async path=>path.endsWith('/first')?old:session('second',[B]));
 const first=e.ctx.openHistory('first');await e.ctx.openHistory('second');resolve(session('first',[A]));await first;assert.equal(e.state.session.id,'second');
});
test('closing history before its response keeps the current session',async()=>{
 let resolve;const pending=new Promise(r=>resolve=r);const e=setup(async()=>pending);const run=e.ctx.openHistory('target');e.$('#m-sheet')._xinjiEpoch++;resolve(session('target',[B]));await run;assert.equal(e.state.session.id,'s');
});
test('normal data controls preserve one conversation and expose no history or reset buttons',async()=>{
 const e=setup(async path=>path.startsWith('/api/actions')?{actions:[]}:session());await e.ctx.more();
 const html=e.$('#m-sheet-body').innerHTML;
 assert.doesNotMatch(html,/data-history|data-mdel|m-reset|m-delete/);
 assert.match(html,/m-manage-connect/);assert.match(html,/m-export/);
 assert.ok(!e.calls.some(([path])=>path==='/api/sessions'));
});
test('deleting a historical session invalidates an outstanding restore and does not reload current chat',async()=>{
 let resolve;const pending=new Promise(r=>resolve=r);let requested=false;
 const e=setup(async(path,opts)=>{if(path==='/api/session/old'&&!opts){requested=true;return pending}if(opts?.method==='DELETE')return {ok:true};if(path==='/api/sessions')return {sessions:[]};if(path.startsWith('/api/actions'))return {actions:[]};return session()});
 const restore=e.ctx.openHistory('old');assert.equal(requested,true);await e.ctx.deleteHistory('old',element());resolve(session('old',[A]));await restore;
 assert.equal(e.state.session.id,'s');assert.equal(e.counts.reloads,0);assert.equal(e.calls.filter(([,opts])=>opts?.method==='DELETE').length,1);
});
test('memory provenance and insight bookmarks use the exact attached source id',async()=>{
 const e=setup(async()=>({id:'bookmark'}));vm.runInContext(clip('  function memCard(', '  function renderUnderstanding()')+'\nthis.card=memCard;'+clip('  async function saveBookmark()', '  async function commitBookmark()')+'\nthis.save=saveBookmark;',e.ctx);
 assert.match(e.ctx.card({id:'m',version:1,source:'本地文件',source_attachment_id:'source-b',text:'合成记忆',status:'candidate'},'事实'),/第二份计划/);
 e.ctx.insightBookmark({source_id:'source-b',title:'B的洞察',text:'B的下一步'},'source-b');await e.ctx.save();assert.equal(JSON.parse(e.calls[0][1].body).source_attachment_id,'source-b');
});
test('an old insight from a removed source cannot create a bookmark',()=>{
 const e=setup(async()=>assert.fail('no request'));e.state.context={sources:[B]};e.ctx.insightBookmark({source_id:'source-a',title:'旧洞察',text:'旧建议'},'source-a');assert.match(e.shown[0],/来源已移除或变化/);
});
test('a stale source remains removable but its insight cannot start a new bookmark',()=>{
 const e=setup(async()=>assert.fail('no request'));e.state.context={sources:[{...A,stale:true},B]};e.ctx.list();e.ctx.insightBookmark({source_id:'source-a',title:'待核对洞察',text:'旧建议'},'source-a');
 assert.match(e.$('#m-connected-sources').innerHTML,/待核对/);assert.match(e.shown[0],/待核对/);assert.equal(e.state.mobileBookmarkSourceId,undefined);
});
test('correcting memory refreshes only authority source state and preserves draft/dialogue',async()=>{
 const next=session();next.context.sources=[{...A,stale:true},B];const e=setup(async()=>next);const messages=e.state.messages;e.$('#m-sheet')._xinjiKind='understand';
 vm.runInContext(clip('  async function showMemoryContextNotice()', '  function memGroups()')+'\nthis.notice=showMemoryContextNotice;',e.ctx);await e.ctx.notice();
 assert.equal(e.state.context.sources[0].stale,true);assert.equal(e.state.context.sources[1].stale,false);assert.equal(e.state.messages,messages);assert.equal(e.$('#m-input').value,'尚未发送的草稿');assert.match(e.$('#m-chat-error').textContent,/相关来源/);
});
