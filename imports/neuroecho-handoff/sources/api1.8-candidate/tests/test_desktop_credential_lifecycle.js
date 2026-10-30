// All inputs and API responses below are synthetic; no services are contacted.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const src = fs.readFileSync('web/app.js', 'utf8');
function clip(a, b) { const i = src.indexOf(a), j = src.indexOf(b, i); assert.ok(i >= 0 && j > i); return src.slice(i, j); }
function element() {
  const classes = new Set(), listeners = new Map();
  return {value:'', textContent:'', innerHTML:'', classList: {add: x => classes.add(x), remove: x => classes.delete(x), toggle: (x, on) => on ? classes.add(x) : classes.delete(x), contains: x => classes.has(x)}, querySelector: () => null, insertAdjacentHTML() {},
    addEventListener:(type,callback)=>listeners.set(type,callback),fire:type=>listeners.get(type)?.()};
}
function storage() {const m = new Map(); return {getItem:k=>m.get(k) ?? null, setItem:(k,v)=>m.set(k,v), removeItem:k=>m.delete(k)};}
function setup(kind, api, localStorage=storage(), enterSession = () => { throw Error('stale session must not open'); }) {
  const nodes = new Map();
  const $ = s => {if (!nodes.has(s)) nodes.set(s, element()); return nodes.get(s)};
  const ctx = vm.createContext({$, $$: () => [], state:{session:null}, AbortController, localStorage, api, esc: x => x, enterSession});
  vm.runInContext('let activeTurn=null, queuedTurns=[], turnQueue=[];'+clip('  const credentialPendingKey = ', '  async function loadCatalog()') + clip(`  function render${kind}Real()`, kind === 'Gmail' ? '  function renderFeishuPicker()' : '  function renderInsights()') + `\nthis.open=render${kind}Real;this.clear=clearCredentialForms;this.back=()=>showWz(2);this.showPending=renderCredentialPendingNotice;`,ctx);
  ctx.open();
  return {ctx, $, localStorage};
}
function deferred() { let resolve; const promise = new Promise(r => {resolve = r}); return {promise, resolve}; }
for (const [kind, input, target, preview, result, hint, start] of [
  ['Gmail','#wz-gmail-password','#wz-gmail-address','#wz-gmail-preview','#wz-gmail-result','#wz-gmail-hint','#wz-gmail-start'],
  ['Notion','#wz-notion-token','#wz-notion-url','#wz-notion-preview','#wz-notion-result','#wz-notion-hint','#wz-notion-start']
]) {
  test(`${kind}: back clears unsubmitted credential and preview`, () => {
    const {ctx,$} = setup(kind, async () => ({})); $(input).value='fixture-secret'; $(result).innerHTML='fixture-preview'; ctx.back();
    assert.equal($(input).value,''); assert.equal($(result).innerHTML,''); assert.equal($(result).classList.contains('is-hidden'),true);
  });
  test(`${kind}: close aborts preview and ignores its late response after reopening`, async () => {
    const d = deferred(); let signal; const {ctx,$} = setup(kind, async (_, options) => { signal=options.signal; return d.promise; });
    $(input).value='fixture-secret'; $(target).value='fixture-target'; const pending=$(preview).onclick();
    assert.equal($(input).value,''); ctx.clear(); assert.equal(signal.aborted,true); ctx.open(); $(input).value='new-secret'; $(hint).textContent='new form';
    d.resolve({ok:true,preview_id:'preview',title:'old preview',items:[{title:'old',summary:'old'}]}); await pending;
    assert.equal($(input).value,'new-secret'); assert.equal($(hint).textContent,'new form'); assert.equal($(result).innerHTML,''); assert.equal($(start).onclick,undefined);
  });
  test(`${kind}: late first preview cannot overwrite newer preview or its typed credential`, async () => {
    const one=deferred(),two=deferred();let count=0;const {ctx,$}=setup(kind,async()=>++count===1?one.promise:two.promise);
    $(input).value='first-secret'; $(target).value='fixture'; const p1=$(preview).onclick(); $(input).value='second-secret'; const p2=$(preview).onclick();
    $(input).value='next-secret'; two.resolve({ok:true,preview_id:'new',title:'new-preview',items:[{title:'new',summary:'new'}]}); await p2;
    const updated=$(result).innerHTML; one.resolve({ok:true,preview_id:'old',title:'old-preview',items:[{title:'old',summary:'old'}]});await p1;
    assert.equal($(input).value,'next-secret');assert.equal($(result).innerHTML,updated);assert.doesNotMatch(updated,/old-preview/);
  });
  test(`${kind}: an unknown start outcome keeps an actionable warning without suggesting retry`, async()=>{
    const {ctx,$,localStorage}=setup(kind,async path=>{if(path.endsWith('/preview'))return {ok:true,preview_id:'p',title:'x',items:[]};throw Error('connection lost')});
    $(input).value='fixture-secret';$(target).value='fixture';await $(preview).onclick();await $(start).onclick();
    assert.match($(hint).textContent,/来源接入结果未确认.*当前对话或历史核对/);assert.doesNotMatch($(hint).textContent,/重试/);assert.equal($('#source-uncertain-notice').classList.contains('is-hidden'),false);
    const reopened=setup(kind,async()=>({}),localStorage);reopened.ctx.showPending();assert.equal(reopened.$('#source-uncertain-notice').classList.contains('is-hidden'),false);
  });
  test(`${kind}: a confirmed success clears only its own pending marker`, async()=>{
    const localStorage=storage();localStorage.setItem('xinji_source_creation_pending',JSON.stringify(['earlier-unknown']));let entered=false;
    const {ctx,$}=setup(kind,async path=>path.endsWith('/preview')?{ok:true,preview_id:'p',title:'x',items:[]}:{session:{id:'fixture'}},localStorage,()=>{entered=true});
    $(input).value='fixture-secret';$(target).value='fixture';await $(preview).onclick();await $(start).onclick();
    assert.equal(entered,true);assert.deepEqual(JSON.parse(localStorage.getItem('xinji_source_creation_pending')),['earlier-unknown']);
    assert.equal($('#source-uncertain-notice').classList.contains('is-hidden'),false);
  });
  test(`${kind}: an expired preview cannot have created the session`, async()=>{
    const {ctx,$,localStorage}=setup(kind,async path=>{if(path.endsWith('/preview'))return {ok:true,preview_id:'p',title:'x',items:[]}; const e=Error('expired');e.status=400;throw e});
    $(input).value='fixture-secret';$(target).value='fixture';await $(preview).onclick();await $(start).onclick();
    assert.equal(localStorage.getItem('xinji_source_creation_pending'),null);assert.match($(hint).textContent,/预览已失效/);
  });
  test(`${kind}: a late start response after close does not navigate`, async()=>{
    const started=deferred(); const {ctx,$,localStorage}=setup(kind,async path => path.endsWith('/preview') ? {ok:true,preview_id:'p',title:'x',items:[]} : started.promise);
    $(input).value='fixture-secret';$(target).value='fixture';await $(preview).onclick(); const pending=$(start).onclick();ctx.clear();assert.equal($('#source-uncertain-notice').classList.contains('is-hidden'),false); started.resolve({session:{id:'fixture'}});await pending;
    const reopened=setup(kind,async()=>({}),localStorage);reopened.ctx.showPending();assert.equal(reopened.$('#source-uncertain-notice').classList.contains('is-hidden'),false);
  });
}
test('return, skip and pagehide all clear typed credentials and abort a pending preview', async () => {
  for (const route of ['return','skip','pagehide']) {
    const delayed=deferred();let signal;
    const {ctx,$}=setup('Gmail',async(_path,options)=>{signal=options.signal;return delayed.promise;});
    ctx.state.session={id:'current'};ctx.els={onboarding:element()};ctx.window=ctx;
    const events=new Map();ctx.addEventListener=(type,callback)=>events.set(type,callback);
    vm.runInContext(clip('  function closeSourceDialog()', '  function prepareSourceDialog()')+
      clip('    $("#onboarding-return")?.addEventListener', '    $("#open-connect")?.addEventListener')+
      '\nwindow.addEventListener("pagehide", clearCredentialForms);',ctx);
    $('#wz-gmail-password').value='synthetic-secret';$('#wz-gmail-address').value='synthetic-address';
    const pending=$('#wz-gmail-preview').onclick();$('#wz-gmail-password').value='new-unsent-secret';
    if(route==='pagehide')events.get('pagehide')();else $(route==='return'?'#onboarding-return':'#wz-skip').fire('click');
    assert.equal($('#wz-gmail-password').value,'');assert.equal(signal.aborted,true);
    delayed.resolve({ok:true,preview_id:'old-preview',title:'late',items:[]});await pending;
    assert.equal($('#wz-gmail-result').innerHTML,'');assert.equal(ctx.state.session.id,'current');
  }
  assert.match(src, /addEventListener\("pagehide", clearCredentialForms\)/);
  assert.match(src, /function enterSession\(data, opts = \{\}\) \{\s*clearCredentialForms\(\)/);
});
