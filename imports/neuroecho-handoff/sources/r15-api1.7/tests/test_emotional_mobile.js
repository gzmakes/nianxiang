// Synthetic onboarding/entry tests: no account, model, filesystem or hardware calls.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const js=fs.readFileSync('web/m.js','utf8'),html=fs.readFileSync('web/m.html','utf8'),css=fs.readFileSync('web/m.css','utf8');
const start=js.indexOf('  let mobileOpeningEntry = '),end=js.indexOf('  const api = ',start);assert.ok(start>=0&&end>start);
function element(){const hidden=new Set(['is-hidden']);return {value:'',innerHTML:'',textContent:'',open:false,isConnected:true,focusCount:0,classList:{add:x=>hidden.add(x),remove:x=>hidden.delete(x),contains:x=>hidden.has(x)},focus(){this.focusCount++},closest(){return null},showModal(){this.open=true},close(){this.open=false}};}
function setup(reply=async()=>({sources:[]})){
 const nodes=new Map(),$=selector=>{if(!nodes.has(selector))nodes.set(selector,element());return nodes.get(selector)};
 const state={session:{id:'same-session'},messages:[]},calls=[],routes=[],shown=[],options=[];
 const welcome={maybeShow:arg=>{welcome.last=arg},open(){welcome.opened=true}},opener=element();$('#m-input').value='已有草稿';
 const ctx=vm.createContext({$,state,wz:{},document:{activeElement:opener},window:{XinjiWelcome:{create:config=>{options.push(config);return welcome},mascotMarkup:'<svg>seed</svg>'}},
  $$:selector=>selector==='[data-m-welcome-close]'?[element(),element()]:[],
  api:async(...args)=>{calls.push(args);return reply(...args)},toast:text=>shown.push(text),esc:s=>String(s??'').replace(/</g,'&lt;'),
  openMobileLocalFiles:()=>routes.push('local_files'),openMobileReal:(...args)=>routes.push(args),openMobileFeishu:()=>routes.push('feishu'),startLarkAuthMobile:()=>routes.push('explicit-authorize'),showWz(){},closeSheet(){}});
 vm.runInContext('let mobileSourceFormEpoch=0;function clearMobileSourceForm(){mobileSourceFormEpoch++;}\n'+js.slice(start,end)+
  '\nthis.entry=openMobileEntry;this.closeRokid=closeMobileRokid;this.invalidate=clearMobileSourceForm;this.closeWizard=closeMobileWizard;this.beginAuth=beginMobileAuthSurface;this.finishAuth=finishMobileAuthSurface;',ctx);
 return {ctx,$,state,calls,routes,shown,options,welcome,opener};
}
test('four direct entries appear in the opening chat, with honest Rokid status',()=>{
 const opening=html.slice(html.indexOf('id="m-chat-empty"'),html.indexOf('id="m-messages"'));
 for(const id of ['feishu','rokid','apple_calendar','local_files'])assert.match(opening,new RegExp('data-m-entry="'+id+'"'));
 assert.match(opening,/飞书/);assert.match(opening,/Rokid 眼镜/);assert.match(opening,/日历/);assert.match(opening,/本机电脑/);assert.match(opening,/待联调/);
 assert.equal((opening.match(/data-prompt=/g)||[]).length,3);
});
test('first launch has no welcome popup or reopening entry',()=>{
 assert.doesNotMatch(html,/id="m-companion-welcome"|id="m-reopen-welcome"/);
 assert.doesNotMatch(js,/getMobileWelcome|maybeShowMobileWelcome|m-persona-welcome/);
});
test('the shared helper remains available for source and auth focus isolation',()=>{
 assert.match(js,/function getMobileWizard/);assert.match(js,/function getMobileAuthSurface/);
 assert.ok(html.indexOf('companion-welcome.js')<html.indexOf('/static/m.js'));
});
test('local computer entry only opens the explicit file picker',async()=>{
 const e=setup();await e.ctx.entry('local_files',e.opener);assert.deepEqual(e.routes,['local_files']);assert.equal(e.calls.length,0);assert.equal(e.$('#m-input').value,'已有草稿');
});
test('calendar entry opens scope confirmation and never reads the calendar itself',async()=>{
 const e=setup();await e.ctx.entry('apple_calendar',e.opener);assert.equal(e.calls.length,0);assert.equal(e.routes[0][0],'apple_calendar');assert.match(e.routes[0][2].reads[0],/未来 7 天/);assert.equal(e.$('#m-input').value,'已有草稿');
});
test('ready Feishu entry checks status then opens only the existing single-document picker',async()=>{
 const e=setup(async()=>({sources:[{id:'feishu',status:'ready'}]}));await e.ctx.entry('feishu',e.opener);assert.deepEqual(e.calls.map(call=>call[0]),['/api/onboarding/sources?force=1']);assert.deepEqual(e.routes,['feishu']);
});
test('unready Feishu explains the connection without starting authorization or reading a document',async()=>{
 const e=setup(async()=>({sources:[{id:'feishu',status:'needs_auth',hint:'授权已过期'}]}));await e.ctx.entry('feishu',e.opener);assert.equal(e.routes.length,0);assert.equal(e.calls.length,1);assert.match(e.$('#m-read-head').innerHTML,/先聊聊/);assert.match(e.$('#m-read-head').innerHTML,/授权已过期/);
});
test('Feishu authorization is available only behind an explicit scope-described click',async()=>{
 const e=setup(async()=>({sources:[{id:'feishu',status:'needs_auth'}]}));await e.ctx.entry('feishu',e.opener);assert.deepEqual(e.routes,[]);assert.match(e.$('#m-read-head').innerHTML,/单篇飞书文档.*核对权限/);e.$('#m-entry-feishu-authorize').onclick();assert.deepEqual(e.routes,['explicit-authorize']);assert.equal(e.calls.length,1);
});
test('a late Feishu status cannot reopen a source after leaving or switching session',async()=>{
 for(const action of ['leave','switch']){let resolve;const waiting=new Promise(r=>resolve=r);const e=setup(async()=>waiting);const run=e.ctx.entry('feishu',e.opener);if(action==='leave')e.ctx.invalidate();else e.state.session={id:'other'};resolve({sources:[{id:'feishu',status:'ready'}]});await run;assert.equal(e.routes.length,0);}
});
test('Rokid opens a static outline and restores focus without any device/API request',async()=>{
 const e=setup();await e.ctx.entry('rokid',e.opener);assert.equal(e.$('#m-rokid-outline').open,true);assert.equal(e.calls.length,0);assert.equal(e.routes.length,0);e.ctx.closeRokid();assert.equal(e.$('#m-rokid-outline').open,false);assert.equal(e.opener.focusCount,1);assert.equal(e.$('#m-input').value,'已有草稿');
 assert.match(html,/当前不会连接眼镜，也不会请求设备权限/);
});
test('mobile surfaces are opaque, warm and respect reduced motion',()=>{
 assert.match(css,/--paper:\s*#f8f3ea/);assert.match(css,/--accent:\s*#ad654c/);assert.doesNotMatch(css,/--accent:\s*#2f6bff/);assert.match(css,/\.onboard\s*\{[^}]*background:\s*#f8f3ea/s);assert.match(css,/prefers-reduced-motion:\s*reduce/);
 assert.ok(html.indexOf('companion-welcome.js')<html.indexOf('/static/m.js'));
});

function lifecycle(e){
 const surfaces=[];
 e.ctx.window.XinjiWelcome.create=options=>{
  let opened=false,previous=[];
  const surface={options,isOpen:()=>opened,open(){opened=true;previous=options.backgrounds.map(node=>({node,inert:node.inert}));for(const {node}of previous)node.inert=true;options.dialog.classList.remove('is-hidden')},close(){if(!opened)return;opened=false;for(const {node,inert}of previous)node.inert=inert;options.dialog.classList.add('is-hidden');options.onClose?.()}};
  surfaces.push(surface);return surface;
 };return surfaces;
}
test('source wizard isolates background and closes without changing draft or session',async()=>{
 const e=setup(),surfaces=lifecycle(e);await e.ctx.entry('local_files',e.opener);assert.equal(surfaces[0].options.storageKey,null);assert.equal(e.$('#m-app').inert,true);e.ctx.closeWizard();assert.notEqual(e.$('#m-app').inert,true);assert.equal(e.$('#m-input').value,'已有草稿');assert.equal(e.state.session.id,'same-session');
});
test('auth suspension removes the wizard trap, then resumes only the same source context',async()=>{
 const e=setup(),surfaces=lifecycle(e);await e.ctx.entry('local_files',e.opener);e.ctx.beginAuth();assert.equal(surfaces[0].isOpen(),false);assert.equal(surfaces[1].isOpen(),true);assert.equal(e.$('#m-app').inert,true);assert.equal(e.ctx.finishAuth(),true);assert.equal(surfaces[1].isOpen(),false);assert.equal(surfaces[0].isOpen(),true);assert.equal(e.$('#m-input').value,'已有草稿');assert.equal(e.calls.length,0);
});
test('auth closing after leaving the originating context never revives its source layer',async()=>{
 const e=setup(),surfaces=lifecycle(e);await e.ctx.entry('local_files',e.opener);e.ctx.beginAuth();e.ctx.invalidate();assert.equal(e.ctx.finishAuth(),false);assert.equal(surfaces[0].isOpen(),false);assert.equal(surfaces[1].isOpen(),false);assert.notEqual(e.$('#m-app').inert,true);
});
