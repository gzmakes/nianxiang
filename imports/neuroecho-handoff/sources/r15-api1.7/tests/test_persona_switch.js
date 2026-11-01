const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'persona-switch.js'), 'utf8');

test('switching persona preserves the shared conversation and uses companion mode', async () => {
  const calls = [];
  const storage = new Map([['xinji_session', 'session']]);
  const messages = {querySelectorAll: () => [], querySelector: () => null, prepend() {}};
  const topics = [];
  const workspace = {topics: {}, setTopic: topic => topics.push(topic)};
  const document = {
    readyState: 'complete', documentElement: {dataset: {}},
    querySelector: selector => selector === '#app #messages, #m-app #m-messages' ? messages : null,
    querySelectorAll: () => [], addEventListener() {}, createElement: () => ({hidden: false, textContent: ''}),
  };
  const context = vm.createContext({
    document, window: {XinjiWorkspace: workspace},
    localStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value)},
    fetch: async (url, options) => {
      calls.push({url, options});
      return {ok: true, json: async () => ({session: {id: 'session', persona_id: 'nianxiang', interaction_mode: 'companion'}})};
    },
    MutationObserver: class {observe() {} takeRecords() {}},
    setInterval: () => 1, clearInterval() {}, Date, CustomEvent: class {},
  });
  vm.runInContext(source, context);
  await new Promise(resolve => setImmediate(resolve));

  await context.window.XinjiSpaces.switchTo('whale:work');
  assert.equal(context.window.XinjiSpaces.current(), 'whale:companion');
  assert.equal(document.documentElement.dataset.persona, 'whale');
  assert.equal(topics.at(-1), '小鲸鱼·陪伴');
  assert.equal(JSON.parse(storage.get('xinji_space_v1')).current, 'whale:companion');
  const updates = calls.filter(call => call.options?.method === 'PUT');
  assert.deepEqual(updates.map(call => call.url), ['/api/session/session/persona', '/api/session/session/mode']);
  assert.equal(JSON.parse(updates[0].options.body).persona_id, 'whale');
  assert.equal(JSON.parse(updates[1].options.body).interaction_mode, 'companion');

  await context.window.XinjiSpaces.switchTo('whale:work');
  assert.equal(calls.filter(call => call.options?.method === 'PUT').length, 2);
});
