const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

for (const mobile of [false, true]) {
  const surface = mobile ? 'H5' : 'Web';
  const source = fs.readFileSync(mobile ? 'web/m.js' : 'web/app.js', 'utf8');
  const name = mobile ? 'showConnectedMobileSource' : 'showConnectedSource';
  const start = source.indexOf(`  function ${name}(`);
  const end = source.indexOf('\n  }', start) + 4;
  const code = source.slice(start, end);
  function harness(sources) {
    const nodes = new Map(), actions = [];
    const $ = key => {
      if (!nodes.has(key)) nodes.set(key, {innerHTML:'', classList:{add() {}}});
      return nodes.get(key);
    };
    const ctx = {$, esc: value => String(value),
      connectedSources: () => sources, mobileSources: () => sources,
      closeSourceDialog: () => actions.push('close'), closeMobileWizard: () => actions.push('close'),
      revokeSelectedSource: id => actions.push(['revoke', id]),
      revokeMobileSelectedSource: id => actions.push(['revoke', id]),
      switchTab: id => actions.push(['manage', id]), openSheet: id => actions.push(['manage', id]),
      showWz: () => {}};
    vm.createContext(ctx);
    vm.runInContext(code + `\nthis.open = ${name};`, ctx);
    ctx.open('apple_calendar', {name:'Apple 日历'});
    return {nodes, actions, button: $(mobile ? '#m-connection-disconnect' : '#connection-disconnect'),
      head: $(mobile ? '#m-read-head' : '#read-head')};
  }
  test(`${surface}: one matching snapshot removes only its own source after the existing confirmation flow`, () => {
    const t = harness([{id:'calendar-one', connector_id:'apple_calendar'}, {id:'reminder-one', connector_id:'apple_reminders'}]);
    assert.match(t.head.innerHTML, /取消授权/);
    assert.match(t.head.innerHTML, /系统权限请在系统设置中管理/);
    t.button.onclick();
    assert.deepEqual(t.actions, ['close', ['revoke', 'calendar-one']]);
  });
  test(`${surface}: multiple snapshots require choosing which one to manage`, () => {
    const t = harness([{id:'calendar-one', connector_id:'apple_calendar'}, {id:'calendar-two', connector_id:'apple_calendar'}]);
    assert.match(t.head.innerHTML, /管理连接/);
    t.button.onclick();
    assert.deepEqual(t.actions, ['close', ['manage', mobile ? 'more' : 'data']]);
  });
  test(`${surface}: a legacy snapshot with no id never calls the remove-all operation`, () => {
    const t = harness([{id:null, connector_id:'apple_calendar'}]);
    assert.match(t.head.innerHTML, /管理连接/);
    t.button.onclick();
    assert.deepEqual(t.actions, ['close', ['manage', mobile ? 'more' : 'data']]);
  });
}
