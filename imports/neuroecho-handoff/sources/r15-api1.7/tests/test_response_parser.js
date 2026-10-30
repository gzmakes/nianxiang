const test = require('node:test');
const assert = require('node:assert/strict');
const { parse } = require('../web/response-parser.js');

test('parses a valid response envelope into ordered messages', () => {
  assert.deepEqual(parse(JSON.stringify({messages:['先接住你。','我们再一起想办法。'], emotion:'warm', format:'plain'})), {messages:['先接住你。','我们再一起想办法。'], emotion:'warm', format:'plain'});
});
test('parses fenced or annotated JSON without exposing the envelope', () => {
  const value = '模型回复：\n```json\n{"messages":["好呀，发来我瞅瞅"],"emotion":"playful"}\n```';
  assert.deepEqual(parse(value), {messages:['好呀，发来我瞅瞅'], emotion:'playful', format:'plain'});
});
test('falls back to readable plain text for invalid, empty, or missing envelopes', () => {
  assert.deepEqual(parse('今天有点累\n但我还想聊聊'), {messages:['今天有点累\n但我还想聊聊'], emotion:null, format:'plain'});
  assert.deepEqual(parse('{"messages":[]}'), {messages:['{"messages":[]}'], emotion:null, format:'plain'});
  assert.deepEqual(parse('{"emotion":"playful"}'), {messages:['{"emotion":"playful"}'], emotion:null, format:'plain'});
  assert.deepEqual(parse('{"messages":[}'), {messages:['{"messages":[}'], emotion:null, format:'plain'});
});
test('keeps markdown and code blocks together', () => {
  const markdown = '## 先看这里\n\n```js\nconst ok = true;\n```\n\n| 项目 | 状态 |\n| --- | --- |';
  assert.deepEqual(parse(markdown), {messages:[markdown], emotion:null, format:'markdown'});
  assert.deepEqual(parse({messages:[markdown], format:'markdown'}), {messages:[markdown], emotion:null, format:'markdown'});
});
test('rejects non-string message entries and unknown metadata safely', () => {
  const value = JSON.stringify({messages:['第一条', 2], emotion:'secret', format:'xml'});
  assert.deepEqual(parse(value), {messages:[value], emotion:null, format:'plain'});
});
