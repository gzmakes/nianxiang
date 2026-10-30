// Synthetic content only: verification of the exact preview boundary.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function helper(source) {
  const start = source.indexOf('  function feishuPreviewMarkup(');
  const end = source.indexOf('\n  function readableFeishuUrl(', start);
  assert.ok(start >= 0 && end > start);
  return vm.runInNewContext(source.slice(start, end) + '\nfeishuPreviewMarkup', {
    esc: (s = '') => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]))
  });
}

for (const file of ['web/app.js', 'web/m.js']) {
  const source = fs.readFileSync(file, 'utf8');
  const render = helper(source);
  test(`${file}: complete, bounded preview is visible, escaped and keyboard scrollable`, () => {
    const text = '文'.repeat(11986) + '😀<结尾>&';
    const length = [...text].length;
    const markup = render({preview:text, preview_id:'test', length, extracted_length:length+8, truncated:true});
    assert.ok(markup.includes('&lt;结尾&gt;&amp;'));
    assert.ok(markup.includes('其余内容不会接入'));
    assert.ok(markup.includes('tabindex="0"') && markup.includes('role="region"'));
    assert.ok(!markup.includes('<结尾>'));
  });
  test(`${file}: incomplete or old server preview never offers confirmation`, () => {
    for (const data of [
      {preview:'前半',preview_id:'test',length:3,extracted_length:3,truncated:false},
      {preview:'内容',preview_id:'test',length:2},
      {preview:'内容',preview_id:'test',length:2,extracted_length:3,truncated:false},
      {preview:'内容',preview_id:'',length:2,extracted_length:2,truncated:false}
    ]) assert.throws(() => render(data), /预览不完整/);
    assert.ok(render({preview:'内容',preview_id:'test',length:2,extracted_length:2,truncated:false}).includes('全部 2 字'));
  });
}

test('each desktop and H5 path renders the validated complete snapshot', () => {
  const desktop = fs.readFileSync('web/app.js','utf8');
  const mobile = fs.readFileSync('web/m.js','utf8');
  assert.equal((desktop.match(/feishuPreviewMarkup\([dp]\)/g) || []).length, 3);
  assert.ok(mobile.includes('feishuPreviewMarkup(pv)'));
  assert.ok(!desktop.includes('(p.preview || "").slice(0, 160)'));
  assert.ok(!mobile.includes('(pv.preview || "").slice(0, 160)'));
});

test('desktop ignores an older preview and hides the previous confirmation on a new read', async () => {
  const source = fs.readFileSync('web/app.js', 'utf8');
  const start = source.indexOf('  function renderRealLark()');
  const end = source.indexOf('  function renderGmailReal()', start);
  const nodes = new Map();
  function $(key) {
    if (!nodes.has(key)) {
      const classes = new Set(['is-hidden']);
      nodes.set(key, {value:'', innerHTML:'', textContent:'', classList:{add:x=>classes.add(x), remove:x=>classes.delete(x), contains:x=>classes.has(x)}, querySelector:()=>null, insertAdjacentHTML:()=>{}});
    }
    return nodes.get(key);
  }
  const pending = [];
  const api = () => new Promise(resolve => pending.push(resolve));
  const context = {$, api, esc:String, feishuPreviewMarkup:helper(source), feishuDisclosure:'范围', state:{session:{id:'test'}}, confirmFeishuPreview:()=>{}};
  vm.createContext(context);
  vm.runInContext(source.slice(start,end) + '\nthis.renderRealLark = renderRealLark;', context);
  context.renderRealLark();
  const input = $('#wz-lark-url'), box = $('#wz-lark-result');
  input.value = 'https://example.test/docx/first';
  const first = $('#wz-lark-preview').onclick();
  input.value = 'https://example.test/docx/second';
  const second = $('#wz-lark-preview').onclick();
  assert.equal(box.classList.contains('is-hidden'), true);
  pending[1]({ok:true,title:'第二篇',preview:'乙',preview_id:'second',length:1,extracted_length:1,truncated:false});
  await second;
  pending[0]({ok:true,title:'第一篇',preview:'甲',preview_id:'first',length:1,extracted_length:1,truncated:false});
  await first;
  assert.ok(box.innerHTML.includes('第二篇'));
  assert.ok(!box.innerHTML.includes('第一篇'));
  const third = $('#wz-lark-preview').onclick();
  assert.equal(box.classList.contains('is-hidden'), true);
  pending[2]({ok:true,title:'旧服务',preview:'片段',preview_id:'old',length:100});
  await third;
  assert.equal(box.classList.contains('is-hidden'), true);
  assert.match($('#wz-lark-hint').textContent, /预览不完整/);
});
