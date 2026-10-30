// Synthetic local Git picker tests; no repository, account, credential or network access.
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const files = {desktop: fs.readFileSync('web/app.js', 'utf8'), mobile: fs.readFileSync('web/m.js', 'utf8')};
function clip(source, first, next) { const a=source.indexOf(first),b=source.indexOf(next,a); assert.ok(a>=0&&b>a); return source.slice(a,b); }
function element() { const hidden=new Set(); return {value:'',textContent:'',innerHTML:'',disabled:false,classList:{add:x=>hidden.add(x),remove:x=>hidden.delete(x),toggle:(x,on)=>on?hidden.add(x):hidden.delete(x)}}; }
function storage(){ const m=new Map(); return {get length(){return m.size},key:i=>Array.from(m.keys())[i]??null,getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k)}; }
function setup(kind, reply) {
  const source=files[kind], nodes=new Map(), $=selector=>{if(!nodes.has(selector))nodes.set(selector,element());return nodes.get(selector)};
  const calls=[], transitions=[], state={session:{id:'current'}}, wizard={}, wz={};
  const ctx=vm.createContext({$,state,wizard,wz,AbortController,localStorage:storage(),esc:s=>String(s??'').replace(/</g,'&lt;'),
    api:async(...args)=>{calls.push(args);return reply(...args)},renderInsights:()=>transitions.push('insights')});
  if (kind==='desktop') {
    vm.runInContext(clip(source,'  const credentialPendingKey = ','  function showWz(n)')+
      'function showWz(){}\n'+clip(source,'  function renderGitPicker()','  function openLocalFiles()')+
      '\nthis.open=renderGitPicker;this.clear=clearCredentialForms;',ctx);
  } else {
    vm.runInContext(clip(source,'  const mobilePendingPrefix = ','  async function loadCatalog()')+
      clip(source,'  function openMobileGit()','  function openMobileCredentialSource(')+
      '\nthis.open=openMobileGit;this.clear=clearMobileSourceForm;',ctx);
  }
  ctx.open();
  const prefix=kind==='desktop'?'#wz-git-':'#m-git-';
  return {$,ctx,state,wizard,wz,calls,transitions,input:$(prefix+'path'),button:$(prefix+'preview'),hint:$(prefix+'hint'),items:$(kind==='desktop'?'#read-items':'#m-read-items'),use:()=>$(prefix+'use')};
}
const sample={ok:true,preview_id:'synthetic-preview',selected_path:'/synthetic/repository',connector:{id:'git'},
  items:Array.from({length:8},(_,i)=>({title:`Synthetic commit ${i}<`,meta:`repo · hash${i}`,summary:`Synthetic summary ${i}`}))};
for(const kind of ['desktop','mobile']) {
  test(`${kind} Git: requires explicit path and shows model disclosure before reading`,async()=>{
    const env=setup(kind,async()=>sample);await env.button.onclick();
    assert.equal(env.calls.length,0);assert.match(env.hint.textContent,/完整目录/);
    assert.match(env.$(kind==='desktop'?'#read-head':'#m-read-head').innerHTML,/最多 8 条.*模型|模型.*最多 8 条/s);
  });
  test(`${kind} Git: previews every commit before allowing existing insight flow`,async()=>{
    const env=setup(kind,async()=>sample);env.input.value='/synthetic/repo with spaces';await env.button.onclick();
    assert.deepEqual(JSON.parse(env.calls[0][1].body),{source_id:'git',path:'/synthetic/repo with spaces'});
    assert.match(env.items.innerHTML,/Synthetic commit 7&lt;/);assert.match(env.items.innerHTML,/repo · hash7/);
    assert.match(env.items.innerHTML,/\/synthetic\/repository/);assert.deepEqual(env.transitions,[]);
    env.use().onclick();assert.deepEqual(env.transitions,['insights']);
    assert.equal((kind==='desktop'?env.state.realSource:env.wz.realSource).read.preview_id,'synthetic-preview');
  });
  test(`${kind} Git: a failed path remains editable and can be retried`,async()=>{
    let count=0;const env=setup(kind,async()=>++count===1?{ok:false,error:'不存在',hint:'请换一个目录'}:sample);
    env.input.value='/synthetic/missing';await env.button.onclick();assert.match(env.hint.textContent,/不存在.*换一个目录/);
    assert.equal(env.button.disabled,false);assert.equal(env.input.value,'/synthetic/missing');
    env.input.value='/synthetic/real';env.input.oninput();await env.button.onclick();assert.match(env.items.innerHTML,/核对这些提交/);
  });
  test(`${kind} Git: editing the path invalidates a previously shown preview`,async()=>{
    const env=setup(kind,async()=>sample);env.input.value='/synthetic/one';await env.button.onclick();
    const stale=env.use().onclick;env.input.value='/synthetic/two';env.input.oninput();stale();
    assert.equal(env.items.innerHTML,'');assert.deepEqual(env.transitions,[]);
  });
  for(const action of ['close','switch']) test(`${kind} Git: a late read after ${action} cannot replace current UI`,async()=>{
    let resolve;const pending=new Promise(r=>resolve=r);const env=setup(kind,async()=>pending);env.input.value='/synthetic/repo';
    const running=env.button.onclick();if(action==='close')env.ctx.clear();else env.state.session={id:'other'};
    resolve(sample);await running;assert.equal(env.items.innerHTML,'');assert.deepEqual(env.transitions,[]);
    if(kind==='desktop'&&action==='close')assert.equal(env.calls[0][1].signal.aborted,true);
  });
  test(`${kind} Git: an older response cannot overwrite a newer directory preview`,async()=>{
    let resolve;const old=new Promise(r=>resolve=r);let count=0;
    const env=setup(kind,async()=>++count===1?old:{...sample,selected_path:'/synthetic/new'});
    env.input.value='/synthetic/old';const first=env.button.onclick();env.input.value='/synthetic/new';env.input.oninput();await env.button.onclick();
    resolve({...sample,selected_path:'/synthetic/old'});await first;assert.match(env.items.innerHTML,/\/synthetic\/new/);assert.doesNotMatch(env.items.innerHTML,/\/synthetic\/old/);
  });
}
test('Git entry remains selectable when nearby automatic discovery is empty',()=>{
  assert.match(files.desktop,/s\.status === "empty" && s\.id !== "git"/);
  assert.ok(files.desktop.indexOf('if (id === "git") { renderGitPicker(); return; }')>=0);
  assert.ok(files.mobile.indexOf('if (id === "git") { openMobileGit(); return; }')<files.mobile.indexOf('status === "empty")'));
});
