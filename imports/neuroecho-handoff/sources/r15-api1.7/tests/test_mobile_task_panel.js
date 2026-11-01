const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source=fs.readFileSync('web/m.js','utf8');
const start=source.indexOf('  function renderBookmark('),end=source.indexOf('\n  async function loadMobileTaskActions()',start);
assert.ok(start>=0&&end>start);
function setup(stored=null,kind='tasks') {
 const body={innerHTML:'',contains:()=>true},sheet={_xinjiEpoch:1,_xinjiKind:kind};
 const input={value:'',events:[],dispatchEvent(e){this.events.push(e.type)},focus(){this.focused=true}};
 const nodes={'#m-sheet-body':body,'#m-sheet':sheet,'#m-input':input,'#m-bm-save':{},'#m-bm-commit':{}};
 const state={session:{id:'one'}},events=[],window={XinjiComposerDraft:{save:()=>events.push('save')}};
 const context=vm.createContext({state,window,$:id=>nodes[id]||null,esc:s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
  localStorage:{getItem:()=>stored},keepMobileChatDraft:()=>events.push('keep'),closeSheet:()=>events.push('close'),
  saveBookmark:()=>events.push('bookmark-save'),commitBookmark:()=>events.push('bookmark-commit'),Event:class {constructor(type){this.type=type;}}});
 vm.runInContext(source.slice(start,end)+'\nthis.run=renderBookmark;',context);context.run();
 function click(attrs){const button={dataset:{},hasAttribute:k=>Object.hasOwn(attrs,k)};if(attrs['data-m-task-view'])button.dataset.mTaskView=attrs['data-m-task-view'];if(Object.hasOwn(attrs,'data-m-task-add'))button.dataset.mTaskAdd=attrs['data-m-task-add'];body.onclick({target:{closest:()=>button}});}
 return {body,sheet,input,state,events,nodes,context,click};
}
test('mobile tasks remove the legacy actions and show empty personal state',()=>{
 const e=setup();assert.match(e.body.innerHTML,/自动任务/);assert.match(e.body.innerHTML,/整理今日重点/);assert.doesNotMatch(e.body.innerHTML,/m-bm-note|新建消息草稿|m-task-actions/);
 e.click({'data-m-task-view':'mine'});assert.match(e.body.innerHTML,/这里空空如也，点击上方去创建一个任务吧！/);
});
test('mobile create keeps an unsent draft, persists it, closes the panel and focuses chat',()=>{
 const e=setup();e.input.value='已有草稿';e.click({'data-m-task-create':''});assert.equal(e.input.value,'已有草稿\n我要创建任务：');assert.deepEqual(e.input.events,['input']);assert.deepEqual(e.events,['save','keep','close']);assert.equal(e.input.focused,true);
});
test('mobile personal task reads the existing browser key and can add it without sending',()=>{
 const e=setup(JSON.stringify([{title:'我的计划',detail:'帮我拆解计划'}]));e.click({'data-m-task-view':'mine'});assert.match(e.body.innerHTML,/我的计划/);e.input.value='草稿';e.click({'data-m-task-add':'0'});assert.equal(e.input.value,'草稿\n帮我拆解计划');assert.ok(!e.events.includes('send'));
});
test('stale task buttons cannot alter the new conversation draft',()=>{
 const e=setup();e.state.session={id:'two'};e.input.value='新对话草稿';e.click({'data-m-task-create':''});assert.equal(e.input.value,'新对话草稿');assert.deepEqual(e.events,[]);
});
test('the independent insight bookmark route keeps a real editable save form',()=>{
 const e=setup(null,'bookmark');assert.match(e.body.innerHTML,/id="m-bm-note"/);assert.match(e.body.innerHTML,/id="m-bm-save"/);assert.doesNotMatch(e.body.innerHTML,/data-m-task-view/);e.nodes['#m-bm-save'].onclick();assert.deepEqual(e.events,['bookmark-save']);
});
