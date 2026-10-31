const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const source = fs.readFileSync(require('node:path').join(__dirname, '..', 'web', 'persona-switch.js'), 'utf8');

test('persona switch keeps persona and interaction mode in the shared space', () => {
  assert.match(source, /const MODES/);
  assert.match(source, /data-space-mode|space-modes/);
  assert.match(source, /\/mode/);
  assert.match(source, /current\.split\('\:'\)/);
  assert.match(source, /write\(\{ current, views \}\)/);
  assert.match(source, /api\/session\/\$\{encodeURIComponent\(sid\)\}\/persona/);
});
