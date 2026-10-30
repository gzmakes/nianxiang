const assert = require('node:assert/strict');
const meme = require('../web/meme.js');
const items = [{id:'builtin/happy.svg', label:'开心', tags:['happy'], url:'/static/stickers/happy.svg'}];
const both = meme.render('好呀 [表情: builtin/happy.svg] <script>', items);
assert.match(both, /好呀/); assert.match(both, /<img/); assert.match(both, /&lt;script&gt;/);
assert.equal(meme.render('未知 [表情: missing]', items), '未知 [表情: missing]');
assert.doesNotMatch(meme.render('[表情: x]', [{id:'x',url:'https://bad.invalid/a'}]), /<img/);
console.log('meme renderer: text, known sticker, unknown and unsafe url verified');
