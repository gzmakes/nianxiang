'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');

test('settings polish keeps both auto-memory disclosures when mounting or re-rendering', () => {
  const source = fs.readFileSync('web/auto-memory-settings.js', 'utf8');
  const template = source.match(/host\.innerHTML = `([^`]+)`/)[1];
  const disclosures = [...template.matchAll(/<p class="note">([^<]+)<\/p>/g)].map(match => match[1]);
  assert.equal(disclosures.length, 2);
  const notes = disclosures.map(textContent => ({textContent, remove() { notes.splice(notes.indexOf(this), 1); }}));
  const label = {};
  const summary = {nextElementSibling: notes[0], insertAdjacentElement(_position, node) { this.nextElementSibling = node; }};
  const details = {querySelector(selector) {return selector.includes('summary') ? summary : label;}, querySelectorAll() {return notes;}};
  const tab = {};
  const callbacks = [];
  const document = {readyState:'complete', documentElement:{dataset:{}}, querySelector(selector) {
    if (selector === '#app #auto-memory-settings details') return details;
    if (selector === '#app #tab-design') return tab;
    return null;
  }};
  class MutationObserver {constructor(callback) {callbacks.push(callback);} observe() {}}
  vm.runInNewContext(fs.readFileSync('web/settings-polish.js', 'utf8'), {document, MutationObserver, window:{}});
  assert.equal(summary.nextElementSibling, label);
  callbacks[0]();
  assert.deepEqual(notes.map(note => note.textContent), disclosures);
  assert.match(notes[0].textContent, /可能随对话发送给当前模型服务/);
  assert.match(notes[1].textContent, /未确认的自动记录不会作为记忆用于回复/);
});
