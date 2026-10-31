const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../web/connector-auth.js'), 'utf8');

function harness(fetch) {
  const node = () => ({textContent: '', disabled: false, attrs: {}, classList: {toggle() {}, add() {}},
    removeAttribute(key) { delete this.attrs[key]; }});
  const button = node(), status = node(), link = node(), code = node();
  link.nextElementSibling = code;
  const panel = {isConnected: true, hidden: false, closest() { return this.hidden ? {} : null; },
    querySelector(selector) { return {'button': button, '[role=status]': status, 'a': link}[selector]; }};
  const context = {document: {createElement() { return panel; }}, URL, fetch, Date,
    setTimeout(callback) { callback(); }};
  vm.runInNewContext(source, context);
  context.XinjiConnectorAuth.mount({append() {}}, 'github');
  return {api: context.XinjiConnectorAuth, panel, button, status, link, code};
}

test('official URLs only; malformed and lookalike URLs are hidden', () => {
  const h = harness();
  assert.equal(h.api.safeUrl('github', 'https://github.com/login/device'), 'https://github.com/login/device');
  for (const value of ['javascript:alert(1)', 'https://github.com.evil.invalid/login', 'https://x@github.com/login', 'https://github.com:444/login']) {
    assert.equal(h.api.safeUrl('github', value), '');
  }
});

test('login transitions from pending to success without importing sources', async () => {
  const requests = [];
  const states = [{status: 'pending', code: 'ABCD-1234', url: 'https://github.com/login/device', message: 'Confirm'},
    {status: 'success', message: 'Read and review selected data'}];
  const h = harness(async (url, options) => {
    requests.push([url, options.method]);
    return {ok: true, json: async () => states.shift()};
  });
  await h.button.onclick();
  assert.equal(h.status.textContent, 'Read and review selected data');
  assert.equal(h.code.textContent, '');
  assert.equal(h.button.disabled, false);
  assert.deepEqual(requests, [['/api/connector-auth/github/start', 'POST'], ['/api/connector-auth/github/status', 'GET']]);
});

test('a late login response cannot update a closed source dialog', async () => {
  let resolve;
  const h = harness(() => new Promise(done => { resolve = done; }));
  const pending = h.button.onclick();
  h.panel.hidden = true;
  resolve({ok: true, json: async () => ({status: 'success', message: 'stale'})});
  await pending;
  assert.notEqual(h.status.textContent, 'stale');
});

test('missing dependencies and failed requests remain retryable', async () => {
  const h = harness(async () => ({ok: true, json: async () => ({status: 'needs_install', message: 'Administrator setup required'})}));
  await h.button.onclick();
  assert.equal(h.status.textContent, 'Administrator setup required');
  assert.equal(h.button.disabled, false);
});
