const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

for (const file of ['web/app.js', 'web/m.js']) {
  test(`${file} derives assistant bubbles through the shared parser`, () => {
    const src = fs.readFileSync(file, 'utf8');
    assert.match(src, /XinjiResponseParser/);
    assert.match(src, /Array\.isArray\(message\.bubbles\)/);
    assert.match(src, /message\.bubbles\s*=\s*parsed\.messages/);
    const parser = src.indexOf('const parser = globalThis.XinjiResponseParser');
    const serverBubbles = src.indexOf('if (Array.isArray(message.bubbles)', parser);
    const parse = src.indexOf('const parsed = parser.parse', parser);
    assert.ok(serverBubbles >= 0 && serverBubbles < parse, 'server bubbles must win over client parsing');
  });
}
