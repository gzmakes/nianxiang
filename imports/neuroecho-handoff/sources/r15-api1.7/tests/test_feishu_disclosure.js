// The disclosure is shown before confirmation at each supported Feishu entry.
const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const pc=fs.readFileSync('web/app.js','utf8'), mobile=fs.readFileSync('web/m.js','utf8');
function clip(src,a,b){const x=src.indexOf(a),y=src.indexOf(b,x);assert.ok(x>=0&&y>x);return src.slice(x,y)}
function disclosure(src){const m=src.match(/const feishuDisclosure = ("[^\n]+?");/);assert.ok(m);return vm.runInNewContext(m[1]);}
test('desktop and mobile explain later model calls and no-match behavior consistently',()=>{
 const text=disclosure(pc); assert.equal(text,disclosure(mobile));
 for (const part of ['最多 12000 字','之后每次聊天','每份来源最多 3 段；当前对话的所有来源合计最多 8 段、3200 字（含来源标注）','发送给当前模型服务','无匹配时不发送检索片段','摘要等其他上下文仍可能发送','移除当前对话来源']) assert.ok(text.includes(part),part);
});
test('all three desktop preview paths show disclosure before confirmation',()=>{
 for (const [begin,end,confirmation] of [
  ['  function renderRealLark()', '  function renderGmailReal()', 'id="wz-lark-start"'],
  ['  function renderFeishuPicker()', '  function renderNotionReal()', 'id="wz-feishu-start"']]) {
   const part=clip(pc,begin,end); assert.ok(part.indexOf('${feishuDisclosure}')>=0); assert.ok(part.indexOf('${feishuDisclosure}')<part.indexOf(confirmation));
 }
 const older=clip(pc,'  async function previewLark()', '  async function startLark()');
 assert.ok(older.includes('hint.textContent = feishuDisclosure'));
});
test('mobile preview shows disclosure before confirmation',()=>{
 const part=clip(mobile,'  function openMobileFeishu()', '  async function startMobileReal(');
 assert.ok(part.indexOf('${feishuDisclosure}')>=0); assert.ok(part.indexOf('${feishuDisclosure}')<part.indexOf('id="m-feishu-start"'));
});
