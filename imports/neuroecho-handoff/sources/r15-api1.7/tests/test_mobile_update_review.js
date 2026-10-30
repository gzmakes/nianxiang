// Exercise the real H5 boot + shared coordinator with disposable records.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/m.js','utf8');
const boot=source.slice(source.indexOf('  async function boot()'),source.indexOf('\n  boot();'));
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function element(){const classes=new Set();return{value:'',textContent:'',innerHTML:'',dataset:{},scrollTop:160,
 classList:{add:(...xs)=>xs.forEach(x=>classes.add(x)),remove:(...xs)=>xs.forEach(x=>classes.delete(x)),contains:x=>classes.has(x)},addEventListener(){}};}
async function fixture({changesSupported=true}={}){
 const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
 const hosts=Array.from({length:2},()=>{const status=element(),button=element(),host=element();host.querySelector=key=>key==='[data-update-status]'?status:button;return{host,status,button};});
 const sheet=$('#m-sheet');sheet.classList.add('is-hidden');sheet._xinjiEpoch=1;sheet._xinjiKind=null;
 let cursor='c0',deferSnapshot=null,sync,modal=false,offline=false;const calls=[],renders=[];
 const state={session:{id:'one'},messages:[],memories:[],sourceGeneration:0,companionBoundary:{canRefresh:()=>true,acceptSnapshot:()=>true},delivery:{pending:()=>false,invalidateReads(){}}};
 const ctx=vm.createContext({state,$,AbortController,URLSearchParams,location:{search:''},setTimeout:()=>1,clearTimeout(){},
  document:{hidden:false,querySelector:()=>modal?{}:null,querySelectorAll:()=>hosts.map(h=>h.host),addEventListener(){}},
  window:{addEventListener(){},XinjiMood:{entryValid:()=>true},XinjiContactContract:{validBoundary:()=>true}},
  contentMutationEpoch:0,contentMutationCount:0,mActiveTurn:null,mTurnQueue:[],mQueuedTurns:[],mChatBlocked:false,mobileManualMemoryOperation:null,onMemAction:{drafts:new Map()},
  followups:{canRefresh:()=>true},mood:{canRefresh:()=>true},bind(){},setupMobileDesign(){},restore:async()=>true,restoreMobileChatLedger(){},keepMobileChatDraft(){},
  renderAll(){},renderStarters(){},renderMessages(){},renderNext(){},renderUnderstanding(){renders.push(state.memories.map(m=>m.text));$('#m-sheet-body').scrollTop=0;},
  api:async(path,opts={})=>{calls.push({path,opts});if(offline)throw Error('synthetic-offline');
   if(path==='/api/capabilities')return{features:{conversation_change_cursor:changesSupported}};
   if(path.startsWith('/api/conversation/changes')){const after=new URLSearchParams(path.split('?')[1]||'').get('after');return{service_instance_id:'service',conversation_id:'one',cursor,reset_required:!after,domains:after===cursor?[]:['memories']};}
   if(path==='/api/conversation'){if(deferSnapshot)await deferSnapshot;return{session:{id:'one'},messages:[],memories:[{id:'mem',text:'fresh-'+cursor}],bookmark:null,context:null};}
   if(path.startsWith('/api/moods'))return{moods:[]};if(path.startsWith('/api/followups'))return{followups:[]};if(path.startsWith('/api/actions'))return{actions:[]};return{};
  }});
 vm.runInContext(fs.readFileSync('web/client-sync.js','utf8'),ctx);
 const create=ctx.window.XinjiContentUpdates.create;
 ctx.window.XinjiContentUpdates.create=options=>sync=create(options);
 ctx.window.XinjiForegroundSync.draft=()=>({save(){}});
 vm.runInContext(boot+'\nthis.boot=boot;',ctx);await ctx.boot();await flush();
 return{ctx,state,$,sheet,hosts,calls,renders,sync,change(){cursor='c'+(Number(cursor.slice(1))+1);},open(kind='understand'){sheet._xinjiEpoch++;sheet._xinjiKind=kind;sheet.classList.remove('is-hidden');},modal(v){modal=v;},offline(v){offline=v;},defer(p){deferSnapshot=p;}};
}
test('memory sheet shows pending feedback without automatic replacement; explicit GET review preserves chat and scroll',async()=>{
 const f=await fixture();f.open();f.$('#m-input').value='合成未发聊天';f.change();
 await f.sync.checkNow();assert.equal(f.renders.length,0);assert.equal(f.sync.state().cursor,'c0');
 for(const h of f.hosts){assert.equal(h.host.dataset.updateState,'pending');assert.match(h.status.textContent,/正在编辑/);}
 await f.hosts[1].button.onclick();assert.equal(f.renders.length,1);assert.equal(f.renders[0][0],'fresh-c1');assert.equal(f.sync.state().cursor,'c1');
 assert.equal(f.$('#m-input').value,'合成未发聊天');assert.equal(f.$('#m-sheet-body').scrollTop,160);assert.equal(f.hosts[1].host.dataset.updateState,'updated');
 assert.ok(f.calls.every(call=>!call.opts.method||call.opts.method==='GET'));f.sync.stop();
});
test('manual review cannot replace a memory editor, prompt, or unrelated form sheet',async()=>{
 for(const guard of ['draft','prompt','form']){const f=await fixture();f.open(guard==='form'?'tasks':'understand');f.change();
  if(guard==='draft')f.ctx.onMemAction.drafts.set('mem','合成修改');if(guard==='prompt')f.modal(true);
  await f.hosts[1].button.onclick();assert.equal(f.renders.length,0);assert.equal(f.sync.state().cursor,'c0');assert.equal(f.hosts[1].host.dataset.updateState,'pending');
  assert.equal(f.calls.filter(c=>c.path==='/api/conversation').length,1);f.sync.stop();
 }
});
test('edit start or sheet change during a checked snapshot invalidates the whole publication',async()=>{
 for(const change of ['draft','sheet']){const f=await fixture();f.open();f.change();let release;f.defer(new Promise(r=>release=r));
  const pending=f.hosts[1].button.onclick();await flush();if(change==='draft')f.ctx.onMemAction.drafts.set('mem','保留编辑');else{f.sheet._xinjiEpoch++;f.sheet._xinjiKind='tasks';}
  release();await pending;assert.equal(f.renders.length,0);assert.equal(f.sync.state().cursor,'c0');assert.equal(f.state.memories[0].text,'fresh-c0');f.sync.stop();
 }
});
test('both update bars show a network error inside the still-open sheet',async()=>{
 const f=await fixture();f.open('settings');f.offline(true);await f.hosts[1].button.onclick();
 for(const h of f.hosts){assert.equal(h.host.dataset.updateState,'offline');assert.match(h.status.textContent,/暂时没能/);}
 assert.equal(f.sheet._xinjiKind,'settings');assert.equal(f.sync.state().cursor,'c0');f.sync.stop();
});
test('explicit check bypasses idle debounce while retaining single-flight ownership',async()=>{
 const f=await fixture();f.open();f.change();let release;f.defer(new Promise(r=>release=r));
 const first=f.hosts[1].button.onclick(),second=f.hosts[1].button.onclick();assert.equal(first,second);await flush();
 assert.equal(f.calls.filter(c=>c.path==='/api/conversation').length,2);release();await first;assert.equal(f.sync.state().cursor,'c1');f.sync.stop();
});
test('old-service explicit fallback reports failed GET as offline rather than inventing a pending update',async()=>{
 const f=await fixture({changesSupported:false});f.open();f.$('#m-input').value='旧服务未发草稿';f.offline(true);
 await f.hosts[1].button.onclick();assert.equal(f.hosts[1].host.dataset.updateState,'offline');assert.match(f.hosts[1].status.textContent,/暂时没能/);
 assert.equal(f.$('#m-input').value,'旧服务未发草稿');assert.equal(f.calls.filter(c=>c.path==='/api/conversation').length,1);
 assert.ok(f.calls.every(call=>!call.opts.method||call.opts.method==='GET'));f.sync.stop();
});
