const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('web/task-panel.js', 'utf8');
const KEY = 'xinji_personal_tasks_v1';
const MIME = 'application/x-xinji-task-prompt';

function node() {
  return {
    children: [], listeners: {}, dataset: {}, attributes: {}, hidden: false, value: '', textContent: '',
    classList: {values: new Set(), add(x) { this.values.add(x); }, remove(x) { this.values.delete(x); }, contains(x) { return this.values.has(x); }},
    append(...nodes) { this.children.push(...nodes); }, replaceChildren(...nodes) { this.children = nodes; },
    setAttribute(key, value) { this.attributes[key] = value; },
    addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); },
    dispatchEvent(event) { for (const callback of this.listeners[event.type] || []) callback(event); return !event.defaultPrevented; },
    focus() { this.focused = true; },
  };
}
function event(type, extra = {}) {
  return {type, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...extra};
}
function storage(existing = new Map()) {
  return {getItem: key => existing.get(key) ?? null, setItem: (key, value) => existing.set(key, value), values: existing};
}
function transfer(initial = {}) {
  const data = {...initial};
  return {get types() { return Object.keys(data); }, setData(type, value) { data[type] = value; }, getData(type) { return data[type] || ''; }};
}
function setup(store = storage()) {
  const root = node(), legacy = node(), input = node(), composer = node(), form = node(), status = node();
  const defaultView = node(), mineView = node(), defaults = node(), mine = node();
  const create = node(), cancel = node(), mineButton = node(), defaultButton = node();
  mineButton.dataset.taskView = 'mine'; defaultButton.dataset.taskView = 'default';
  form.hidden = true;
  form.elements = {title: node(), detail: node()};
  form.reset = () => { form.elements.title.value = ''; form.elements.detail.value = ''; };
  defaultView.querySelector = selector => selector === '.task-cards' ? defaults : null;
  mineView.querySelector = selector => selector === '.task-cards' ? mine : null;
  const nodes = {'.task-create-form': form, '.task-status': status, '.task-default-view': defaultView,
    '.task-mine-view': mineView, '.task-create-link': create, '.task-form-cancel': cancel};
  root.querySelector = selector => nodes[selector];
  root.querySelectorAll = selector => selector === '[data-task-view]' ? [mineButton, defaultButton] : [];
  const document = {getElementById: id => ({'task-panel-enhancements': root, 'task-legacy': legacy, input, composer})[id], createElement: () => node()};
  const windowEvents = {};
  const window = {addEventListener(type, fn) { windowEvents[type] = fn; }, XinjiComposerDraft: {save() { saves++; }}};
  let saves = 0;
  vm.runInNewContext(source, {document, window, localStorage: store, Event: class { constructor(type, options) { this.type = type; this.bubbles = options.bubbles; } }});
  const click = element => element.dispatchEvent(event('click'));
  return {root, legacy, input, composer, form, status, defaultView, mineView, defaults, mine, create, cancel, mineButton, defaultButton, store, windowEvents, click, saves: () => saves};
}

test('adding a default suggestion keeps the existing draft and does not send it', () => {
  const env = setup(); env.input.value = '我原来的草稿';
  let inputEvents = 0; env.input.addEventListener('input', () => inputEvents++);
  env.click(env.defaults.children[0].children[2]);
  assert.equal(env.input.value, '我原来的草稿\n把你今天要做的事情列清楚，排出最值得先完成的一件。');
  assert.equal(inputEvents, 1); assert.equal(env.saves(), 1); assert.equal(env.input.focused, true);
});

test('create task preserves a draft and focuses the conversation without a form', () => {
  const env = setup(); env.input.value = '原草稿';
  env.click(env.create);
  assert.equal(env.input.value, '原草稿\n我要创建任务：');
  assert.equal(env.input.focused, true); assert.equal(env.saves(), 1);
  assert.doesNotMatch(env.root.innerHTML, /task-create-form|自己创建的任务保存在此浏览器/);
});

test('task views show existing user tasks and keep old unrelated actions hidden', () => {
  const store = storage(new Map([[KEY, JSON.stringify([{title: '我的计划', detail: '帮我拆解计划'}])]]));
  const env = setup(store);
  assert.equal(env.defaultView.hidden, false); assert.equal(env.legacy.hidden, true);
  env.click(env.mineButton);
  assert.equal(env.mineView.hidden, false); assert.equal(env.legacy.hidden, true);
  assert.equal(env.mine.children[0].children[1].children[0].textContent, '我的计划');
  assert.match(env.root.innerHTML, /自动任务/);
  env.click(env.defaultButton);
  assert.equal(env.legacy.hidden, true); assert.equal(env.defaultView.hidden, false);
});

test('empty personal tasks provide a clear next step', () => {
  const env = setup(); env.click(env.mineButton);
  assert.equal(env.mine.children[0].textContent, '这里空空如也，点击上方去创建一个任务吧！');
});

test('drop only accepts task cards and leaves ordinary text drops to the browser', () => {
  const env = setup(); env.input.value = '草稿';
  const ordinary = event('drop', {dataTransfer: transfer({'text/plain': '外部文字'})});
  env.input.dispatchEvent(ordinary); assert.equal(ordinary.defaultPrevented, false); assert.equal(env.input.value, '草稿');
  const data = transfer(); env.defaults.children[1].dispatchEvent(event('dragstart', {dataTransfer: data}));
  assert.ok(data.types.includes(MIME));
  const over = event('dragover', {dataTransfer: data}); env.input.dispatchEvent(over);
  assert.equal(over.defaultPrevented, true); assert.equal(env.composer.classList.contains('task-drop-active'), true);
  const drop = event('drop', {dataTransfer: data}); env.input.dispatchEvent(drop);
  assert.equal(drop.defaultPrevented, true); assert.equal(env.composer.classList.contains('task-drop-active'), false);
  assert.equal(env.input.value, '草稿\n把一个目标拆成几步，明确下一步现在就能开始做什么。');
});
