const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('web/companion-choices.js', 'utf8');
function setup(initial = '') {
  const context = {window:{}, Event:class {constructor(type, options){this.type=type;this.bubbles=options.bubbles;}}};
  vm.runInNewContext(source, context);
  const input = {value:initial, events:[], dispatchEvent(e){this.events.push(e.type)}, focus(){this.focused=true}, setSelectionRange(a,b){this.selection=[a,b]}};
  const buttons=['listen','reflect','auto'].map(choice => ({dataset:{responseChoice:choice}, addEventListener(_event,cb){this.click=cb}}));
  context.window.XinjiCompanionChoices.bind({querySelectorAll:()=>buttons}, input);
  return {input, buttons, choices:context.window.XinjiCompanionChoices};
}
test('choosing a response style keeps a pre-existing draft and never sends it',()=>{
 const {input,buttons}=setup('这周的事情有点多');buttons[0].click();
 assert.equal(input.value,'先听我说，这周的事情有点多');assert.equal(input.focused,true);assert.deepEqual(input.events,['input']);
});
test('switching style replaces only the shortcut prefix, preserving what the user typed',()=>{
 const {input,buttons}=setup('我今天有点累');buttons[0].click();buttons[1].click();
 assert.equal(input.value,'帮我梳理一下，我今天有点累');buttons[1].click();assert.equal(input.value,'帮我梳理一下，我今天有点累');
});
test('natural chat is available without dropping the draft',()=>{
 const {input,buttons}=setup('我想继续说');buttons[0].click();buttons[2].click();assert.equal(input.value,'恢复自然聊天，我想继续说');
});
test('a user-edited prefix is never discarded when changing the selection',()=>{
 const {input,buttons}=setup('这件事');buttons[0].click();input.value='先听我完整讲完，这件事';buttons[1].click();
 assert.equal(input.value,'帮我梳理一下，先听我完整讲完，这件事');
});
test('both app pages load shared draft-only controls before their app script',()=>{
 for(const [file,app] of [['web/index.html','/static/app.js'],['web/m.html','/static/m.js']]){
  const html=fs.readFileSync(file,'utf8');assert.match(html,/data-response-choice="listen"/);assert.match(html,/data-response-choice="reflect"/);assert.match(html,/data-response-choice="auto"/);
  assert.match(html,/加入草稿，发送后生效/);assert.ok(html.indexOf('/static/companion-choices.js')<html.indexOf(app));
 }
});
