const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync('web/device-connections.js', 'utf8');
function setup() {
  const sandbox = {window:{}};
  vm.runInNewContext(code, sandbox);
  return sandbox.window.XinjiDeviceConnections;
}
test('desktop and mobile expose four device entries without claiming a connection or reading data', () => {
  const mod = setup();
  for (const mobile of [false, true]) {
    const html = mod.html({mobile});
    for (const label of ['Rokid 眼镜','脑机接口','电子吧唧','智能手表','待连接 app 或热点链接']) assert.ok(html.includes(label));
    assert.equal((html.match(/data-device-connect=/g) || []).length, 4);
    assert.doesNotMatch(html, /已连接|✓/);
    assert.match(html, /待接入/);
    assert.equal((html.match(/待接入/g) || []).length, 2);
    assert.doesNotMatch(html, /class="status"/);
  }
});
test('a device is only opened after its explicit button click and unavailable devices say so', () => {
  const mod = setup(), calls = [];
  const buttons = ['rokid', 'mindlink', 'badge', 'watch', 'unknown'].map(id => ({dataset:{deviceConnect:id}}));
  const box = {querySelectorAll: () => buttons};
  mod.bind(box, {onMindLink: () => calls.push('mindlink'), onUnavailable: d => calls.push([d.id,d.message])});
  assert.equal(calls.length,0);
  buttons[0].onclick(); buttons[1].onclick(); buttons[2].onclick(); buttons[3].onclick(); buttons[4].onclick();
  assert.equal(calls.length,4);
  assert.equal(calls[1],'mindlink');
  assert.deepEqual(calls.filter(Array.isArray).map(x=>x[0]),['rokid','badge','watch']);
  assert.ok(calls.filter(Array.isArray).every(x=>/待接入/.test(x[1])));
});
test('known application icons use local resources, unknown names are safely escaped', () => {
  const mod = setup();
  for (const id of ['feishu','apple_calendar','apple_reminders']) {
    const html = mod.sourceIcon(id,'x');
    assert.match(html, /src="\/static\/connection-icons\//);
    assert.match(html, /alt="x"/); // Browser shows a text fallback if an icon cannot load.
    const path = html.match(/src="\/static\/([^"]+)"/)[1];
    assert.equal(fs.existsSync(`web/${path}`),true, path);
  }
  assert.equal(mod.sourceIcon('other','<img src=x>'), '&lt;img src=x&gt;');
});
