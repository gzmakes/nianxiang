const test = require('node:test');
const assert = require('node:assert/strict');
const {createController} = require('../web/paired-devices.js');
const token = 'echo_pair_' + 'A'.repeat(43); // disposable synthetic credential, not a real service token
const device = (extra = {}) => ({id:'d_12345678', label:'合成 iPhone', created_at:'2026-10-30T00:00:00Z', expires_at:'2026-11-06T00:00:00Z', revoked_at:null, ...extra});
const list = (extra = {}) => ({service_instance_id:'service-1', conversation_id:'s1', devices:[], ...extra});
const issued = (extra = {}) => ({...list(), scope:'personal_core', local_actions_allowed:false, device:device(), token, ...extra});
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => {resolve=a;reject=b;}); return {promise, resolve, reject}; };
function setup(handler) {
  const requests=[], changes=[], timers=new Map(); let n=0, sid='s1', visible=true;
  const api = async (path, opts) => { requests.push({path,opts}); return handler ? handler(path,opts) : list(); };
  const controller = createController({api, getSessionId:() => sid, visible:() => visible,
    onChange:state => changes.push(state), timers:{setTimeout(fn) { const id=++n;timers.set(id,fn);return id; }, clearTimeout:id => timers.delete(id)}});
  return {controller, requests, changes, timers, setSid:value => sid=value, setVisible:value => visible=value};
}

test('reading owner devices never issues a credential or copies hidden server fields', async () => {
  const e=setup(() => list({devices:[{...device(),token,token_hash:'hidden',private:'ignored'}],token}));
  assert.equal(e.requests.length,0); await e.controller.load();
  assert.equal(e.requests.length,1); assert.equal(e.requests[0].path,'/api/paired-devices');
  const state=JSON.stringify(e.controller.snapshot());
  assert.ok(!state.includes(token));assert.ok(!state.includes('hidden'));assert.equal(e.controller.secretForView(),'');
});
test('preparing and cancelling the scope card does not write anything', async () => {
  const e=setup();await e.controller.load();assert.equal(e.controller.prepare('合成 iPhone'),true);
  assert.equal(e.requests.length,1);assert.equal(e.controller.snapshot().review.kind,'issue');
  e.controller.cancelReview();assert.equal(await e.controller.issue(),false);assert.equal(e.requests.length,1);
});
test('a blank name, unverified service or changed conversation cannot issue', async () => {
  const e=setup();assert.equal(e.controller.prepare('合成 iPhone'),false);await e.controller.load();
  for(const name of ['', '  ', 'x'.repeat(81)])assert.equal(e.controller.prepare(name),false);
  e.setSid('s2');assert.equal(e.controller.prepare('合成 iPhone'),false);assert.equal(e.requests.length,1);
});
test('only explicit scope confirmation sends the seven-day owner request', async () => {
  const e=setup((path,opts) => opts.method==='POST' ? issued() : list());await e.controller.load();
  assert.equal(e.controller.prepare(' 合成 iPhone '),true);assert.equal(await e.controller.issue(),true);
  assert.deepEqual(JSON.parse(e.requests[1].opts.body),{label:'合成 iPhone',expires_in_seconds:604800,confirmed:true});
  assert.equal(e.controller.secretForView(),token);assert.ok(!JSON.stringify(e.changes).includes(token));
  assert.equal(e.controller.snapshot().devices.length,1);
});
test('hiding clears the one-time secret; returning never restores it', async () => {
  const e=setup((p,o) => o.method==='POST' ? issued() : list());await e.controller.load();e.controller.prepare('合成 iPhone');await e.controller.issue();
  e.setVisible(false);e.controller.suspend();assert.equal(e.controller.secretForView(),'');
  e.setVisible(true);assert.equal(e.controller.secretForView(),'');assert.equal(e.controller.snapshot().hasSecret,false);
});
test('a late create response after leaving the page cannot reveal its token', async () => {
  const pending=deferred(),e=setup((p,o) => o.method==='POST' ? pending.promise : list());
  await e.controller.load();e.controller.prepare('合成 iPhone');const waiting=e.controller.issue();
  e.setVisible(false);e.controller.suspend();pending.resolve(issued());assert.equal(await waiting,false);
  e.setVisible(true);assert.equal(e.controller.secretForView(),'');assert.equal(e.controller.snapshot().unknown,true);
});
test('lost create receipt stays unknown and is never automatically retried', async () => {
  const pending=deferred(),e=setup((p,o) => o.method==='POST' ? pending.promise : list());
  await e.controller.load();e.controller.prepare('合成 iPhone');const waiting=e.controller.issue();
  Array.from(e.timers.values())[0]();assert.equal(await waiting,false);
  assert.equal(e.controller.snapshot().unknown,true);assert.equal(e.controller.prepare('其他'),false);
  assert.equal(e.requests.filter(item => item.opts.method==='POST').length,1);
  pending.resolve(issued());await Promise.resolve();assert.equal(e.controller.secretForView(),'');
  await e.controller.load();assert.equal(e.controller.snapshot().unknown,false);assert.equal(e.controller.prepare('其他'),true);
});
test('an old failure after suspend cannot damage a newer successful device list', async () => {
  const pending=deferred();let reads=0;
  const e=setup(() => ++reads===1 ? pending.promise : list({devices:[device()]}));
  const first=e.controller.load();e.controller.suspend();await e.controller.load();
  pending.reject(Error('old failure'));assert.equal(await first,false);
  assert.equal(e.controller.snapshot().loaded,true);assert.equal(e.controller.snapshot().devices.length,1);
});
test('wrong conversation or duplicate identities reject the list before granting controls', async () => {
  for(const response of [list({conversation_id:'other'}),list({devices:[device(),device()]})]) {
    const e=setup(() => response);assert.equal(await e.controller.load(),false);
    assert.equal(e.controller.snapshot().loaded,false);assert.equal(e.controller.prepare('我的手机'),false);
  }
});
test('changed service, wider scope and malformed secret receipts never reveal a credential', async () => {
  for(const response of [issued({service_instance_id:'replacement'}),issued({scope:'all_local'}),issued({local_actions_allowed:true}),issued({token:'short'})]) {
    const e=setup((p,o) => o.method==='POST' ? response : list());await e.controller.load();e.controller.prepare('合成 iPhone');
    assert.equal(await e.controller.issue(),false);assert.equal(e.controller.secretForView(),'');assert.equal(e.controller.snapshot().unknown,true);
  }
});
test('revocation requires its own confirmation and a receipt for exactly that device', async () => {
  const e=setup((p,o) => o.method==='POST' ? {service_instance_id:'service-1',device_id:'d_12345678',revoked:true,in_flight_may_have_committed:true} : list({devices:[device()]}));
  await e.controller.load();assert.equal(await e.controller.revoke(),false);assert.equal(e.requests.length,1);
  assert.equal(e.controller.prepareRevoke('d_12345678'),true);assert.equal(e.requests.length,1);
  assert.equal(await e.controller.revoke(),true);assert.match(e.requests[1].path,/d_12345678\/revoke$/);
  assert.ok(e.controller.snapshot().devices[0].revoked_at);assert.match(e.controller.snapshot().note,/不会自动回滚/);
});
test('failed or mismatched revocation cannot be reported as revoked', async () => {
  for(const receipt of [{service_instance_id:'service-1',device_id:'other',revoked:true,in_flight_may_have_committed:true},null]) {
    const e=setup((p,o) => {if(o.method==='POST'){if(!receipt)throw Error('network');return receipt;}return list({devices:[device()]});});
    await e.controller.load();e.controller.prepareRevoke('d_12345678');assert.equal(await e.controller.revoke(),false);
    assert.equal(e.controller.snapshot().devices[0].revoked_at,null);assert.equal(e.controller.snapshot().unknown,true);
    assert.match(e.controller.snapshot().note,/还没确认/);
  }
});
test('a context change during create cannot activate the old context credential', async () => {
  const pending=deferred(),e=setup((p,o) => o.method==='POST' ? pending.promise : list());
  await e.controller.load();e.controller.prepare('合成 iPhone');const waiting=e.controller.issue();
  e.setSid('s2');pending.resolve(issued());assert.equal(await waiting,false);assert.equal(e.controller.secretForView(),'');
});
test('disposing prevents late work and removes a live one-time credential', async () => {
  const e=setup((p,o) => o.method==='POST' ? issued() : list());await e.controller.load();e.controller.prepare('合成 iPhone');await e.controller.issue();
  e.controller.dispose();assert.equal(e.controller.secretForView(),'');assert.equal(await e.controller.load(),false);assert.equal(e.controller.prepare('其他'),false);
});
