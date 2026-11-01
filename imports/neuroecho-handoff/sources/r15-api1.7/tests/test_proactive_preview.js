const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync('web/proactive-preview.js','utf8');
function setup() {
  const element = () => ({hidden:false,textContent:'',addEventListener(type, fn){if (type==='click') this.click=fn;}});
  const close=element(), start=element(), pause=element(), end=element(), dismiss=element(), status=element(), title=element(), message=element();
  const children={'.preview-card-close':close,'[data-guide-start]':start,'[data-guide-pause]':pause,'[data-guide-end]':end,'[data-guide-dismiss]':dismiss,'[data-guide-status]':status,'[data-reminder-title]':title,'[data-reminder-message]':message};
  const card={hidden:true, innerHTML:'', replaceChildren(){this.innerHTML='';}, querySelector(s){return children[s];}};
  const root={hidden:true,dataset:{},querySelector(s){return s==='[data-preview-card]'?card:null;}};
  const state={guiding:false,guidePaused:false,blocked:false,error:''};
  const sound={getState:()=>state,startGuide(){state.guiding=true;state.guidePaused=false;},pauseGuide(){state.guidePaused=true;},stopGuide(){state.guiding=false;}};
  const window={NianxiangSound:sound,addEventListener(type,fn){if(type==='nianxiang-sound-change')this.sync=fn;}};
  vm.runInNewContext(code,{window,document:{readyState:'complete',querySelectorAll(){return [];}}});
  const controller=window.XinjiProactivePreview.mount(root);
  return {controller,root,card,start,pause,end,dismiss,close,status,title,message,state,window};
}
const reminder={title:'一起放松一下？',message:'如果想休息，可以慢慢呼吸一会儿。',allowBreathing:true};
test('no reminder is shown until a caller supplies actual nonempty text',()=>{
  const x=setup();assert.equal(x.root.hidden,true);assert.equal(x.card.hidden,true);
  assert.equal(x.controller.show({}),false);assert.equal(x.root.hidden,true);
  assert.equal(x.controller.show(reminder),true);assert.equal(x.root.hidden,false);assert.equal(x.card.hidden,false);
  assert.equal(x.title.textContent,reminder.title);assert.equal(x.message.textContent,reminder.message);
  assert.doesNotMatch(x.card.innerHTML,/样式预览|示例内容|普通对话选项/);
});
test('breathing starts, pauses, resumes, ends, and closing ends owned guide',()=>{
  const x=setup();x.controller.show(reminder);x.start.click();assert.equal(x.state.guiding,true);assert.equal(x.pause.hidden,false);x.pause.click();assert.equal(x.state.guidePaused,true);assert.equal(x.start.textContent,'继续呼吸');x.start.click();assert.equal(x.state.guidePaused,false);x.end.click();assert.equal(x.state.guiding,false);x.start.click();x.close.click();assert.equal(x.state.guiding,false);assert.equal(x.card.hidden,true);assert.equal(x.root.hidden,true);
});
test('blocked and failed audio states are communicated',()=>{
  const x=setup();x.controller.show(reminder);x.start.click();x.state.blocked=true;x.window.sync();assert.match(x.status.textContent,/声音暂时无法播放/);x.state.error='暂时无法播放';x.window.sync();assert.equal(x.status.textContent,'暂时无法播放');
});
test('breathing requires an explicit action and text is set as text',()=>{
  const x=setup();x.controller.show({title:'<img src=x>',message:'<b>文字</b>'});assert.equal(x.start.hidden,true);x.window.sync();assert.equal(x.start.hidden,true);assert.equal(x.title.textContent,'<img src=x>');assert.equal(x.message.textContent,'<b>文字</b>');
});
test('desktop and mobile have no fixed proactive trigger and the card starts hidden',()=>{
  for(const f of ['web/index.html','web/m.html']) {const html=fs.readFileSync(f,'utf8');assert.doesNotMatch(html,/data-preview-kind=/);assert.match(html,/<section class="proactive-preview"[^>]* hidden>/);assert.match(html,/proactive-preview\.js/);}
});
