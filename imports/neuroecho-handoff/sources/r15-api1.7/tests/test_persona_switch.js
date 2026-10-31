const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const source = fs.readFileSync(require('node:path').join(__dirname, '..', 'web', 'persona-switch.js'), 'utf8');

test('persona switch has one persona dimension and keeps topic filtering separate', () => {
  assert.doesNotMatch(source, /const MODES/);
  assert.doesNotMatch(source, /data-space-mode|space-modes/);
  assert.doesNotMatch(source, /\/mode/);
  assert.match(source, /value\.split\(':', 1\)/);
  assert.match(source, /write\(\{ \.\.\.saved, current, views \}\)/);
  assert.match(source, /api\/session\/\$\{encodeURIComponent\(sid\)\}\/persona/);
});
