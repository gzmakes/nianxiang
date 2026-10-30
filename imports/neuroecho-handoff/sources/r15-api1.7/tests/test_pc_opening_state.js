// Regression for first-visit UI versus a conversation already started from a source.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/app.js','utf8');
function clip(a,b){const i=source.indexOf(a),j=source.indexOf(b,i);assert.ok(i>=0&&j>i);return source.slice(i,j);}
function element(){const classes=new Set();return{innerHTML:'',textContent:'',scrollTop:0,scrollHeight:720,
 classList:{add:(...xs)=>xs.forEach(x=>classes.add(x)),remove:(...xs)=>xs.forEach(x=>classes.delete(x)),contains:x=>classes.has(x),toggle:(x,on)=>{const value=on??!classes.has(x);value?classes.add(x):classes.delete(x);return value;}},querySelectorAll:()=>[]};}
function setup({mode='empty',messages=[],bookmark=null}={}){
 const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
 const state={session:{id:'restored-session',mode},messages,bookmark},switched=[],scrolls=[];
 const context=vm.createContext({$,state,els:{messages:$('#messages')},localStorage:{getItem:key=>key==='xinji_last_seen_restored-session'?'2026-10-29T09:00:00+08:00':null},
  Date,switchTab:tab=>switched.push(tab),memoryProposal:{sync(){}},chatScroll:{render:(render,options)=>{render();scrolls.push(options);}},
  window:{XinjiVoice:{pruneClips(){}},XinjiActionCards:{chatDraft:()=>null}},esc:String,renderMessageText:String,sendMessage(){throw Error('rendering must not send a message');}});
 vm.runInContext(clip('  function showResumeBanner()', '  function showIntro()')+
  '\nlet renderedChatSession=null,renderedAssistantId=null;'+clip('  function renderMessages(', '  function memByKind(')+
  '\nthis.resume=showResumeBanner;this.render=renderMessages;',context);
 return{context,$,state,switched,scrolls};
}
test('an untouched empty chat hides a stale resume banner even when last_seen exists',()=>{
 const e=setup({messages:[{id:'intro',role:'assistant',text:'初始化介绍'}]});
 e.$('#resume-banner').classList.remove('is-hidden');e.context.resume();
 assert.equal(e.$('#resume-banner').classList.contains('is-hidden'),true);assert.equal(e.$('#resume-text').textContent,'');assert.equal(e.$('#messages').scrollTop,0);
});
test('a source greeting alone does not claim that the user has a conversation to resume',()=>{
 const e=setup({mode:'real',messages:[{id:'source-intro',role:'assistant',text:'已经整理好你选择的资料'}]});e.context.resume();
 assert.equal(e.$('#resume-banner').classList.contains('is-hidden'),true);assert.equal(e.$('#resume-text').textContent,'');
});
test('a saved bookmark can be resumed before any user message and opens its actual tab',()=>{
 const e=setup({bookmark:{id:'saved',note:'下次想继续说的事'}});e.context.resume();
 assert.equal(e.$('#resume-banner').classList.contains('is-hidden'),false);assert.match(e.$('#resume-text').textContent,/书签：下次想继续说的事/);assert.equal(e.$('#resume-bookmark').classList.contains('is-hidden'),false);
 e.$('#resume-bookmark').onclick();assert.deepEqual(e.switched,['bookmark']);assert.equal(e.$('#resume-banner').classList.contains('is-hidden'),true);
});
test('existing user history keeps the resume hint without inventing a bookmark',()=>{
 const e=setup({messages:[{id:'user',role:'user',text:'以前说过的话'}]});e.context.resume();
 assert.equal(e.$('#resume-banner').classList.contains('is-hidden'),false);assert.match(e.$('#resume-text').textContent,/接着往下说/);assert.equal(e.$('#resume-bookmark').classList.contains('is-hidden'),true);assert.equal(e.$('#messages').scrollTop,720);
});
test('an empty-mode introduction shows the chat welcome without duplicating its bootstrap greeting',()=>{
 const e=setup({messages:[{id:'bootstrap',role:'assistant',text:'自动生成的旧介绍'}]});e.context.render();
 assert.equal(e.$('#chat-empty').classList.contains('is-hidden'),false);assert.equal(e.$('#messages').innerHTML,'');
});
test('an assistant-only source conversation renders its greeting and releases the welcome layout',()=>{
 for(const mode of ['real','paste','sample']){
  const e=setup({mode,messages:[{id:'source-greeting',role:'assistant',text:'读完这份资料，我想先听听你的感受。',suggestions:['聊聊最近的压力']}]});e.context.render();
  assert.equal(e.$('#chat-empty').classList.contains('is-hidden'),true);assert.match(e.$('#messages').innerHTML,/读完这份资料，我想先听听你的感受/);assert.match(e.$('#messages').innerHTML,/聊聊最近的压力/);assert.equal(e.scrolls[0].forceBottom,true);
 }
});
test('the first user message replaces the empty welcome and remains visible with its reply',()=>{
 const e=setup();e.context.render();assert.equal(e.$('#chat-empty').classList.contains('is-hidden'),false);
 e.state.messages=[{id:'u',role:'user',text:'今天有点累'},{id:'a',role:'assistant',text:'我在，慢慢说。'}];e.context.render();
 assert.equal(e.$('#chat-empty').classList.contains('is-hidden'),true);assert.match(e.$('#messages').innerHTML,/今天有点累/);assert.match(e.$('#messages').innerHTML,/我在，慢慢说/);assert.equal(e.scrolls[1].newMessage,true);
});
