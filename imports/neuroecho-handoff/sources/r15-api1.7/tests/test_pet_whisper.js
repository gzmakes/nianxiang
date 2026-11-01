const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('web/pet-whisper.js', 'utf8');
function load(fetch) {
  const ctx = {window:{}, fetch};
  vm.runInNewContext(source, ctx);
  return ctx.window.NianxiangPetWhisper;
}

test('pet utterances send no chat context and share one in-flight request', async () => {
  let finish, calls = 0;
  const pet = load((url, options) => {
    calls++;
    assert.equal(url, '/api/pet-whisper');
    assert.equal(options.method, 'POST');
    assert.equal(options.body, undefined);
    return new Promise(resolve => { finish = resolve; });
  });
  const first = pet.generate(), second = pet.generate();
  assert.equal(first, second);
  finish({ok:true, json:async () => ({available:true, text:'  今天也加油～  '})});
  assert.equal(await first, '今天也加油～');
  assert.equal(calls, 1);
});

test('failed or unavailable model returns null for the caller to fall back', async () => {
  assert.equal(await load(async () => ({ok:true, json:async () => ({available:false})})).generate(), null);
  assert.equal(await load(async () => {throw new Error('network')}).generate(), null);
  assert.equal(await load(async () => ({ok:false})).generate(), null);
});
