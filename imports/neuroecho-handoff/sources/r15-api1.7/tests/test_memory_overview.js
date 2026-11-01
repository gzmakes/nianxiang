// Synthetic records only: the overview must remain a view over real, editable memory cards.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync('web/memory-overview.js', 'utf8');

class Element {
  constructor(tag) { this.tagName = tag.toLowerCase(); this.children = []; this.parentNode = null; this.dataset = {}; this.attributes = {}; this.hidden = false; this.className = ''; this.listeners = {}; this._text = ''; this.value = ''; }
  append(...nodes) { for (const node of nodes) { if (node.parentNode) node.parentNode.children.splice(node.parentNode.children.indexOf(node), 1); this.children.push(node); node.parentNode = this; } }
  insertBefore(node, reference) { if (node.parentNode) node.parentNode.children.splice(node.parentNode.children.indexOf(node), 1); this.children.splice(this.children.indexOf(reference), 0, node); node.parentNode = this; }
  replaceChildren(...nodes) { this.children.forEach(node => node.parentNode = null); this.children = []; this._text = ''; this.append(...nodes); }
  set textContent(text) { this._text = String(text); this.children.forEach(node => node.parentNode = null); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  dispatch(type) { let result; for (const fn of this.listeners[type] || []) result = fn({target: this}); return result; }
  remove() { if (this.parentNode) { this.parentNode.children.splice(this.parentNode.children.indexOf(this), 1); this.parentNode = null; } }
  focus() {}
  matches(selector) {
    const parts = selector.split(/(?=\[)/); const head = parts[0].startsWith('[') ? '' : parts.shift();
    if (head && head.startsWith('.') && !this.className.split(/\s+/).includes(head.slice(1))) return false;
    if (head && !head.startsWith('.') && this.tagName !== head) return false;
    return parts.every(part => { const m = part.match(/^\[data-([\w-]+)(?:="([^"]*)")?\]$/); if (!m) return false; const key = m[1].replace(/-([a-z])/g, (_, c) => c.toUpperCase()); return Object.hasOwn(this.dataset, key) && (m[2] === undefined || this.dataset[key] === m[2]); });
  }
  querySelectorAll(selector) { const result = []; const visit = node => { for (const child of node.children) { if (child.matches(selector)) result.push(child); visit(child); } }; visit(this); return result; }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}
function fixture(options = {}) {
  const values = new Map(); const root = new Element('main'); const list = new Element('div'); root.append(list);
  const localStorage = {getItem: key => values.get(key) || null, setItem: (key, value) => values.set(key, value)};
  const context = vm.createContext({window: {XinjiDialogs: {confirm: options.confirm || (async () => true)}}, document: {createElement: tag => new Element(tag)}, localStorage, fetch: options.fetch || (() => { throw Error('unexpected fetch'); })});
  vm.runInContext(fs.readFileSync('web/memory-insights.js', 'utf8'), context);
  vm.runInContext(code, context);
  const overview = context.window.XinjiMemoryOverview.mount({list});
  function setCards(records) { list.replaceChildren(...records.map(record => { const card = new Element('div'); card.className = 'mem-item'; card.dataset.id = record.id; const edit = new Element('textarea'); edit.value = '未提交的草稿'; card.append(edit); return card; })); }
  return {root, list, overview, values, setCards, find: selector => root.querySelector(selector)};
}
const rows = [
  {id:'a', text:'我喜欢合成绿茶', kind:'fact', status:'confirmed', version:1, created_at:'2026-01-02'},
  {id:'b', text:'合成的项目内容', kind:'fact', status:'candidate', version:1, created_at:'2026-01-03'},
  {id:'c', text:'已删除的合成内容', kind:'fact', status:'deleted', version:1, created_at:'2026-01-04'}
];

test('overview presents concise grounded facts without sources or the removed controls', () => {
  const records = [
    {id:'a', text:'我喜欢合成绿茶', kind:'fact', status:'confirmed', source:'私人来源', version:1},
    {id:'b', text:'我喜欢合成红茶', kind:'fact', status:'candidate', version:1},
    {id:'c', text:'过时内容', kind:'fact', status:'confirmed', source_attachment_id:'stale', version:1},
    {id:'d', text:'我喜欢合成咖啡', kind:'inference', status:'confirmed', version:1}
  ];
  const f=fixture(); f.setCards(records); f.overview.render(records, 's', [{id:'stale',stale:true}]);
  const summary=f.find('.memory-summary'); assert.match(summary.textContent, /你喜欢合成绿茶/);
  assert.doesNotMatch(summary.textContent, /私人来源|合成红茶|过时内容|合成咖啡|查看全部记忆|待核对/);
  assert.equal(f.find('[data-memory-all]'), null); assert.equal(f.find('[data-memory-generate]'), null);
  f.find('[data-memory-pending]').dispatch('click'); assert.equal(f.list.children[1].hidden, false); assert.equal(f.list.children[0].hidden, true);
});

test('review filters questions, generic insights and duplicates, and shows at most five at a time without mutating data', () => {
  const records=Array.from({length:7}, (_,i)=>({id:`p${i}`,text:`我喜欢品种${i}`,kind:'fact',status:'candidate',version:1}));
  records.push({...records[0],id:'duplicate'}, {id:'question',kind:'question',status:'candidate',text:'「日历」需要我先帮你做什么？'},
    {id:'insight',kind:'inference',status:'candidate',text:'洞察（pattern）：本次展示 5 条提醒'}, {id:'other',kind:'fact',status:'candidate',text:'项目有三项安排'});
  const before=JSON.stringify(records), f=fixture(); f.setCards(records); f.overview.render(records,'s',[]);
  assert.match(f.find('[data-memory-pending]').textContent, /5 条/); f.find('[data-memory-pending]').dispatch('click');
  assert.equal(f.list.children.filter(card=>!card.hidden).length,5); assert.equal(f.find('[data-memory-more]'),null);
  f.find('[data-memory-back]').dispatch('click'); f.find('[data-memory-group="other"]').dispatch('click');
  assert.equal(f.list.children[5].hidden,false); assert.equal(JSON.stringify(records),before);
});

test('summary avoids unconfirmed automatic memories and changes immediately after explicit correction', () => {
  const f=fixture(), old={id:'auto',text:'我喜欢合成红茶',kind:'fact',status:'auto',source:'对话原话 · 自动记录',version:1};
  f.setCards([old]); f.overview.render([old],'s',[]); assert.doesNotMatch(f.find('.memory-summary').textContent,/合成红茶/);
  const corrected={...old,text:'我喜欢合成绿茶',source:'对话原话 · 用户纠正',version:2}; f.setCards([corrected]); f.overview.render([corrected],'s',[]);
  assert.match(f.find('.memory-summary').textContent,/你喜欢合成绿茶/);
});

test('local understanding uses authorized reminder titles without claiming unverified traits', () => {
  const source = {id:'r', connector_id:'apple_reminders', stale:false, items:[
    {type:'提醒',title:'准备合成报告',modified_at:'2026-10-30'},
    {type:'提醒',title:'新建提醒',modified_at:'2026-10-29'},
    {type:'提醒',title:'准备合成报告',modified_at:'2026-10-28'},
    {type:'提醒',title:'待判断？',modified_at:'2026-10-27'}
  ]};
  const f=fixture(); f.setCards([]); f.overview.render([], 's', [source]);
  assert.match(f.find('.memory-summary').textContent,/你曾有提醒「准备合成报告」/);
  assert.doesNotMatch(f.find('.memory-summary').textContent,/新建提醒|待判断/);
  assert.doesNotMatch(f.find('[data-memory-group="other"]').textContent,/0 条记忆/);
  f.overview.render([], 's', [{...source,stale:true}]); assert.doesNotMatch(f.find('.memory-summary').textContent,/合成报告/);
  f.overview.render([], 's', [{...source,connector_id:'local_files'}]); assert.doesNotMatch(f.find('.memory-summary').textContent,/合成报告/);
});

test('category navigation retains editable cards and user changes', () => {
  const f=fixture(); f.setCards(rows); const edit=f.list.children[0].querySelector('textarea'); f.overview.render(rows,'s');
  f.find('[data-memory-group="preferences"]').dispatch('click'); assert.equal(f.list.children[0].hidden,false); assert.equal(edit.value,'未提交的草稿');
  f.find('[data-memory-back]').dispatch('click'); assert.equal(f.list.hidden,true);
});

test('mobile overview uses the same grounded summary, no automatic-record module, and a maximum of five pending cards', () => {
  const mobile=fs.readFileSync('web/m.js','utf8'), body={innerHTML:''}, add={};
  const records=[{id:'ok',kind:'fact',status:'confirmed',text:'我喜欢茶',source:'私人来源'},
    ...Array.from({length:7},(_,i)=>({id:`p${i}`,kind:'fact',status:'candidate',text:`我喜欢品种${i}`})),
    {id:'question',kind:'question',status:'candidate',text:'你喜欢什么？'}];
  const state={memorySaving:false,session:{id:'s'},memories:records}, window={};
  const context=vm.createContext({state,window,mobileMemoryReviewOffset:0,mobileSources:()=>[],esc:String,
    memCard:m=>`<article data-id="${m.id}">${m.text}</article>`,addMobileMemoryPrompt:()=>{},
    $:selector=>selector==='#m-sheet-body'?body:selector==='#m-memory-more'?null:add});
  vm.runInContext(fs.readFileSync('web/memory-insights.js','utf8'),context);
  vm.runInContext(mobile.slice(mobile.indexOf('  function renderUnderstanding()'),mobile.indexOf('  let mobileManualMemoryOperation'))+'\nthis.render=renderUnderstanding;',context);
  context.render(); assert.match(body.innerHTML,/你喜欢茶/); assert.match(body.innerHTML,/有 5 条/);
  assert.doesNotMatch(body.innerHTML,/自动记录|私人来源/);
  const overview=body.innerHTML.split('<summary>其他记忆</summary>')[0]; assert.doesNotMatch(overview,/你喜欢什么|品种5/);
});

test('PC and H5 cards distinguish memory states and allow confirmation of automatic records', () => {
  const desktop = fs.readFileSync('web/app.js', 'utf8');
  const mobile = fs.readFileSync('web/m.js', 'utf8');
  const globals = {esc: value => String(value), memorySourceLabel: record => record.source || '', mobileSources: () => [], connectedSources: () => []};
  const pc = vm.createContext({...globals});
  vm.runInContext(desktop.slice(desktop.indexOf('  function memoryPresentation('), desktop.indexOf('\n  function renderBookmark()')) + '\nthis.card=memoryItem;', pc);
  const h5 = vm.createContext({...globals});
  vm.runInContext(mobile.slice(mobile.indexOf('  function memCard('), mobile.indexOf('\n  function renderUnderstanding()', mobile.indexOf('  function memCard('))) + '\nthis.card=memCard;', h5);
  const samples = [
    [{id:'a',kind:'fact',status:'auto',source:'对话原话 · 自动记录',version:1,text:'我喜欢茶'}, /自动记录/, /自动记下/],
    [{id:'b',kind:'fact',status:'auto',source:'用户手动添加',version:1,text:'我喜欢音乐'}, /你已添加/, /你主动记下/],
    [{id:'c',kind:'fact',status:'candidate',source:'资料',version:1,text:'旧资料'}, /尚未核实/, /不作为确定事实/],
    [{id:'d',kind:'inference',status:'candidate',source:'资料',version:1,text:'可能喜欢散步'}, /推测/, /不作为确定事实/],
    [{id:'e',kind:'fact',status:'auto',source:'撤回后来源待核对',version:1,text:'已撤回'}, /来源待核对/, /暂不用于回复/],
    [{id:'f',kind:'fact',status:'confirmed',source:'资料',source_attachment_id:'missing',version:1,text:'来源已变化'}, /来源待核对/, /仍可能用于回复/]
  ];
  for (const [record, label, use] of samples) for (const card of [pc.card(record), h5.card(record, record.kind)]) {
    assert.match(card, label); assert.match(card, use);
    if (record.id === 'a' || record.id === 'c') assert.match(card, /data-act="confirm"/);
    else assert.doesNotMatch(card, /data-act="confirm"/);
    assert.match(card, /data-act="edit"/); assert.match(card, /data-act="delete"/);
  }
});
