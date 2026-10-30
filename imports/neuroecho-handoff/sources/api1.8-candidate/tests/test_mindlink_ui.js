// Deterministic tests of the real MindLink UI functions, without network or hardware.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup(respond, start = async () => ({token: 'test-grant'})) {
  const full = fs.readFileSync('web/app.js', 'utf8');
  const source = full.slice(full.indexOf('  // Explicit, temporary device opt-in.'), full.indexOf('  // ---------------- onboarding wizard'));
  assert.ok(source.includes('function pollMindlink'));
  let now = 0, nextId = 0;
  const timers = new Map(), calls = [];
  const nodes = {'#mindlink-status': {textContent: ''}, '#mindlink-toggle': {textContent: '', disabled: false}};
  const document = {hidden: false};
  const context = vm.createContext({
    AbortController, document, performance: {now: () => now},
    $: selector => nodes[selector],
    setTimeout: (fn, ms) => { const id = ++nextId; timers.set(id, {fn, at: now + ms}); return id; },
    clearTimeout: id => timers.delete(id),
    api: start,
    fetch: (url, options) => { calls.push({url, options}); return respond(url, options, calls); },
  });
  vm.runInContext(source + '\nthis.ui = {toggleMindlink, stopMindlink, mindlinkVisibilityChanged};', context);
  async function flush() { for (let i = 0; i < 8; i++) await Promise.resolve(); }
  async function advance(ms) {
    const end = now + ms;
    while (true) {
      const due = [...timers].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      now = due[1].at; timers.delete(due[0]); due[1].fn(); await flush();
    }
    now = end; await flush();
  }
  return {ui: context.ui, nodes, document, calls, flush, advance};
}
const ok = data => ({ok: true, status: 200, json: async () => data});
const reading = {available: true, score: 72, age_ms: 1000};
const status = t => t.nodes['#mindlink-status'].textContent;

test('old score expires even while next request is stuck', async () => {
  let count = 0;
  const t = setup((url, options) => {
    if (url.endsWith('/stop')) return Promise.resolve(ok({}));
    if (++count === 1) return Promise.resolve(ok(reading));
    return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('aborted'))));
  });
  await t.ui.toggleMindlink(); await t.flush();
  assert.match(status(t), /72/);
  await t.advance(1499); assert.match(status(t), /72/);
  await t.advance(1); assert.doesNotMatch(status(t), /72/); assert.match(status(t), /不可用/);
  await t.advance(1700); assert.ok(t.calls.find(c => c.options.signal?.aborted));
});

test('hidden page clears reading, aborts request and resumes with fresh check', async () => {
  let count = 0, release;
  const t = setup((url) => {
    if (url.endsWith('/stop')) return Promise.resolve(ok({}));
    if (++count === 1) return Promise.resolve(ok(reading));
    if (count === 2) return new Promise(resolve => { release = resolve; });
    return Promise.resolve(ok({...reading, score: 42}));
  });
  await t.ui.toggleMindlink(); await t.flush();
  await t.advance(1200);
  t.document.hidden = true; t.ui.mindlinkVisibilityChanged();
  assert.match(status(t), /已隐藏/);
  release(ok({...reading, score: 99})); await t.flush();
  assert.doesNotMatch(status(t), /99/);
  t.document.hidden = false; t.ui.mindlinkVisibilityChanged(); await t.flush();
  assert.match(status(t), /42/);
});

test('stop discards late reply and releases grant', async () => {
  let release;
  const t = setup(url => url.endsWith('/stop') ? Promise.resolve(ok({})) : new Promise(resolve => { release = resolve; }));
  await t.ui.toggleMindlink(); await t.flush();
  await t.ui.stopMindlink();
  release(ok(reading)); await t.flush();
  assert.equal(status(t), '已停止读取');
  assert.ok(t.calls.some(c => c.url.endsWith('/stop') && c.options.headers['X-MindLink-Token'] === 'test-grant'));
});

test('a forbidden read clears the grant and asks user to re-enable', async () => {
  const t = setup(url => Promise.resolve(url.endsWith('/stop') ? ok({}) : {ok: false, status: 403}));
  await t.ui.toggleMindlink(); await t.flush();
  assert.match(status(t), /授权已结束/);
  assert.equal(t.nodes['#mindlink-toggle'].textContent, '同意并开启读取');
});

test('stale server values are never displayed', async () => {
  const t = setup(() => Promise.resolve(ok({...reading, age_ms: 2500})));
  await t.ui.toggleMindlink(); await t.flush();
  assert.doesNotMatch(status(t), /72/); assert.match(status(t), /不可用/);
});

test('hiding while start is pending releases a late grant without reading', async () => {
  let releaseStart, signal;
  const t = setup(url => Promise.resolve(ok({})), (url, options) => {
    signal = options.signal;
    return new Promise(resolve => { releaseStart = resolve; });
  });
  const starting = t.ui.toggleMindlink(); await t.flush();
  t.document.hidden = true; t.ui.mindlinkVisibilityChanged();
  assert.equal(signal.aborted, true);
  t.document.hidden = false; t.ui.mindlinkVisibilityChanged();
  releaseStart({token: 'late-grant'}); await starting; await t.flush();
  assert.equal(t.calls.filter(c => c.url.endsWith('/state')).length, 0);
  assert.ok(t.calls.some(c => c.url.endsWith('/stop') && c.options.headers['X-MindLink-Token'] === 'late-grant'));
});

test('a stuck start is aborted and the button becomes available again', async () => {
  const t = setup(() => Promise.resolve(ok({})), (url, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new Error('timeout')));
  }));
  const starting = t.ui.toggleMindlink(); await t.flush();
  assert.equal(t.nodes['#mindlink-toggle'].disabled, true);
  await t.advance(2000); await starting;
  assert.match(status(t), /无法开启/);
  assert.equal(t.nodes['#mindlink-toggle'].disabled, false);
});
