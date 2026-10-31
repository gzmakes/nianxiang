'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');

function setup(api) {
  const toggle = {checked:false, disabled:false, addEventListener(name, callback) {this[name] = callback;}};
  const status = {textContent:''};
  const host = {isConnected:true, innerHTML:'', querySelector(q) {return q === '[data-auto-memory]' ? toggle : status;}};
  const context = {window:{}};
  vm.runInNewContext(fs.readFileSync('web/auto-memory-settings.js', 'utf8'), context);
  context.window.XinjiAutoMemorySettings.mount(host, {api, getSessionId: () => 'test-session'});
  return {host,toggle,status};
}

test('setting loads disabled by default and explicitly saves on/off', async () => {
  let enabled = false;
  const calls = [];
  const ui = setup(async (url, options = {}) => {
    calls.push([url, options.method || 'GET']);
    if (options.method === 'PUT') enabled = JSON.parse(options.body).enabled;
    return {enabled};
  });
  await new Promise(setImmediate);
  assert.equal(ui.toggle.checked, false);
  assert.equal(ui.toggle.disabled, false);
  assert.match(ui.host.innerHTML, /可能随对话发送给当前模型服务/);
  ui.toggle.checked = true; await ui.toggle.change();
  assert.equal(enabled, true); assert.equal(ui.status.textContent, '已开启');
  ui.toggle.checked = false; await ui.toggle.change();
  assert.equal(enabled, false); assert.equal(ui.status.textContent, '已关闭');
  assert.deepEqual(calls.map(x => x[1]), ['GET', 'PUT', 'PUT']);
});

test('failed change does not claim it was saved', async () => {
  const ui = setup(async (_url, options = {}) => {
    if (options.method === 'PUT') throw Error('offline');
    return {enabled:false};
  });
  await new Promise(setImmediate);
  ui.toggle.checked = true; await ui.toggle.change();
  assert.equal(ui.toggle.checked, false);
  assert.match(ui.status.textContent, /未能确认保存/);
});
