// Production UI gate: QA fakes remain in tests, never as selectable product/runtime data.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const pc=fs.readFileSync('web/app.js','utf8'),mobile=fs.readFileSync('web/m.js','utf8');
const pages=['web/index.html','web/m.html'].map(name=>fs.readFileSync(name,'utf8'));
function clip(source,a,b){const i=source.indexOf(a),j=source.indexOf(b,i);assert.ok(i>=0&&j>i);return source.slice(i,j);}
test('neither production page exposes sample, fault injection, credential downgrade or synthetic device controls',()=>{
 for(const html of pages){
  assert.doesNotMatch(html,/data-mode=["']sample|data-fault=|id=["'](?:fault-panel|auth-fix|m-auth-fix|device-toggle|device-toggle-label|device-status|device-note|quality-bar|quality-value|sim-button|display-ack|m-device-chip|m-dev-toggle|m-sim-button|scenario-grid)["']/);
  assert.doesNotMatch(html,/keychain-downgrade|合成流|模拟按钮|故障演练/);
 }
});
test('production scripts contain no demo boot, fault injection, credential downgrade or synthetic device transport',()=>{
 for(const script of [pc,mobile]){
  assert.doesNotMatch(script,/\/api\/device\/|\/api\/debug\/faults|\/api\/auth\/lark\/setup|keychain-downgrade|auth-fix|data-fault|data-mode/);
  assert.doesNotMatch(script,/startSession\(["']sample|has\(["']demo["']\)|has\(["']debug["']\)|function (?:renderDevice|toggleDevice|pollFrame|renderScenarios|connectorCard)\(/);
 }
});
test('the old mobile start entry resumes the canonical conversation even if passed a legacy sample mode',async()=>{
 let restored=0;const context=vm.createContext({restore:async()=>{restored++;return 'canonical';}});
 vm.runInContext(clip(mobile,'  async function startSession(', '  // ---------- onboarding wizard (mobile) ----------')+'\nthis.start=startSession;',context);
 assert.equal(await context.start('sample','obsolete input'),'canonical');assert.equal(restored,1);
});
test('a stale device sheet request is inert rather than reviving a hidden synthetic panel',()=>{
 const context=vm.createContext({});vm.runInContext(clip(mobile,'  function openSheet(', '  async function renderTodayMobile()')+'\nthis.open=openSheet;',context);assert.equal(context.open('device'),undefined);
});
test('real MindLink opt-in and truthful Rokid outline remain available without pretending hardware is connected',()=>{
 assert.match(pages[0],/id="mindlink-toggle"/);assert.match(pages[0],/MindLink.*专注度/);assert.match(pages[0],/不记录、不发送给模型，也不判断情绪/);assert.match(pc,/api\("\/api\/mindlink\/start"/);assert.match(pc,/X-MindLink-Token/);
 assert.match(pages[1],/id="m-rokid-outline"/);assert.match(pages[1],/当前不会连接眼镜，也不会请求设备权限/);
 for(const script of [pc,mobile])assert.match(script,/force: true/);
});
