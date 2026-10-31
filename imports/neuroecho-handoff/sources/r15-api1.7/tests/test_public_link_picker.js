// Unit-only synthetic responses; these checks do not claim live platform access.
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('web/public-link-picker.js', 'utf8');

function node() {
  return {children:[], textContent:'', value:'', disabled:false, attributes:{},
    appendChild(child) { this.children.push(child); },
    replaceChildren(...children) { this.children = children; },
    setAttribute(name, value) { this.attributes[name] = value; }};
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function preview(overrides = {}) {
  return {ok:true, preview_id:'reviewed-preview', connector:{id:'waytoagi'},
    title:'Unit-only public document', text:'合成公开正文\n第二行😀', ...overrides};
}
function setup({sourceId = 'waytoagi', reply = async () => preview(), attach, autoAttach = false} = {}) {
  const selectors = ['.public-url', '.public-read', '.public-status', '.public-preview', '.public-confirm'];
  const nodes = Object.fromEntries(selectors.map(selector => [selector, node()]));
  const container = {isConnected:true, querySelector:selector => nodes[selector],
    set innerHTML(value) { this.html = value; nodes['.public-confirm'].disabled = /public-confirm" disabled/.test(value); }};
  const calls = [], attached = [], context = {active:true};
  const sandbox = {window:{}, document:{createElement:() => node()}, URL};
  vm.runInNewContext(source, sandbox);
  sandbox.window.XinjiPublicLinkPicker.mount(container, {sourceId, autoAttach,
    api:async (...args) => { calls.push(args); return reply(...args); },
    isCurrent:() => context.active,
    onConfirm:async value => { attached.push(value); if (attach) await attach(value); }});
  return {container, context, calls, attached, input:nodes['.public-url'], read:nodes['.public-read'],
    status:nodes['.public-status'], output:nodes['.public-preview'], confirm:nodes['.public-confirm'],
    change(url) { this.input.value = url; this.input.oninput(); }};
}

test('mount is inert and invalid URLs never start a source request', async () => {
  const t = setup();
  assert.equal(t.calls.length, 0);
  assert.equal(t.confirm.disabled, true);
  await t.confirm.onclick();
  for (const url of ['', 'not a URL', 'http://example.test', 'javascript:alert(1)']) {
    t.change(url); await t.read.onclick();
    assert.match(t.status.textContent, /HTTPS/);
    assert.equal(t.calls.length, 0); assert.equal(t.confirm.disabled, true);
  }
  assert.equal(t.attached.length, 0);
});

for (const sourceId of ['waytoagi', 'jike']) {
  test(`${sourceId}: only explicit confirmation attaches the exact reviewed server preview`, async () => {
    const data = preview({connector:{id:sourceId}, title:'<script>must remain text</script>'});
    const t = setup({sourceId, reply:async () => data});
    t.change('  https://example.test/document?part=1  ');
    await t.read.onclick();
    assert.equal(t.calls.length, 1);
    assert.equal(t.calls[0][0], '/api/onboarding/real/read');
    assert.equal(t.calls[0][1].method, 'POST');
    assert.deepEqual(JSON.parse(t.calls[0][1].body), {source_id:sourceId, url:'https://example.test/document?part=1'});
    assert.equal(t.output.children[0].textContent, data.title);
    assert.equal(t.output.children[1].value, data.text);
    assert.equal(t.output.children[1].readOnly, true);
    assert.equal(t.attached.length, 0);
    assert.equal(t.confirm.disabled, false);
    await t.confirm.onclick(); await t.confirm.onclick();
    assert.equal(t.attached.length, 1); assert.strictEqual(t.attached[0], data);
  });
}

test('network failures and malformed payloads never become ready, then a real retry can succeed', async () => {
  const failures = [
    () => { throw Error('network unavailable'); },
    () => ({ok:false, error:'需要登录', hint:'请使用公开链接'}),
    () => preview({preview_id:''}), () => preview({text:' \n\t'}),
    () => preview({connector:{id:'other-platform'}}), () => undefined
  ];
  for (const failure of failures) {
    let attempts = 0;
    const t = setup({reply:async () => ++attempts === 1 ? failure() : preview()});
    t.change('https://example.test/doc'); await t.read.onclick(); await t.confirm.onclick();
    assert.equal(t.confirm.disabled, true); assert.equal(t.read.disabled, false);
    assert.equal(t.output.children.length, 0); assert.equal(t.attached.length, 0);
    assert.doesNotMatch(t.status.textContent, /^已从原站读取/);
    await t.read.onclick(); assert.equal(t.confirm.disabled, false);
  }
});

test('a pending read prevents duplicate requests and cannot confirm early', async () => {
  const pending = deferred(), t = setup({reply:() => pending.promise});
  t.change('https://example.test/doc'); const reading = t.read.onclick();
  assert.equal(t.read.disabled, true);
  await t.read.onclick(); await t.confirm.onclick();
  assert.equal(t.calls.length, 1); assert.equal(t.attached.length, 0);
  pending.resolve(preview()); await reading;
  assert.equal(t.confirm.disabled, false);
});

test('changing a URL immediately invalidates an already reviewed preview', async () => {
  const t = setup(); t.change('https://example.test/first'); await t.read.onclick();
  t.change('https://example.test/second'); await t.confirm.onclick();
  assert.equal(t.output.children.length, 0); assert.equal(t.confirm.disabled, true);
  assert.equal(t.attached.length, 0);
});

for (const lateOutcome of ['success', 'failure']) {
  test(`a late ${lateOutcome} from an old URL cannot replace a newer reviewed result`, async () => {
    const first = deferred(), latest = preview({preview_id:'new-preview', text:'New reviewed body'});
    let attempt = 0;
    const t = setup({reply:() => ++attempt === 1 ? first.promise : latest});
    t.change('https://example.test/old'); const oldRead = t.read.onclick();
    t.change('https://example.test/new'); await t.read.onclick();
    const status = t.status.textContent;
    if (lateOutcome === 'success') first.resolve(preview({text:'Obsolete body'}));
    else first.reject(Error('Old network failure'));
    await oldRead;
    assert.equal(t.output.children[1].value, latest.text); assert.equal(t.status.textContent, status);
    await t.confirm.onclick(); assert.strictEqual(t.attached[0], latest);
  });
}

for (const leave of ['detach', 'change current view']) {
  test(`late reads after ${leave} cannot update or attach a source`, async () => {
    const pending = deferred(), t = setup({reply:() => pending.promise});
    t.change('https://example.test/doc'); const reading = t.read.onclick();
    if (leave === 'detach') t.container.isConnected = false;
    else t.context.active = false;
    pending.resolve(preview()); await reading; await t.confirm.onclick();
    assert.equal(t.output.children.length, 0); assert.equal(t.attached.length, 0);
  });
  test(`an already reviewed source cannot be attached after ${leave}`, async () => {
    const t = setup(); t.change('https://example.test/doc'); await t.read.onclick();
    if (leave === 'detach') t.container.isConnected = false;
    else t.context.active = false;
    await t.confirm.onclick(); assert.equal(t.attached.length, 0);
  });
}

test('unknown attachment outcomes never replay: inspect attached sources and reread explicitly', async () => {
  const pending = deferred(); let attempts = 0;
  const t = setup({attach:async () => { if (++attempts === 1) await pending.promise; }});
  t.change('https://example.test/doc'); await t.read.onclick();
  const attaching = t.confirm.onclick(); await t.confirm.onclick(); await t.read.onclick();
  assert.equal(t.attached.length, 1); assert.equal(t.calls.length, 1); assert.equal(t.input.disabled, true);
  pending.reject(Error('Connection lost after submission')); await attaching;
  assert.equal(t.input.disabled, false); assert.equal(t.read.disabled, false); assert.equal(t.confirm.disabled, true);
  assert.equal(t.output.children.length, 0); assert.match(t.status.textContent, /核对已接入资料.*重新读取/);
  await t.confirm.onclick(); assert.equal(t.attached.length, 1);
  await t.read.onclick(); await t.confirm.onclick();
  assert.equal(t.calls.length, 2); assert.equal(t.attached.length, 2);
});

test('truncation is visible and Unicode character counts match the exact displayed body', async () => {
  const data = preview({text:'中😀', truncated:true}), t = setup({reply:async () => data});
  t.change('https://example.test/doc'); await t.read.onclick();
  assert.match(t.status.textContent, /2 字.*正文超限/);
  assert.equal(t.output.children[1].value, data.text);
  await t.confirm.onclick(); assert.equal(t.attached[0].text, data.text);
});

for (const mode of ['web', 'h5']) {
 test(`${mode}: reviewed public attachment waits for any existing source mutation`, async()=>{
  const text = fs.readFileSync(mode === 'web' ? 'web/app.js' : 'web/m.js', 'utf8');
  const start = text.indexOf(mode === 'web' ? '  function openPublicSource(' : '  function openMobilePublicSource(');
  const end = text.indexOf(mode === 'web' ? '  function openLocalFiles(' : '  function openMobileLocalFiles(', start);
  assert.ok(start >= 0 && end > start);
  const state = {session:{id:'s'}}, nodes = new Map();
  const $ = key => { if (!nodes.has(key)) nodes.set(key, {classList:{add(){}},innerHTML:'',textContent:''}); return nodes.get(key); };
  let picker;
  const context = {state, $, mobileSourceFormEpoch:1, activeTurn:null, queuedTurns:[],turnQueue:[],mActiveTurn:null,mQueuedTurns:[],mTurnQueue:[],
   beginCredentialRequest:()=>({}), credentialRequestCurrent:()=>true, showWz(){},
   api:async()=>assert.fail('must not overlap source writes'),
   window:{XinjiPublicLinkPicker:{mount(_,options){picker=options}}}};
  vm.runInNewContext(text.slice(start,end) + (mode === 'web' ? "\nopenPublicSource('waytoagi');" : "\nopenMobilePublicSource('waytoagi');"), context);
  for (const key of ['attachingSource','revokingSource','confirmingSource']) {
   state[key]=true;await assert.rejects(picker.onConfirm(preview()), /对话正在更新/);state[key]=false;
  }
 });
}

for(const sourceId of ['waytoagi','jike']){
 test(`${sourceId}: one compact authorization reads and attaches the exact actual preview once`,async()=>{
  const data=preview({connector:{id:sourceId}}),t=setup({sourceId,autoAttach:true,reply:async()=>data});t.change('https://example.test/document');await t.read.onclick();
  assert.equal(t.calls.length,1);assert.equal(JSON.parse(t.calls[0][1].body).start_intro,true);assert.equal(t.attached.length,1);assert.strictEqual(t.attached[0],data);await t.confirm.onclick();assert.equal(t.attached.length,1);
 });
}
test('a failed compact read never attaches or claims success',async()=>{
 const t=setup({autoAttach:true,reply:async()=>({ok:false,error:'合成读取失败'})});t.change('https://example.test/document');await t.read.onclick();assert.equal(t.attached.length,0);assert.match(t.status.textContent,/读取失败/);
});
