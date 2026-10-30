// Actual H5 renderMessages with the shared scroll controller; no services or accounts.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {createChatScroll} = require('../web/chat-scroll.js');
const source = fs.readFileSync('web/m.js', 'utf8');
const first = source.indexOf('  function renderMessages(');
const last = source.indexOf('  let mAuthTimer', first);
assert.ok(first >= 0 && last > first);

function element() {
  const classes = new Set();
  return {innerHTML: '', value: '', scrollTop: 400, scrollHeight: 1100, clientHeight: 500,
    classList: {add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x),
      toggle: (x, on) => on ? classes.add(x) : classes.delete(x)},
    addEventListener() {}, querySelectorAll: () => []};
}
function setup({mode = 'empty', messages = [], context = null} = {}) {
  const nodes = new Map();
  const $ = id => {if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id);};
  const state = {session: {id: 'session-a', mode}, messages, context};
  $('#m-input').value = '尚未发送的草稿';
  const ctx = vm.createContext({$, state, memoryProposal: {sync() {}},
    chatScroll: createChatScroll($('#m-main'), $('#m-chat-new-messages')),
    window: {XinjiVoice:{pruneClips(){}},XinjiActionCards: {chatDraft: () => null}}, esc: String, renderMemeText: String,
    send() {assert.fail('render must not send');}, openMobileAction() {assert.fail('render must not create action');}});
  vm.runInContext('let renderedChatSession=null,renderedAssistantId=null;\n' + source.slice(first, last) + '\nthis.render=renderMessages;', ctx);
  return {$, state, render: ctx.render};
}

test('an untouched empty hero starts at the top even when its content exceeds the viewport', () => {
  const e = setup({messages: [{id: 'intro', role: 'assistant', text: '旧的初始化介绍'}]});
  e.$('#m-chat-new-messages').classList.remove('is-hidden');
  e.render(true);
  assert.equal(e.$('#m-chat-empty').classList.contains('is-hidden'), false);
  assert.equal(e.$('#m-main').scrollTop, 0);
  assert.equal(e.$('#m-messages').innerHTML, '');
  assert.equal(e.$('#m-chat-new-messages').classList.contains('is-hidden'), true);
  assert.equal(e.$('#m-input').value, '尚未发送的草稿');
});

test('restoring an empty conversation resets a prior conversation scroll position', () => {
  const e = setup({mode: 'connector', messages: [{id: 'greeting', role: 'assistant', text: '来源开场'}]});
  e.render();
  assert.equal(e.$('#m-main').scrollTop, 1100);
  e.state.session = {id: 'restored-empty', mode: 'empty'};
  e.state.messages = [{id: 'intro', role: 'assistant', text: '初始化介绍'}];
  e.render();
  assert.equal(e.$('#m-main').scrollTop, 0);
  assert.equal(e.$('#m-chat-empty').classList.contains('is-hidden'), false);
  e.$('#m-main').scrollTop = 250;
  e.render();
  assert.equal(e.$('#m-main').scrollTop, 0);
});

test('assistant-only source conversations show their actual greeting and suggestions', () => {
  for (const mode of ['connector', 'real', 'paste', 'sample']) {
    const e = setup({mode, messages: [{id: 'greeting', role: 'assistant', text: '读过这份资料，想先听听你的感受。', suggestions: ['聊聊最近的压力']}]});
    e.render();
    assert.equal(e.$('#m-chat-empty').classList.contains('is-hidden'), true);
    assert.match(e.$('#m-messages').innerHTML, /读过这份资料，想先听听你的感受/);
    assert.match(e.$('#m-messages').innerHTML, /聊聊最近的压力/);
    assert.equal(e.$('#m-main').scrollTop, 1100);
  }
});

test('restored source context prevents a stale empty mode from hiding its greeting', () => {
  for (const context of [{sources: [{id: 'source-a'}]}, {connector_id: 'feishu'}, {items: [{title: '旧版资料'}]}]) {
    const e = setup({context, messages: [{id: 'greeting', role: 'assistant', text: '来源问候'}]});
    e.render();
    assert.equal(e.$('#m-chat-empty').classList.contains('is-hidden'), true);
    assert.match(e.$('#m-messages').innerHTML, /来源问候/);
  }
});

test('the first user message releases the hero and follows its reply', () => {
  const e = setup();
  e.render();
  e.state.messages = [{id: 'u', role: 'user', text: '今天有点累'}, {id: 'a', role: 'assistant', text: '我在，慢慢说。'}];
  e.$('#m-main').scrollHeight = 400;
  e.render();
  assert.equal(e.$('#m-chat-empty').classList.contains('is-hidden'), true);
  assert.match(e.$('#m-messages').innerHTML, /今天有点累/);
  assert.match(e.$('#m-messages').innerHTML, /我在，慢慢说/);
  assert.equal(e.$('#m-main').scrollTop, 400);
});

test('an existing conversation preserves reader scroll and offers a new-reply notice', () => {
  const e = setup({messages: [{id: 'u', role: 'user', text: '聊过的话'}, {id: 'a', role: 'assistant', text: '旧回复'}]});
  e.render();
  e.$('#m-main').scrollTop = 80;
  e.state.messages.push({id: 'new', role: 'assistant', text: '新回复'});
  e.render();
  assert.equal(e.$('#m-main').scrollTop, 80);
  assert.equal(e.$('#m-chat-new-messages').classList.contains('is-hidden'), false);
  e.render(true);
  assert.equal(e.$('#m-main').scrollTop, 1100);
  assert.equal(e.$('#m-chat-new-messages').classList.contains('is-hidden'), true);
});
