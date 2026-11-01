const connectionContext = require("./helpers/connection-context.cjs");
// Exercise the shipped source entry handlers against synthetic metadata only.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/app.js','utf8');
function clip(a,b){const i=source.indexOf(a),j=source.indexOf(b,i);assert.ok(i>=0&&j>i);return source.slice(i,j);}
function element(){const classes=new Set();return{innerHTML:'',textContent:'',value:'',disabled:false,
  classList:{add:(...xs)=>xs.forEach(x=>classes.add(x)),remove:(...xs)=>xs.forEach(x=>classes.delete(x)),contains:x=>classes.has(x)},
  querySelectorAll(){return[];},focus(){},insertAdjacentHTML(_position,html){this.innerHTML+=html;}};}
function setup(handler=async()=>({sources:[]})){
 const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
 const state={session:{id:'existing'},messages:[{role:'user',text:'已经说过的经历'}],memories:[],realSource:null};
 const calls=[],actions=[];let generation=0;
 const context=connectionContext({$,state,wizard:{pendingSource:null},els:{onboarding:element()},
  api:async(path,opts)=>{calls.push({path,opts});return handler(path,opts);},esc:String,
  prepareSourceDialog(){actions.push('open-source-dialog');},clearCredentialForms(){generation++;},
  beginCredentialRequest(){return {generation:++generation,controller:new AbortController()};},
  credentialRequestCurrent:request=>request.generation===generation,
  showWz:step=>actions.push('step:'+step),renderFeishuAccount:()=>actions.push('feishu-account'),renderFeishuPicker:()=>actions.push('feishu-picker'),
  renderGitPicker(){throw Error('unrelated connector must not open');},renderGmailReal(){throw Error('unrelated source');},renderNotionReal(){throw Error('unrelated source');},
  openLocalFiles:()=>actions.push('local-file-picker-mounted'),startLarkAuth:()=>actions.push('start-feishu-auth'),
  closeSourceDialog:()=>actions.push('close-source-dialog'),renderInsights:()=>actions.push('show-reviewed-read'),
  activeTurn:null,queuedTurns:[],turnQueue:[],markCredentialStart:()=>"marker",finishCredentialStart(){},enterSession:()=>actions.push('connected'),AbortController,Error});
 vm.runInContext('let larkConnectedThisPage=false;'+clip('  function larkCanChooseDocuments()', '  function reserveLarkAuthWindow()')+
  clip('  const STATUS_LABEL = ', '  async function openRealSource(')+clip('  async function openRealSource(', '  function renderGitPicker(')+
  clip('  async function readConfirmedSource()', '  async function startRealSource(')+
  clip('  async function openCompanionSource(', '  async function boot()')+
  '\nthis.open=openCompanionSource;this.read=readConfirmedSource;this.markConnected=()=>larkConnectedThisPage=true;this.renderCards=renderRealSources;',context);
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

test('first Feishu entry opens account settings without automatically expanding authorization',async()=>{
 const env=setup(async()=>({sources:[{id:'feishu',status:'needs_auth'}]}));await env.context.open('feishu');
 assert.equal(env.calls.length,0);assert.ok(env.actions.includes('feishu-account'));assert.ok(!env.actions.includes('start-feishu-auth'));
});

test('an existing single document still opens account settings and never implies full account access',async()=>{
 const env=setup(async()=>({sources:[{id:'feishu',status:'ready'}]}));env.context.markConnected();await env.context.open('feishu');
 assert.ok(env.actions.includes('feishu-account'));assert.ok(!env.actions.includes('feishu-picker'));assert.equal(env.calls.length,0);
 assert.equal(env.context.wizard.pendingSource,null);assert.equal(env.state.messages[0].text,'已经说过的经历');
});

test('calendar immediately shows the scope and waits for explicit consent before reading',async()=>{
 const env=setup(async path=>path.endsWith('/read')
  ?{ok:true,preview_id:'calendar-preview',connector:{id:'apple_calendar',name:'日历'},items:[]}:{session:{id:'existing'}});
 const pending=env.context.open('calendar');
 assert.equal(env.calls.length,0);assert.equal(env.context.wizard.pendingSource,'apple_calendar');
 assert.match(env.$('#read-head').innerHTML,/过去 7 天/);assert.doesNotMatch(env.$('#read-head').innerHTML,/先看看可用状态/);
 assert.equal(env.$('#wz-read').textContent,'授权');await pending;await env.context.read();
 assert.equal(env.calls.length,2);assert.equal(env.calls[0].path,'/api/onboarding/real/read');
 assert.equal(JSON.parse(env.calls[0].opts.body).source_id,'apple_calendar');assert.equal(env.calls[1].path,'/api/onboarding/real/start');assert.ok(env.actions.includes('connected'));
 assert.equal(env.state.session.id,'existing');
});

test('opening another source replaces the calendar scope without a pending metadata request',async()=>{
 const env=setup();await env.context.open('calendar');await env.context.open('rokid');
 assert.match(env.$('#read-items').innerHTML,/没有连接设备/);assert.equal(env.calls.length,0);
 assert.equal(env.context.wizard.pendingSource,null);assert.equal(env.state.session.id,'existing');
});

test('legacy source cards show actual account enablement independently from CLI login and snapshots',()=>{
 const e=setup(),sources=[{id:'feishu',status:'ready',name:'飞书',hint:'已授权'}];e.context.renderCards(sources);assert.match(e.$('#reco-list').innerHTML,/>待连接</);assert.match(e.$('#reco-list').innerHTML,/>连接<\/button>/);assert.doesNotMatch(e.$('#reco-list').innerHTML,/已授权/);
 e.context.markConnected();e.context.renderCards(sources);assert.match(e.$('#reco-list').innerHTML,/>待连接</);
 e.state.feishuAccount={enabled:true};e.context.renderCards(sources);assert.match(e.$('#reco-list').innerHTML,/>✓ 已连接</);assert.match(e.$('#reco-list').innerHTML,/>管理连接<\/button>/);
});
