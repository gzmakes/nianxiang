// Exercise the shipped source entry handlers against synthetic metadata only.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/app.js','utf8');
function clip(a,b){const i=source.indexOf(a),j=source.indexOf(b,i);assert.ok(i>=0&&j>i);return source.slice(i,j);}
function element(){const classes=new Set();return{innerHTML:'',textContent:'',value:'',disabled:false,
  classList:{add:(...xs)=>xs.forEach(x=>classes.add(x)),remove:(...xs)=>xs.forEach(x=>classes.delete(x)),contains:x=>classes.has(x)},
  focus(){},insertAdjacentHTML(_position,html){this.innerHTML+=html;}};}
function setup(handler=async()=>({sources:[]})){
 const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
 const state={session:{id:'existing'},messages:[{role:'user',text:'已经说过的经历'}],memories:[],realSource:null};
 const calls=[],actions=[];let generation=0;
 const context=vm.createContext({$,state,wizard:{pendingSource:null},els:{onboarding:element()},
  api:async(path,opts)=>{calls.push({path,opts});return handler(path,opts);},esc:String,
  prepareSourceDialog(){actions.push('open-source-dialog');},clearCredentialForms(){generation++;},
  beginCredentialRequest(){return {generation:++generation,controller:new AbortController()};},
  credentialRequestCurrent:request=>request.generation===generation,
  showWz:step=>actions.push('step:'+step),renderFeishuPicker:()=>actions.push('feishu-picker'),
  renderGitPicker(){throw Error('unrelated connector must not open');},renderGmailReal(){throw Error('unrelated source');},renderNotionReal(){throw Error('unrelated source');},
  openLocalFiles:()=>actions.push('local-file-picker-mounted'),startLarkAuth:()=>actions.push('start-feishu-auth'),
  closeSourceDialog:()=>actions.push('close-source-dialog'),renderInsights:()=>actions.push('show-reviewed-read'),
  AbortController,Error});
 vm.runInContext(clip('  async function openRealSource(', '  function renderGitPicker(')+
  clip('  async function readConfirmedSource()', '  async function startRealSource(')+
  clip('  async function openCompanionSource(', '  async function boot()')+
  '\nthis.open=openCompanionSource;this.read=readConfirmedSource;',context);
 return{context,$,state,calls,actions,clear:()=>context.clearCredentialForms()};
}

test('Rokid opens a truthful unconnected outline and performs zero API or device operations',async()=>{
 const env=setup();await env.context.open('rokid');
 assert.match(env.$('#read-head').innerHTML,/待真机联调/);assert.match(env.$('#read-items').innerHTML,/没有连接设备/);
 assert.equal(env.calls.length,0);assert.equal(env.context.wizard.pendingSource,null);
 assert.equal(env.$('#wz-read').classList.contains('is-hidden'),true);assert.equal(env.state.session.id,'existing');
});

test('local entry only opens file selection; no files are read or sent by the source card',async()=>{
 const env=setup();await env.context.open('local');
 assert.ok(env.actions.includes('local-file-picker-mounted'));assert.equal(env.calls.length,0);
 assert.equal(env.state.messages[0].text,'已经说过的经历');assert.equal(env.state.session.id,'existing');
});

test('unauthorized Feishu only checks metadata and waits for an explicit authorization click',async()=>{
 const env=setup(async()=>({sources:[{id:'feishu',status:'needs_auth'}]}));await env.context.open('feishu');
 assert.deepEqual(env.calls.map(c=>c.path),['/api/onboarding/sources']);
 assert.ok(!env.actions.includes('start-feishu-auth'));assert.match(env.$('#read-items').innerHTML,/没有读取飞书内容/);
 env.$('#welcome-feishu-authorize').onclick();assert.ok(env.actions.includes('start-feishu-auth'));
 assert.equal(env.calls.length,1);
});

test('ready Feishu opens the single-document picker without reading documents or searching automatically',async()=>{
 const env=setup(async()=>({sources:[{id:'feishu',status:'ready'}]}));await env.context.open('feishu');
 assert.ok(env.actions.includes('feishu-picker'));assert.equal(env.calls.length,1);
 assert.equal(env.calls[0].path,'/api/onboarding/sources');assert.equal(env.context.wizard.pendingSource,null);
});

test('calendar waits on its scope screen until the user explicitly consents to read',async()=>{
 const env=setup(async path=>path==='/api/onboarding/sources'
  ?{sources:[{id:'apple_calendar',status:'needs_click',name:'日历',reads:['未来7天日程']}]}
  :{ok:true,connector:{id:'apple_calendar',name:'日历'},items:[],understanding:{facts:[],inferences:[],questions:[]},insights:[]});
 await env.context.open('calendar');assert.equal(env.calls.length,1);
 assert.equal(env.context.wizard.pendingSource,'apple_calendar');assert.match(env.$('#read-items').innerHTML,/确认后才开始读取/);
 assert.equal(env.$('#wz-read').textContent,'同意并读取');await env.context.read();
 assert.equal(env.calls.length,2);assert.equal(env.calls[1].path,'/api/onboarding/real/read');
 assert.equal(JSON.parse(env.calls[1].opts.body).source_id,'apple_calendar');assert.ok(env.actions.includes('show-reviewed-read'));
 assert.equal(env.state.session.id,'existing');
});

test('a late metadata response cannot replace a newly selected conversation or its source screen',async()=>{
 let resolve;const env=setup(()=>new Promise(r=>resolve=r));const pending=env.context.open('feishu');
 const initial=env.$('#read-head').innerHTML;env.state.session={id:'other'};
 resolve({sources:[{id:'feishu',status:'ready'}]});await pending;
 assert.equal(env.$('#read-head').innerHTML,initial);assert.ok(!env.actions.includes('feishu-picker'));
 assert.equal(env.state.session.id,'other');
});

test('opening Rokid while a source status is pending prevents its late Feishu state from painting over it',async()=>{
 let resolve;const env=setup(()=>new Promise(r=>resolve=r));const pending=env.context.open('feishu');
 await env.context.open('rokid');const rokid=env.$('#read-items').innerHTML;
 resolve({sources:[{id:'feishu',status:'needs_auth'}]});await pending;
 assert.equal(env.$('#read-items').innerHTML,rokid);assert.equal(env.$('#welcome-feishu-authorize').onclick,undefined);
});
