const connectionContext = require("./helpers/connection-context.cjs");
// One persistent conversation is selected by the server; the client cannot fork it at boot.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/m.js','utf8');
function clip(a,b){const i=source.indexOf(a),j=source.indexOf(b,i);assert.ok(i>=0&&j>i);return source.slice(i,j);}
function element(){const classes=new Set();return{value:'',textContent:'',innerHTML:'',classList:{add:(...xs)=>xs.forEach(x=>classes.add(x)),remove:(...xs)=>xs.forEach(x=>classes.delete(x)),contains:x=>classes.has(x)},focus(){},addEventListener(){}};}
function setup(search='',offline=false){
 const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
 const state={session:null,messages:[],memories:[]},calls=[],reads=[],writes=[],actions=[];let picker;
 const snapshot={session:{id:'canonical',mode:'empty'},messages:[{id:'u',role:'user',text:'已有的连续经历'}],memories:[],bookmark:null,context:{sources:[]}};
 const context=connectionContext({$,state,location:{search},URLSearchParams,localStorage:{getItem:key=>{reads.push(key);return'old-browser-session';},setItem:(key,value)=>writes.push({key,value}),removeItem:key=>actions.push(['remove',key])},
  window:{addEventListener(){},XinjiForegroundSync:{draft:()=>({save(){}}),create:()=>async()=>false},XinjiContentUpdates:{mountStatuses:()=>()=>{},create:()=>({start(){},stop(){},visibilityChanged(){},check:async()=>false,state:()=>({supported:null})})},XinjiFilePicker:{mount:(_head,options)=>{picker=options;}}},document:{querySelector:()=>null,querySelectorAll:()=>[],addEventListener(){}},mActiveTurn:null,mQueuedTurns:[],mTurnQueue:[],
  api:async(path,opts)=>{calls.push({path,opts});if(path==='/api/conversation'){if(offline)throw Error('合成离线');return snapshot;}if(path==='/api/local-files/confirm')return{...snapshot,context:{sources:[{id:'new-source',title:'用户所选资料'}]}};throw Error('unexpected request '+path);},
  clearMobileSourceForm(){},closeLarkAuthMobile(){},closeMobileWizard(){},renderAll(){},loadEngine(){},loadNextStep(){},renderStarters(){},loadCarryover(){},toast(){},bind(){},setupMobileDesign(){},showWz(){},restoreMobileChatLedger(){},keepMobileChatDraft(){},
  showRestoreFailure:()=>actions.push(['failure']),showMobileOnboarding:()=>actions.push(['sources']),startSession:mode=>actions.push(['new-session',mode]),});
 vm.runInContext(clip('  function enterSessionData(', '  async function startSession(')+
  clip('  async function restore()', '  async function showMobileOnboarding()')+
  clip('  async function boot()', '  boot();')+
  clip('  function openMobileLocalFiles()', '  async function readMobileConfirmedSource()')+
  '\nthis.boot=boot;this.openFiles=openMobileLocalFiles;',context);
 return{context,state,calls,reads,writes,actions,$,snapshot,get picker(){return picker;}};
}
for(const query of ['', '?fresh=1','?onboarding=1','?demo=1&debug=1'])test(`normal H5 bootstrap ${query||'(default)'} uses the canonical conversation without client-side session creation`,async()=>{
 const e=setup(query);await e.context.boot();
 assert.equal(e.state.session.id,'canonical');assert.equal(e.state.messages[0].text,'已有的连续经历');assert.equal(e.calls[0].path,'/api/conversation');assert.ok(e.calls.every(call=>!call.opts?.method||call.opts.method==='GET'));
 assert.ok(!e.calls.some(call=>/^\/api\/session(?:\/|$)/.test(call.path)));assert.ok(!e.reads.includes('xinji_session'));assert.ok(!e.actions.some(action=>action[0]==='new-session'||action[0]==='remove'));
 if(query.includes('onboarding'))assert.ok(e.actions.some(action=>action[0]==='sources'));
});
test('an offline canonical lookup cannot silently create a replacement conversation',async()=>{
 const e=setup('',true);await e.context.boot();assert.equal(e.state.session,null);assert.equal(e.calls.length,1);assert.equal(e.calls[0].path,'/api/conversation');assert.ok(!e.actions.some(action=>action[0]==='new-session'));assert.ok(e.actions.some(action=>action[0]==='failure'));
});
test('selected local material attaches to the canonical conversation and retains its existing chat',async()=>{
 const e=setup();await e.context.boot();const before=e.calls.length;e.context.openFiles();assert.equal(e.calls.length,before);assert.equal(e.picker.sessionId,'canonical');
 await e.picker.onConfirm([{name:'合成.txt',text:'用户明确选择的内容'}],'canonical');
 const attach=e.calls.find(call=>call.path==='/api/local-files/confirm');assert.ok(attach);assert.equal(JSON.parse(attach.opts.body).session_id,'canonical');assert.equal(e.state.session.id,'canonical');assert.equal(e.state.messages[0].id,'u');assert.equal(e.state.context.sources[0].id,'new-source');assert.ok(!e.calls.some(call=>call.path==='/api/session'));
});

test('mobile start resumes the canonical conversation without creating a session',async()=>{
 let restores=0;
 const ctx=vm.createContext({restore:async()=>{restores++;return true}});
 vm.runInContext(clip('  async function startSession(', '  // ---------- onboarding wizard (mobile)')+'\nthis.start=startSession;',ctx);
 assert.equal(await ctx.start(),true);
 assert.equal(restores,1);
});
