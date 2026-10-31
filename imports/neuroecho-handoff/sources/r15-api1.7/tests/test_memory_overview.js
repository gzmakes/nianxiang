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

test('overview derives only from confirmed live records and distinguishes pending and deleted', () => {
  const f = fixture(); f.setCards(rows); f.overview.render(rows, 'session-one');
  const summary = f.find('.memory-summary');
  assert.match(summary.textContent, /我喜欢合成绿茶/);
  assert.doesNotMatch(summary.textContent, /合成的项目内容|已删除的合成内容/);
  assert.match(summary.textContent, /1 条其他记录未计入了解/);
  assert.equal(f.list.hidden, true);
  assert.equal(f.find('.memory-overview').hidden, false);
});

test('category navigation filters existing cards, preserves their edit state, and back returns to overview', () => {
  const f = fixture(); f.setCards(rows); const card = f.list.children[0]; const edit = card.querySelector('textarea');
  f.overview.render(rows, 'session-one'); f.find('[data-memory-group="preferences"]').dispatch('click');
  assert.equal(f.list.hidden, false); assert.equal(card.hidden, false); assert.equal(f.list.children[1].hidden, true); assert.equal(f.list.children[2].hidden, true);
  assert.equal(card.querySelector('textarea'), edit); assert.equal(edit.value, '未提交的草稿');
  f.find('[data-memory-back]').dispatch('click'); assert.equal(f.list.hidden, true); assert.equal(f.find('.memory-overview').hidden, false);
  f.find('[data-memory-all]').dispatch('click'); assert.equal(card.hidden, false); assert.equal(f.list.children[1].hidden, false); assert.equal(f.list.children[2].hidden, true);
});

test('corrected category persists without storing text, and sessions stay isolated', () => {
  const f = fixture(); f.setCards(rows); f.overview.render(rows, 'session-one'); f.overview.showAll();
  let select = f.list.children[0].querySelector('[data-memory-category]'); select.value = 'life'; select.dispatch('change');
  const saved = f.values.get('xinji.memory.category.v1'); assert.ok(saved); assert.doesNotMatch(saved, /合成绿茶|项目内容/);
  f.setCards(rows); f.overview.render(rows, 'session-one'); f.find('[data-memory-group="life"]').dispatch('click'); assert.equal(f.list.children[0].hidden, false);
  f.setCards(rows); f.overview.render(rows, 'session-two'); assert.equal(f.find('.memory-overview').hidden, false);
  f.find('[data-memory-group="life"]').dispatch('click'); assert.equal(f.list.children[0].hidden, true);
  f.find('[data-memory-back]').dispatch('click'); f.overview.render(rows, 'session-one'); f.find('[data-memory-group="life"]').dispatch('click'); assert.equal(f.list.children[0].hidden, false);
});

test('removed and deleted records disappear after refresh and cannot leave stale summary or category entries', () => {
  const f = fixture(); f.setCards(rows); f.overview.render(rows, 'session-one'); f.overview.showAll();
  const select = f.list.children[0].querySelector('[data-memory-category]'); select.value = 'life'; select.dispatch('change');
  const next = [{...rows[0], status:'deleted'}]; f.setCards(next); f.overview.render(next, 'session-one');
  f.find('[data-memory-back]').dispatch('click'); assert.doesNotMatch(f.find('.memory-summary').textContent, /合成绿茶/);
  assert.match(f.find('[data-memory-group="life"]').textContent, /0 条记忆/);
  const saved = JSON.parse(f.values.get('xinji.memory.category.v1') || '{}'); assert.equal(saved['session-one']?.a, undefined);
});

const summaryRows = [
  {id:'a', text:'我喜欢合成绿茶', kind:'fact', status:'confirmed', version:1, source:'合成来源'},
  {id:'b', text:'我喜欢合成音乐', kind:'fact', status:'confirmed', version:2, source:'合成来源'},
  {id:'c', text:'我喜欢待确认内容', kind:'fact', status:'candidate', version:1}
];
function choose(f, id) {
  const checkbox = f.find(`[data-memory-summary-choice="${id}"]`); assert.ok(checkbox); checkbox.checked = true; checkbox.dispatch('change');
}
function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return {promise, resolve}; }
function response(summary='合成总结', evidence=[{id:'a', version:1, text:'我喜欢合成绿茶', source:'合成来源'}]) { return {ok:true, status:200, json:async () => ({summary, evidence})}; }

test('model summary is opt-in, defaults to no selection, and cancellation never calls the service', async () => {
  let confirmations = 0, calls = 0; const f = fixture({confirm:async () => { confirmations++; return false; }, fetch:async () => { calls++; return response(); }});
  f.setCards(summaryRows); f.overview.render(summaryRows, 's');
  assert.equal(f.find('[data-memory-generate]').disabled, true);
  assert.equal(f.find('[data-memory-summary-choice="a"]').checked, false);
  assert.equal(f.find('[data-memory-summary-choice="b"]').checked, false);
  assert.equal(f.find('[data-memory-summary-choice="c"]'), null);
  await f.find('[data-memory-generate]').dispatch('click'); assert.equal(confirmations, 0); assert.equal(calls, 0);
  choose(f, 'a'); assert.equal(f.find('[data-memory-generate]').disabled, false);
  await f.find('[data-memory-generate]').dispatch('click'); assert.equal(confirmations, 1); assert.equal(calls, 0);
});

test('approved summary sends only selected IDs and versions and labels the result with evidence', async () => {
  const requests = [], confirmations = [];
  const f = fixture({confirm:async args => {confirmations.push(args); return true;}, fetch:async (url, options) => {requests.push({url, options}); return response();}});
  f.setCards(summaryRows); f.overview.render(summaryRows, 's'); choose(f, 'a');
  await f.find('[data-memory-generate]').dispatch('click');
  assert.equal(requests.length, 1); assert.equal(requests[0].url, '/api/memory/summary'); assert.equal(requests[0].options.method, 'POST');
  assert.deepEqual(JSON.parse(requests[0].options.body), {session_id:'s', confirm:true, memories:[{id:'a',version:1}]});
  assert.match(confirmations[0].message, /完整内容.*模型服务/);
  assert.match(f.find('.memory-generated').textContent, /模型生成，待核对/);
  assert.match(f.find('.memory-generated').textContent, /合成总结/);
  assert.match(f.find('.memory-summary-evidence').textContent, /合成绿茶/);
  assert.doesNotMatch(f.find('.memory-generated').textContent, /合成音乐/);
  const stored = [...f.values.values()].join(''); assert.doesNotMatch(stored, /合成总结|合成绿茶/);
});

test('failure is surfaced and leaves an explicit retry available', async () => {
  const f = fixture({fetch:async () => ({ok:false, status:503, json:async () => ({detail:'合成服务暂不可用'})})});
  f.setCards(summaryRows); f.overview.render(summaryRows, 's'); choose(f, 'a'); await f.find('[data-memory-generate]').dispatch('click');
  assert.match(f.find('.memory-summary-status').textContent, /合成服务暂不可用/);
  assert.equal(f.find('.memory-generated'), null); assert.equal(f.find('[data-memory-generate]').disabled, false);
});

test('a changed version invalidates a completed summary and clears its selected inputs', async () => {
  const f = fixture({fetch:async () => response()}); f.setCards(summaryRows); f.overview.render(summaryRows, 's'); choose(f, 'a');
  await f.find('[data-memory-generate]').dispatch('click'); assert.ok(f.find('.memory-generated'));
  const changed = [{...summaryRows[0], version:2, text:'我喜欢合成红茶'}, ...summaryRows.slice(1)]; f.setCards(changed); f.overview.render(changed, 's');
  assert.equal(f.find('.memory-generated'), null); assert.match(f.find('.memory-summary-status').textContent, /记忆已变化/);
  assert.equal(f.find('[data-memory-summary-choice="a"]').checked, false); assert.equal(f.find('[data-memory-generate]').disabled, true);
});

test('a changed version or session discards an in-flight model response', async () => {
  for (const change of ['version','session']) {
    const pending = deferred(), f = fixture({fetch:async () => pending.promise});
    f.setCards(summaryRows); f.overview.render(summaryRows, 's'); choose(f, 'a');
    const running = f.find('[data-memory-generate]').dispatch('click'); await Promise.resolve(); await Promise.resolve();
    const changed = change === 'version' ? [{...summaryRows[0], version:2}, ...summaryRows.slice(1)] : summaryRows;
    f.setCards(changed); f.overview.render(changed, change === 'session' ? 'other' : 's');
    pending.resolve(response()); await running;
    assert.equal(f.find('.memory-generated'), null); assert.equal(f.find('[data-memory-summary-choice="a"]').checked, false);
    assert.equal(f.find('[data-memory-generate]').disabled, true);
  }
});


test('automatic facts enter the overview and selectable summary, while guesses and legacy candidates do not', () => {
  const records = [
    {id:'auto', text:'我喜欢合成红茶', kind:'fact', status:'auto', version:1, source:'对话原话 · 自动记录'},
    {id:'guess', text:'我喜欢合成咖啡', kind:'inference', status:'candidate', version:1},
    {id:'old', text:'我喜欢合成气泡水', kind:'fact', status:'candidate', version:1},
    {id:'stale', text:'我喜欢合成饮料', kind:'fact', status:'auto', version:1, source:'撤回后来源待核对'}
  ];
  const f = fixture(); f.setCards(records); f.overview.render(records, 's');
  const summary = f.find('.memory-summary');
  assert.match(summary.textContent, /合成红茶/);
  assert.doesNotMatch(summary.textContent, /合成咖啡|合成气泡水|合成饮料/);
  assert.ok(f.find('[data-memory-summary-choice="auto"]'));
  assert.equal(f.find('[data-memory-summary-choice="guess"]'), null);
  assert.equal(f.find('[data-memory-summary-choice="old"]'), null);
  assert.equal(f.find('[data-memory-summary-choice="stale"]'), null);
  assert.equal(f.find('.memory-summary-evidence').open, undefined);
});

test('PC and H5 cards distinguish memory states and allow confirmation of automatic records', () => {
  const desktop = fs.readFileSync('web/app.js', 'utf8');
  const mobile = fs.readFileSync('web/m.js', 'utf8');
  const globals = {esc: value => String(value), memorySourceLabel: record => record.source || '', mobileSources: () => []};
  const pc = vm.createContext({...globals});
  vm.runInContext(desktop.slice(desktop.indexOf('  function memoryPresentation('), desktop.indexOf('\n  function renderBookmark()')) + '\nthis.card=memoryItem;', pc);
  const h5 = vm.createContext({...globals});
  vm.runInContext(mobile.slice(mobile.indexOf('  function memCard('), mobile.indexOf('\n  function renderUnderstanding()', mobile.indexOf('  function memCard('))) + '\nthis.card=memCard;', h5);
  const samples = [
    [{id:'a',kind:'fact',status:'auto',source:'对话原话 · 自动记录',version:1,text:'我喜欢茶'}, /自动记录/, /自动记下/],
    [{id:'b',kind:'fact',status:'auto',source:'用户手动添加',version:1,text:'我喜欢音乐'}, /你已添加/, /你主动记下/],
    [{id:'c',kind:'fact',status:'candidate',source:'资料',version:1,text:'旧资料'}, /尚未核实/, /不作为确定事实/],
    [{id:'d',kind:'inference',status:'candidate',source:'资料',version:1,text:'可能喜欢散步'}, /推测/, /不作为确定事实/],
    [{id:'e',kind:'fact',status:'auto',source:'撤回后来源待核对',version:1,text:'已撤回'}, /自动记录/, /暂不用于回复/]
  ];
  for (const [record, label, use] of samples) for (const card of [pc.card(record), h5.card(record, record.kind)]) {
    assert.match(card, label); assert.match(card, use);
    if (record.id === 'a') assert.match(card, /data-act="confirm"/);
    else assert.doesNotMatch(card, /data-act="confirm"/);
    assert.match(card, /data-act="edit"/); assert.match(card, /data-act="delete"/);
  }
});


test('editing an automatic fact updates the overview and invalidates the old summary selection', () => {
  const f = fixture();
  const initial = [{id:'auto', text:'我喜欢合成红茶', kind:'fact', status:'auto', version:1, source:'对话原话 · 自动记录'}];
  f.setCards(initial); f.overview.render(initial, 's'); choose(f, 'auto');
  const corrected = [{...initial[0], version:2, text:'我喜欢合成绿茶', source:'对话原话 · 用户纠正'}];
  f.setCards(corrected); f.overview.render(corrected, 's');
  assert.match(f.find('.memory-summary').textContent, /合成绿茶/);
  assert.doesNotMatch(f.find('.memory-summary').textContent, /合成红茶/);
  assert.equal(f.find('[data-memory-summary-choice="auto"]').checked, false);
});


test('trusted automatic personal statements are not lost to narrow wording patterns', () => {
  const records = [
    {id:'usual', text:'我平时喜欢听音乐', kind:'fact', status:'auto', version:1, source:'对话原话 · 自动记录'},
    {id:'corrected', text:'通常听轻音乐', kind:'fact', status:'auto', version:2, source:'对话原话 · 用户纠正'},
    {id:'manual', text:'周末喜欢散步', kind:'fact', status:'auto', version:1, source:'用户手动添加'},
    {id:'guess', text:'我平时可能喜欢音乐', kind:'inference', status:'auto', version:1, source:'对话原话 · 自动记录'},
    {id:'old', text:'我平时喜欢画画', kind:'fact', status:'candidate', version:1, source:'对话原话 · 自动记录'},
    {id:'untrusted', text:'我喜欢电影', kind:'fact', status:'auto', version:1, source:'未核实资料'},
    {id:'stale', text:'我平时喜欢旅行', kind:'fact', status:'auto', version:1, source:'撤回后来源待核对'}
  ];
  const f = fixture(); f.setCards(records); f.overview.render(records, 's');
  const summary = f.find('.memory-summary');
  assert.match(summary.textContent, /我平时喜欢听音乐/);
  assert.match(summary.textContent, /通常听轻音乐/);
  assert.match(summary.textContent, /周末喜欢散步/);
  for (const id of ['usual','corrected','manual']) assert.ok(f.find(`[data-memory-summary-choice="${id}"]`));
  for (const id of ['guess','old','untrusted','stale']) assert.equal(f.find(`[data-memory-summary-choice="${id}"]`), null);
});
