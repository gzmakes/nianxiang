// Unit-only account replies and synthetic URLs: no account or document access.
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('web/feishu-account-picker.js', 'utf8');
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
function deferred() { let resolve, reject; const promise = new Promise((r,j) => {resolve=r;reject=j;}); return {promise,resolve,reject}; }
function element() {
  const classes = new Set();
  return {textContent:'',disabled:false,classList:{add:name=>classes.add(name),remove:name=>classes.delete(name),toggle:(name,on) => on ? classes.add(name) : classes.delete(name), contains:name => classes.has(name)}};
}
function setup({reply = async () => ({enabled:false,ready:true,version:1}), sessionId = 'same-dialogue', ensureSession} = {}) {
  const sandbox = {window:{},URL}; vm.runInNewContext(source, sandbox);
  const nodes = new Map(), calls = [], stateChanges = [], events = [], context = {active:true,sessionId};
  const node = key => { if (!nodes.has(key)) nodes.set(key,element()); return nodes.get(key); };
  const container = {isConnected:true, querySelector:node, set innerHTML(value) {this.html=value;}};
  const picker = sandbox.window.XinjiFeishuAccountPicker.mount(container, {api:async(...args) => {calls.push(args);return reply(...args);},
    getSessionId:()=>context.sessionId, isCurrent:()=>context.active,
    ensureSession:async()=>{ events.push('canonical'); const id = ensureSession ? await ensureSession() : 'canonical-dialogue'; context.sessionId = id; return id; },
    onReturn:()=>events.push('return'),onConnected:()=>events.push('connected'),onAuthorize:()=>events.push('authorize'),onSingleDocument:()=>events.push('single'), onManageSources:()=>events.push('manage'),
    onStateChange:data=>stateChanges.push(data)});
  return {picker,container,node,calls,context,events,stateChanges,module:sandbox.window.XinjiFeishuAccountPicker,
    connect:node('.feishu-account-connect'),disconnect:node('.feishu-account-disconnect'),refresh:node('.feishu-account-refresh'),
    authorize:node('.feishu-account-authorize'),status:node('.feishu-account-status')};
}

test('opening reads actual state only; existing CLI permission never silently enables account retrieval', async () => {
  const t = setup(); await flush();
  assert.equal(t.calls.length,1); assert.equal(t.calls[0][0],'/api/lark/account?session_id=same-dialogue');
  assert.equal(t.calls[0][1],undefined); assert.match(t.status.textContent,/授权完成后/); assert.equal(t.connect.disabled,false);
  assert.equal(t.disconnect.classList.contains('is-hidden'),true); assert.equal(t.events.length,0);
  assert.match(t.container.html,/只读你有权访问的文档/);
  assert.match(t.container.html,/此前手动接入的快照/);
});

test('one explicit connect verifies permissions and enables only the same ongoing dialogue', async () => {
  const t=setup({reply:async path => path.endsWith('/connect') ? {ok:true,enabled:true,ready:true,version:2} : {enabled:false,version:1}}); await flush();
  await t.connect.onclick();
  assert.equal(t.calls.length,2); assert.equal(t.calls[1][0],'/api/lark/account/connect');
  assert.deepEqual(JSON.parse(t.calls[1][1].body),{session_id:'same-dialogue',start_intro:true});
  assert.match(t.status.textContent,/已连接/); assert.equal(t.connect.disabled,true);
  assert.equal(t.disconnect.classList.contains('is-hidden'),false); assert.deepEqual(t.events,['connected']);
});

test('the explicit authorization click continues to official OAuth when permission is missing', async () => {
  const t=setup({reply:async path => path.endsWith('/connect') ? {ok:false,error:'需要搜索权限',permission_issue:'user_grant'} : {enabled:false}});await flush();
  await t.connect.onclick(); assert.deepEqual(t.events,['authorize']); assert.match(t.status.textContent,/需要搜索权限/);
  assert.equal(t.authorize.classList.contains('is-hidden'),true);
  assert.equal(t.calls.filter(([path])=>path.endsWith('/connect')).length,1);
});

test('app configuration failures and unverified payloads never claim success or start authorization', async () => {
  for (const data of [{ok:false,error:'应用配置不完整',permission_issue:'app_config'},{ok:true,enabled:false},{status:'success'}]) {
    const t=setup({reply:async path=>path.endsWith('/connect')?data:{enabled:false}});await flush();await t.connect.onclick();
    assert.doesNotMatch(t.status.textContent,/^已连接/);assert.equal(t.events.length,0);assert.equal(t.authorize.classList.contains('is-hidden'),true);
  }
});

test('duplicate connect clicks issue one request; a closed surface cannot be revived by late success', async () => {
  const pending=deferred(), t=setup({reply:async path=>path.endsWith('/connect')?pending.promise:{enabled:false}});await flush();
  const saving=t.connect.onclick();await flush();await t.connect.onclick();
  assert.equal(t.calls.filter(([path])=>path.endsWith('/connect')).length,1);
  const before=t.status.textContent;t.context.active=false;pending.resolve({ok:true,enabled:true});await saving;
  assert.equal(t.status.textContent,before);assert.equal(t.stateChanges.length,1);
});

for (const mode of ['detached','changed-dialogue','disposed']) {
  test(`late account state after ${mode} cannot relabel the current surface`,async()=>{
    const pending=deferred(),t=setup({reply:()=>pending.promise});await flush();
    if(mode==='detached')t.container.isConnected=false;
    else if(mode==='changed-dialogue')t.context.sessionId='different-dialogue';
    else t.picker.dispose();
    pending.resolve({enabled:true,ready:true});await flush();
    assert.match(t.status.textContent,/正在核对/);assert.equal(t.stateChanges.length,0);
  });
}

test('a canonical dialogue is obtained once when needed without creating another conversation or enabling retrieval',async()=>{
  const t=setup({sessionId:null});await flush();assert.deepEqual(t.events,['canonical']);
  assert.equal(t.calls.length,1);assert.equal(t.calls[0][0],'/api/lark/account?session_id=canonical-dialogue');
});

test('disconnect waits for server confirmation and retains the independent snapshot management choice',async()=>{
  const pending=deferred(),t=setup({reply:async path=>path.endsWith('/disconnect')?pending.promise:{enabled:true,ready:true}});await flush();
  const disconnecting=t.disconnect.onclick();await flush();assert.match(t.status.textContent,/正在断开/);
  assert.deepEqual(JSON.parse(t.calls[1][1].body),{session_id:'same-dialogue'});
  pending.resolve({ok:true,enabled:false,version:3});await disconnecting;
  assert.match(t.status.textContent,/授权完成后/);assert.equal(t.connect.disabled,false);
  t.node('.feishu-account-manage').onclick();assert.deepEqual(t.events,['manage']);
});

test('uncertain write outcomes require state verification before another connect can run',async()=>{
  let fail=true;const t=setup({reply:async path=>{if(path.endsWith('/connect')&&fail)throw Error('response lost');return {enabled:false};}});await flush();
  await t.connect.onclick();assert.match(t.status.textContent,/结果尚未确认.*先重新核对状态/);assert.equal(t.connect.disabled,true);
  await t.connect.onclick();assert.equal(t.calls.length,2);fail=false;await t.refresh.onclick();assert.equal(t.connect.disabled,false);
});

test('single document mode remains a separate explicit choice and ends the old account surface',async()=>{
  const t=setup();await flush();t.node('.feishu-account-single').onclick();assert.deepEqual(t.events,['single']);
  await t.connect.onclick();assert.equal(t.calls.length,1);
});

test('actual document provenance renders escaped official links and leaves memory revision citations intact',()=>{
  const t=setup(), render=t.module.renderCitations;
  const message={role:'assistant',citations:[{kind:'feishu_document',title:'<项目> "计划"',url:'https://unit.feishu.cn/docx/SyntheticDoc?from=chat&x=1'},
    {id:'memory-1',version:2,text:'用户确认的记忆'}]};
  const html=render(message);assert.match(html,/查阅 · &lt;项目&gt; &quot;计划&quot;/);assert.match(html,/href="https:\/\/unit.feishu.cn\/docx\/SyntheticDoc\?from=chat&amp;x=1"/);
  assert.match(html,/target="_blank" rel="noopener noreferrer"/);assert.match(html,/data-mem="memory-1".*依据 · v2/);
  assert.doesNotMatch(html,/vundefined|data-mem="undefined"/);
  assert.doesNotMatch(render(message,{includeMemories:false}),/data-mem/);
});

test('pending, user-side, malformed and unsafe provenance never becomes a clickable document or memory',()=>{
  const t=setup(), render=t.module.renderCitations;
  const valid={kind:'feishu_document',title:'Synthetic',url:'https://unit.feishu.cn/wiki/SyntheticDoc'};
  assert.equal(render({role:'assistant',delivery_pending:true,citations:[valid]}),'');
  assert.equal(render({role:'user',citations:[valid]}),'');
  for(const url of ['javascript:alert(1)','http://unit.feishu.cn/docx/Doc','https://feishu.cn.evil.invalid/docx/Doc','https://unit.feishu.cn/drive/Doc','https://u:p@unit.feishu.cn/docx/Doc','https://unit.feishu.cn:8443/docx/Doc','https://unit.feishu.cn/docx/Doc/../../evil','https://unit.feishu.cn./docx/Doc']) {
    assert.equal(render({role:'assistant',citations:[{...valid,url}]}),'',url);
  }
  assert.equal(render({role:'assistant',citations:[null,{kind:'other',id:'x',version:1},{id:'memory'},{id:'memory',version:'1'}]}),'');
});

test('official apex and tenant document links are accepted while lookalike suffixes are rejected',()=>{
  const {documentURL}=setup().module;
  for(const url of ['https://feishu.cn/docx/SyntheticDoc','https://larksuite.com/wiki/SyntheticDoc','https://unit.feishu.cn/docx/SyntheticDoc','https://unit.larksuite.com/docs/SyntheticDoc']) {
    assert.equal(documentURL(url),url);
  }
  for(const url of ['https://feishu.cn.evil.invalid/docx/SyntheticDoc','https://larksuite.com.evil.invalid/wiki/SyntheticDoc','https://evilfeishu.cn/docx/SyntheticDoc','https://evillarksuite.com/docs/SyntheticDoc']) {
    assert.equal(documentURL(url),null);
  }
});

test('Web and H5 canonical account adapters preserve unsent input and never enter a replacement conversation',async()=>{
  for(const mobile of [false,true]) {
    const filename=mobile?'web/m.js':'web/app.js',src=fs.readFileSync(filename,'utf8');
    const start=src.indexOf(mobile?'  function openMobileFeishuAccount()':'  function renderFeishuAccount()');
    const end=src.indexOf(mobile?'  function openMobileFeishu()':'  function renderFeishuPicker()',start);
    const nodes=new Map(),$=key=>{if(!nodes.has(key))nodes.set(key,{...element(),value:'unsent words'});return nodes.get(key);};
    let options, calls=0;const state={session:null},ctx={state,$,els:{onboarding:element()},api:async()=>{calls++;return{session:{id:'canonical'},messages:[],memories:[]};},
      clearCredentialForms(){},clearMobileSourceForm(){},showWz(){},localStorage:{setItem(){}},openMobileFeishu(){},
      window:{XinjiFeishuAccountPicker:{mount:(container,opts)=>options=opts}},credentialGeneration:1,mobileSourceFormEpoch:1};
    vm.createContext(ctx);vm.runInContext(src.slice(start,end)+`\nthis.open=${mobile?'openMobileFeishuAccount':'renderFeishuAccount'};`,ctx);ctx.open();
    assert.equal(calls,0);const before=$('#input').value;assert.equal(await options.ensureSession(),'canonical');
    assert.equal(state.session.id,'canonical');assert.equal($('#input').value,before);assert.equal(calls,1);
  }
});

test('Web and H5 account changes immediately update an already rendered directory without requests or draft changes',()=>{
  const module=setup().module;
  for(const mobile of [false,true]) {
    const src=fs.readFileSync(mobile?'web/m.js':'web/app.js','utf8');
    const start=src.indexOf(mobile?'  function openMobileFeishuAccount()':'  function renderFeishuAccount()');
    const end=src.indexOf(mobile?'  function openMobileFeishu()':'  function renderFeishuPicker()',start);
    const nodes=new Map(),$=key=>{if(!nodes.has(key))nodes.set(key,{...element(),value:'保留未发送的草稿'});return nodes.get(key);};
    const badges=[element(),element()],controls=[element(),element()],document={querySelectorAll:selector=>selector==='[data-feishu-account-status]'?badges:controls};
    let options,requests=0;const state={session:{id:'canonical'}};
    const ctx={state,$,document,els:{onboarding:element()},credentialGeneration:1,mobileSourceFormEpoch:1,
      clearCredentialForms(){},clearMobileSourceForm(){},showWz(){},openMobileFeishu(){},api:async()=>{requests++;throw Error('a directory repaint must not issue a request');},
      window:{XinjiFeishuAccountPicker:{...module,mount:(_container,opts)=>options=opts}}};
    vm.createContext(ctx);vm.runInContext(src.slice(start,end)+`\nthis.open=${mobile?'openMobileFeishuAccount':'renderFeishuAccount'};`,ctx);ctx.open();
    for(const [data,label,button] of [[{enabled:true,ready:true},'✓ 已连接','管理连接'],[{enabled:false,ready:true},'待连接','连接'],[{enabled:true,ready:false},'连接需核对','管理连接']]) {
      options.onStateChange(data);assert.ok(badges.every(node=>node.textContent===label));assert.ok(controls.every(node=>node.textContent===button));
    }
    assert.equal(requests,0);assert.equal($('#input').value,'保留未发送的草稿');assert.equal(state.session.id,'canonical');
  }
});

for (const mobile of [false,true]) {
  test(`${mobile?'H5':'Web'} account authorization uses official joint-scope OAuth then verifies enablement and returns to chat`,async()=>{
    const src=fs.readFileSync(mobile?'web/m.js':'web/app.js','utf8');
    const start=src.indexOf(mobile?'  let mAuthTimer = null':'  let authPollTimer = null');
    const end=src.indexOf(mobile?'  function renderMemeText':'  async function openApps()',start);
    const nodes=new Map(),$=key=>{if(!nodes.has(key))nodes.set(key,{...element(),href:'',focus(){},removeAttribute(name){this[name]='';}});return nodes.get(key);};
    const calls=[],times=[],events=[],url='https://accounts.feishu.cn/oauth/v1/device/verify/?flow_id=unit-only&user_code=UNIT';
    const ctx={$,state:{session:{id:'same-dialogue'}},els:{onboarding:element()},URL,prepareSourceDialog(){events.push('resume');},
      renderFeishuAccount(){events.push('account');},renderFeishuPicker(){events.push('single');},showWz(){},loadToday(){},
      finishConnection(data){events.push(['connected',data.intro.id]);},closeSourceDialog(){events.push('close');},toast(){},XinjiFeishuAccountPicker:{syncBadges(){}},document:{},setInterval:fn=>{ctx.poll=fn;return 1;},clearInterval(){},setTimeout:fn=>times.push(fn),
      api:async(path,options)=>{calls.push([path,options]);return path.endsWith('/start')?{status:'pending',url}:path.endsWith('/connect')?{ok:true,enabled:true,ready:true,intro:{id:'job'}}:{status:'success'};},
      open(){events.push('blank-window');return{opener:{},location:{replace(value){events.push(value);}},close(){}};},
      XinjiSourceDialog:{isOpen:()=>!mobile},finishMobileAuthSurface(){events.push('mobile-resume');}};
    ctx.window=ctx;vm.createContext(ctx);vm.runInContext(src.slice(start,end)+`\nthis.openAccount=${mobile?'startLarkAuthMobile':'startLarkAuth'};this.canChoose=larkCanChooseDocuments;`,ctx);
    await ctx.openAccount('account');
    assert.equal(events[0],'blank-window');assert.equal(calls[0][0],'/api/auth/lark/account/start');assert.ok(events.includes(url));
    await ctx.poll();assert.equal(calls[1][0],'/api/auth/lark/account/status');assert.equal(ctx.canChoose(),false);
    assert.equal(calls[2][0],'/api/lark/account/connect');
    assert.deepEqual(JSON.parse(calls[2][1].body),{session_id:'same-dialogue',start_intro:true});
    assert.deepEqual(events.find(event=>Array.isArray(event)),['connected','job']);
    assert.ok(!events.includes('single'));assert.equal(times.length,0);
  });
}

test('an already connected account offers return to chat without replaying a completed intro or searching again',async()=>{
 const e=setup({reply:async()=>({enabled:true,ready:true})});await flush();assert.match(e.container.html,/feishu-account-return is-hidden">回到聊天/);assert.doesNotMatch(e.container.html,/聊聊最近 7 天/);e.node('.feishu-account-return').onclick();assert.deepEqual(e.events,['return']);assert.equal(e.calls.length,1);assert.equal(e.calls[0][1],undefined);
});
