const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function element() {
  return { value:'', hidden:false, style:{}, textContent:'', attrs:{}, focused:false,
    setAttribute(k,v){this.attrs[k]=v}, focus(){this.focused=true},
    getBoundingClientRect(){return {left:0,top:0,width:100,height:100}},
    setPointerCapture(id){this.captured=id}, hasPointerCapture(id){return this.captured===id} };
}
function setup() {
  const context={window:{}, Math, Number, String, WeakMap};
  vm.runInNewContext(fs.readFileSync('web/lab.js','utf8'), context);
  const editor=element(),open=element(); editor.hidden=true; let nodes = new Map();
  Object.defineProperty(editor,'innerHTML',{set(value){this.markup=value;nodes=new Map()},get(){return this.markup}});
  editor.querySelector = selector => {if(!nodes.has(selector))nodes.set(selector,element());return nodes.get(selector)};
  editor.replaceChildren=()=>{editor.markup='';nodes=new Map()};
  const host={innerHTML:'',querySelector:selector=>selector==='[data-lab-editor]'?editor:open};
  context.window.XinjiLab.mount(host);
  return {lab:context.window.XinjiLab,host,open,editor,get:(key)=>editor.querySelector('[data-lab-'+key+']')};
}
test('experiment offers an extensible section, explicitly local scope and no network/storage access',()=>{
  const e=setup();assert.match(e.host.innerHTML,/实验区/);assert.match(e.host.innerHTML,/心情表达方式/);
  e.open.onclick();assert.match(e.editor.innerHTML,/尚未验证疗效/);assert.match(e.editor.innerHTML,/不判断你的情绪/);assert.match(e.editor.innerHTML,/关闭实验或离开设置后清除/);
  assert.doesNotMatch(fs.readFileSync('web/lab.js','utf8'),/\b(fetch|localStorage|sessionStorage|sendBeacon|XMLHttpRequest)\s*[.(]/);
});
test('map and accessible sliders share values, update color, and keep free text while switching',()=>{
  const e=setup();e.open.onclick();const plane=e.get('plane'), before=plane.style.background;
  plane.onpointerdown({clientX:100,clientY:0,pointerId:1});
  assert.equal(e.get('x').value,'100');assert.equal(e.get('y').value,'100');assert.notEqual(plane.style.background,before);
  assert.match(e.get('reading').textContent,/偏舒服 · 偏有活力/);
  e.get('note').value='今天有点复杂';e.get('accessible').onclick();
  assert.equal(e.get('sliders').hidden,false);assert.equal(e.get('map-panel').hidden,true);assert.equal(e.get('x').focused,true);
  e.get('y').value='-100';e.get('y').oninput();assert.match(e.get('reading').textContent,/偏平缓/);
  e.get('plane-mode').onclick();assert.equal(e.get('note').value,'今天有点复杂');assert.equal(e.get('point').style.top,'100%');
});
test('close, tab exit, and settings remount clear only experiment text, including repeated visits',()=>{
  const e=setup(), chatDraft={value:'聊天草稿保留'};e.open.onclick();let note=e.get('note');note.value='实验的文字';e.get('done').onclick();
  assert.equal(note.value,'');assert.equal(e.editor.hidden,true);assert.equal(e.editor.markup,'');assert.equal(e.open.focused,true);
  e.open.onclick();note=e.get('note');note.value='下一次的文字';e.lab.close(e.host);assert.equal(note.value,'');assert.equal(e.editor.hidden,true);
  e.open.onclick();note=e.get('note');note.value='第三次的文字';e.lab.close(e.host);assert.equal(note.value,'');
  e.lab.mount(e.host);e.open.onclick();assert.equal(e.get('note').value,'');assert.equal(chatDraft.value,'聊天草稿保留');
});
test('reset clears this experiment, not conversation, and color handles both axes',()=>{
  const e=setup();e.open.onclick();e.get('note').value='文字';e.get('x').value='50';e.get('x').oninput();e.get('reset').onclick();
  assert.equal(e.get('note').value,'');assert.equal(e.get('x').value,'0');assert.equal(e.get('reading').textContent,'还在寻找自己的位置');
  assert.notEqual(e.lab.tint(-100,100),e.lab.tint(100,100));assert.notEqual(e.lab.tint(100,-100),e.lab.tint(100,100));
});
test('both entry points load experiment and close on leaving settings',()=>{
  for(const file of ['web/index.html','web/m.html']){const html=fs.readFileSync(file,'utf8');assert.match(html,/\/static\/lab\.css\?v=/);assert.match(html,/\/static\/lab\.js\?v=/);assert.ok(html.indexOf('/static/lab.js')<html.indexOf('/static/design-system.js'));}
  const design=fs.readFileSync('web/design-system.js','utf8');assert.match(design,/XinjiLab\?\.mount\(lab\)/);assert.match(design,/XinjiLab\?\.close\(lab\)/);
  const app=fs.readFileSync('web/app.js','utf8');assert.match(app,/if \(name !== "design"[^\n]+window\.XinjiLab\?\.close/);assert.match(app,/if \(!open[^\n]+window\.XinjiLab\?\.close/);
  const mobile=fs.readFileSync('web/m.js','utf8');assert.ok((mobile.match(/XinjiLab\?\.close\(/g)||[]).length>=2);
});

test('Web switching away from settings clears the existing experiment before tab transition',()=>{
 const source=fs.readFileSync('web/app.js','utf8'),start=source.indexOf('  function switchTab(name) {'),end=source.indexOf('\n  let todaySources',start);assert.ok(start>=0&&end>start);
 const labHost={},closed=[],tabs={classList:{remove(){},add(){}}};
 const context={window:{XinjiLab:{close:host=>closed.push(host)}},state:{tab:'design'},$:(selector)=>selector.includes('[data-settings-lab]')?labHost:tabs,$$:()=>[],pairedDevicesPanel:null,setDesignPanel(){},loadToday(){}};
 vm.runInNewContext(source.slice(start,end)+';this.change=switchTab;',context);context.change('today');
 assert.deepEqual(closed,[labHost]);assert.equal(context.state.tab,'today');
});

test('H5 moving to another sheet or closing settings clears and disposes the experiment',()=>{
 const source=fs.readFileSync('web/m.js','utf8');let start=source.indexOf('  function openSheet(kind, presetNext = "") {'),end=source.indexOf('\n  async function renderTodayMobile',start);assert.ok(start>=0&&end>start);const open=source.slice(start,end);
 start=source.indexOf('  function closeSheet() {');end=source.indexOf('\n  async function showMemoryContextNotice',start);assert.ok(start>=0&&end>start);const close=source.slice(start,end);
 const labHost={},closed=[],sheet={classList:{add(){},remove(){}}},body={},title={},preferences={_designDispose(){this.disposed=(this.disposed||0)+1}};
 const ctx={window:{XinjiLab:{close:host=>closed.push(host)}},globalThis:{},pairedDevicesPanel:null,followups:{stop(){}},mood:null,
  $:selector=>selector.includes('[data-settings-lab]')?labHost:selector==='#m-design-preferences'?preferences:selector==='#m-sheet'?sheet:selector==='#m-sheet-title'?title:body,
  renderTodayMobile(){},renderUnderstanding(){},renderBookmark(){},renderPersonaMobile(){},renderDevice(){},renderMore(){},renderDesignSettingsMobile(){}};
 vm.runInNewContext(open+close+';this.show=openSheet;this.close=closeSheet;',ctx);ctx.show('today');ctx.close();
 assert.deepEqual(closed,[labHost,labHost]);assert.equal(preferences.disposed,2);assert.equal(sheet._xinjiKind,null);
});
