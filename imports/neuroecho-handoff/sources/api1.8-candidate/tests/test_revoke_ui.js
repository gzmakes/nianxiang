// Browser state tests with synthetic sessions; no real user data or services.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function clip(src, from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  assert.ok(a >= 0 && b > a);
  return src.slice(a, b);
}
function element() {
  const hidden = new Set(['is-hidden']);
  return {textContent:'', classList:{add:x=>hidden.add(x), remove:x=>hidden.delete(x), contains:x=>hidden.has(x)}};
}
for (const variant of ['desktop', 'mobile']) {
  const mobile = variant === 'mobile';
  const src = fs.readFileSync(mobile ? 'web/m.js' : 'web/app.js', 'utf8');
  const code = mobile
    ? clip(src, '  async function revokeMobileSource()', '  async function renderMore()')
    : clip(src, '  async function revokeSource()', '  function resetAll()');
  const fn = mobile ? 'revokeMobileSource' : 'revokeSource';
  function setup(api) {
    const elements = new Map();
    const $ = (id) => { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); };
    const state = {session:{id:'s',source_label:'旧来源'}, memories:[{text:'原记忆'}], context:{insights:[{title:'旧洞察'}]}, messages:[{text:'待发送消息'}], nextStep:{step:'旧建议'}};
    const shown = [];
    const ctx = vm.createContext({$, state, els:{sourceLabel:element()}, confirm:()=>true, api,
      connectedSources:()=>state.context?.sources || [{id:null,label:state.session.source_label}], sourceDisplayName:s=>s.label, renderConnectedSources(){},
      enterSession(data,opts={}){state.session=data.session;state.memories=data.memories;state.bookmark=data.bookmark||null;state.context=data.context||null;if(!opts.preserveDrafts)state.messages=data.messages||[];},
      renderAll(){}, renderNextStep(){}, renderInsightPanel(){}, renderStarters(){},
      loadNextStep(){}, loadAudit(){}, closeSheet(){}, toast:s=>shown.push(s), encodeURIComponent});
    ctx.window = {XinjiDialogs: {confirm: async options => ctx.confirm(options.message)}};
 vm.runInContext("let sourceUiEpoch=0;" + code + `\nthis.run=${fn}`, ctx);
    return {ctx, state, shown, $};
  }
  test(`${variant}: revoke reloads surviving memories without replacing unsent messages`, async()=>{
    const calls=[];
    const {ctx,state,shown} = setup(async(path)=>{
      calls.push(path);
      if(path === '/api/source/revoke') return {ok:true,cleaned:1};
      return {session:{id:'s',source_label:'新对话'}, memories:[{text:'接入前保留的记忆'}], bookmark:null, context:null};
    });
    await ctx.run();
    assert.deepEqual(calls,['/api/source/revoke','/api/session/s']);
    assert.equal(state.memories[0].text,'接入前保留的记忆');
    assert.equal(state.messages[0].text,'待发送消息');
    assert.equal(state.session.source_label,'新对话');
    assert.equal(state.context,null);
    assert.match(shown[0],/清理 1 条派生记忆/);
  });
  test(`${variant}: failed refresh clearly distinguishes confirmed revoke from unsynced UI`, async()=>{
    const {ctx,state,shown,$} = setup(async(path)=>{if(path === '/api/source/revoke') return {ok:true,cleaned:1}; throw Error('offline');});
    await ctx.run();
    assert.equal(state.memories[0].text,'原记忆');
    assert.match(shown[0],/已撤回.*未能同步.*刷新/);
    const notice=$(mobile?'#m-chat-error':'#chat-error');
    assert.equal(notice.classList.contains('is-hidden'),false);
  });
  test(`${variant}: uncertain legacy memories receive a persistent review notice`, async()=>{
    const {ctx,$} = setup(async(path)=> path === '/api/source/revoke'
      ? {ok:true,cleaned:1,review_required:2}
      : {session:{id:'s',source_label:'新对话'},memories:[],bookmark:null,context:null});
    await ctx.run();
    const notice=$(mobile?'#m-chat-error':'#chat-error');
    assert.equal(notice.classList.contains('is-hidden'),false);
    assert.match(notice.textContent,/2 条来源待核对.*暂停.*模型/);
  });
  test(`${variant}: uncertain revoke does not claim success`, async()=>{
    const {ctx,shown} = setup(async()=>{throw Error('offline');});
    await ctx.run();
    assert.match(shown[0],/未能确认撤回结果/);
  });
  test(`${variant}: response does not overwrite another session`, async()=>{
    let state;
    const setupResult = setup(async(path)=>{
      if(path === '/api/source/revoke') return {ok:true,cleaned:1};
      state.session={id:'other',source_label:'其他会话'};
      state.memories=[{text:'其他记忆'}];
      return {session:{id:'s'},memories:[],context:null};
    });
    state=setupResult.state;
    await setupResult.ctx.run();
    assert.equal(state.session.id,'other');
    assert.equal(state.memories[0].text,'其他记忆');
  });
}
