const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function delivery(api) {
  const timers = new Map(), played = [], soundDetails = []; let timerId = 0;
  const win = {NianxiangSound: {play: (name, detail) => { played.push(name); soundDetails.push(detail); }}};
  vm.runInNewContext(fs.readFileSync('web/chat-delivery.js', 'utf8'), {
    window: win, setTimeout: fn => { timers.set(++timerId, fn); return timerId; }, clearTimeout: id => timers.delete(id)
  });
  const state = {session: {id: 's'}, messages: [{id: 'm', role: 'assistant', delivery_pending: true}]};
  const instance = win.XinjiChatDelivery.create({state, api, render() {}, busy: () => false});
  return {state, instance, timers, played, soundDetails};
}
test('a delayed reply sounds once when it completes', async () => {
  const env = delivery(async () => ({messages: [{id: 'm', role: 'assistant', delivery_pending: false}]}));
  env.instance.schedule(); await [...env.timers.values()][0]();
  assert.deepEqual(env.played, ['receive']); assert.equal(env.soundDetails[0].messageId, 'm');
  env.instance.schedule(); assert.deepEqual(env.played, ['receive']);
});
test('a user-stopped reply does not sound as completed', async () => {
  const env = delivery(async (path, options) => path === '/api/capabilities'
    ? {features: {chat_delivery_targeted_stop: true}}
    : options?.method === 'POST' ? {stopped: true, message_id: 'm'}
    : {messages: [{id: 'm', role: 'assistant', delivery_pending: false}]});
  await env.instance.stop(); assert.deepEqual(env.played, []);
});
test('speech and generated clips report active and inactive transitions', async () => {
  const activity = [], spoken = [], events = {};
  const doc = {hidden: false, addEventListener: (type, fn) => { events[type] = fn; }, createElement() {
    return {paused: true, style: {}, pause() { this.paused = true; }, load() {}, setAttribute() {}, removeAttribute() {}};
  }};
  const win = {document: doc, NianxiangSound: {setVoiceActive: value => activity.push(value)},
    addEventListener() {}, setTimeout() { return 1; }, clearTimeout() {},
    speechSynthesis: {getVoices: () => [{lang: 'zh-CN', localService: true}], speak: utterance => spoken.push(utterance), cancel() {}},
    SpeechSynthesisUtterance: function (text) { this.text = text; },
    fetch: async () => ({ok: true, blob: async () => ({size: 1}), headers: {get: () => 'audio/wav'}}),
    URL: {createObjectURL: () => 'blob:test', revokeObjectURL() {}}};
  vm.runInNewContext(fs.readFileSync('web/voice-reply.js', 'utf8'), {window: win});
  const voice = win.XinjiVoice, button = {setAttribute() {}}, message = {id: 'a', role: 'assistant', text: '你好'};
  voice.pruneClips('s', [message]); voice.playMessage('a', '你好', button, 's'); spoken[0].onstart();
  assert.equal(activity.at(-1), true); spoken[0].onend(); assert.equal(activity.at(-1), false);
  await voice.configure({api: async () => ({features: {voice_clip_from_assistant_message: true}})});
  let player; await voice.makeClip({sessionId: 's', id: 'a', text: '你好', button, container: {replaceChildren(node) { player = node; }}, isCurrent: () => true});
  player.paused = false; player.onplay(); assert.equal(activity.at(-1), true);
  player.paused = true; player.onpause(); assert.equal(activity.at(-1), false);
});

function reminderHarness({hidden = false, mode = 'active'} = {}) {
  const played = [], created = [], stored = new Map();
  const item = {id: 'f', session_id: 's', due_at: new Date(Date.now() - 1000).toISOString(),
    contact_expires_at: new Date(Date.now() + 60000).toISOString(), boundary_revision: 0, content: '提醒'};
  const makeNode = () => ({children: [], setAttribute() {}, append(...nodes) { this.children.push(...nodes); }, remove() {}});
  const doc = {hidden, body: {append(node) { created.push(node); }}, createElement: makeNode, addEventListener() {}, removeEventListener() {}};
  const win = {NianxiangSound: {play: name => played.push(name)}, addEventListener() {}, removeEventListener() {},
    XinjiContactContract: {supported: () => true, validBoundary: () => true, eligible: () => true,
      identity: () => 'one-occurrence', claimMatches: () => true, recheckMatches: () => true}};
  function Notification() { this.close = () => {}; } Notification.permission = 'granted';
  const context = {window: win, document: doc, Notification, localStorage: {getItem: key => stored.get(key), setItem: (key, value) => stored.set(key, value)},
    setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {}, Date, JSON, Set, Number, encodeURIComponent}; context.globalThis = context;
  vm.runInNewContext(fs.readFileSync('web/proactive-contact.js', 'utf8'), context);
  const api = async path => {
    if (path === '/api/capabilities') return {};
    if (path.startsWith('/api/companion-boundary?')) return {mode, revision: 0};
    if (path.startsWith('/api/followup-notification-settings?')) return {enabled: true, revision: 0};
    if (path.startsWith('/api/followups?')) return {followups: [item]};
    if (path.endsWith('/claim')) return {claim_id: 'claim'};
    if (path.endsWith('/recheck')) return {};
    if (path.endsWith('/finish')) return {};
    throw Error(path);
  };
  return {widget: win.XinjiProactiveContact.create({api, getSessionId: () => 's'}), played, created};
}
test('an eligible foreground reminder sounds once and remains quiet after dismissal and refresh', async () => {
  const env = reminderHarness(); await new Promise(setImmediate);
  assert.equal(env.created.length, 1); assert.deepEqual(env.played, ['notify']);
  env.created[0].children[3].onclick(); await env.widget.refresh();
  assert.deepEqual(env.played, ['notify']); env.widget.stop();
});
test('paused boundaries and hidden system notifications never play in-app reminder sound', async () => {
  for (const options of [{mode: 'paused'}, {hidden: true}]) {
    const env = reminderHarness(options); await new Promise(setImmediate);
    assert.deepEqual(env.played, []); env.widget.stop();
  }
});

function mobileDispatchHarness(result) {
  const source = fs.readFileSync('web/m.js', 'utf8');
  const start = source.indexOf('  async function dispatchSend() {'), end = source.indexOf('  // ---------- boot ----------', start);
  assert.ok(start >= 0 && end > start);
  const events = [], soundDetails = [], node = {value: '', textContent: '', classList: {add() {}, remove() {}}};
  const state = {session: {id: 's'}, messages: [{id: 'local', role: 'user', text: '你好'}], memories: []};
  const context = {state, mQueuedTurns: [{sessionId: 's', parts: [{id: 'local', text: '你好'}]}], mTurnQueue: [],
    mUncertainTurns: new Map(), mActiveTurn: null, mDisplayedTurns: new Map(), mChatBlocked: false, mChatStorageBlocked: false,
    mChatTransport: {send: async () => { if (result instanceof Error) throw result; return result; }},
    mChatLedger: {returnDraft() {}}, mPendingMessages: () => [], memoryProposal: {shouldRequest: () => false, offer() {}},
    renderAll: () => events.push('render'), renderMessages() {}, loadNextStep() {}, toast() {}, $: () => node,
    window: {NianxiangSound: {play: (name, detail) => { events.push(name); soundDetails.push(detail); }}, XinjiComposerDraft: {save() {}}},
    XinjiMobilePresence() {}, console};
  vm.runInNewContext(source.slice(start, end) + '\nthis.dispatchSend = dispatchSend;', context);
  return {run: () => context.dispatchSend(), events, soundDetails};
}
test('mobile immediate reply announces after the new voice controls are rendered', async () => {
  const env = mobileDispatchHarness({messages: [{id: 'u', role: 'user'}, {id: 'a', role: 'assistant', text: '你好'}], memories: []});
  await env.run(); assert.deepEqual(env.events, ['render', 'receive']); assert.equal(env.soundDetails[0].messageId, 'a');
});
test('mobile only sounds an error when the message is known not sent', async () => {
  const uncertain = mobileDispatchHarness(new Error('unconfirmed'));
  await uncertain.run(); assert.equal(uncertain.events.includes('gentleError'), false);
  const failure = Object.assign(new Error('not sent'), {notSent: true});
  const confirmed = mobileDispatchHarness(failure);
  await confirmed.run(); assert.equal(confirmed.events.filter(event => event === 'gentleError').length, 1);
});

test('receive suppression checks only the current reply and its autoplay preference', () => {
  const store = new Map([['xinji_soundscape_v1', JSON.stringify({effects: true})]]);
  const history = {dataset: {messageId: 'history'}, querySelector: () => ({hidden: false})};
  const currentClip = {hidden: true};
  const current = {dataset: {messageId: 'current'}, querySelector: () => currentClip};
  const document = {currentScript: {src: 'http://localhost/soundscape.js'}, readyState: 'loading', hidden: false,
    querySelector: () => null, querySelectorAll: () => [history, current], addEventListener() {}};
  const win = {}, plays = [];
  function Audio() { this.paused = true; this.pause = () => { this.paused = true; }; this.play = () => { this.paused = false; plays.push(this.src); return Promise.resolve(); }; }
  const localStorage = {getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, value)};
  vm.runInNewContext(fs.readFileSync('web/soundscape.js', 'utf8'), {window: win, document, Audio, URL, localStorage, setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {}, Date, Math, JSON});
  assert.equal(win.NianxiangSound.play('receive', {messageId: 'current'}), true);
  currentClip.hidden = false;
  assert.equal(win.NianxiangSound.play('receive', {messageId: 'current'}), false);
  store.set('xinji_voice_autoplay_v1', 'false');
  assert.equal(win.NianxiangSound.play('receive', {messageId: 'current'}), true);
  store.delete('xinji_voice_autoplay_v1');
  assert.equal(win.NianxiangSound.play('receive', {messageId: 'unknown'}), true);
  assert.equal(plays.length, 3);
});
