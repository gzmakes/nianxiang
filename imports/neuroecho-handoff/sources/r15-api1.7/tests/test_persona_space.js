const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('server message metadata wins over stale browser views while legacy messages retain their saved view', async () => {
  const saved = {current:'nianxiang:companion', views:{a:'nianxiang:companion', old:'whale:work'}};
  const storage = new Map([['xinji_session','session'], ['xinji_space_v1',JSON.stringify(saved)]]);
  const storageApi = {getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)};
  const serverMessage = {dataset:{messageId:'a',personaId:'whale',interactionMode:'work'},classList:{contains:()=>false}};
  const legacyMessage = {dataset:{messageId:'old'},classList:{contains:()=>false}};
  const messages = {querySelectorAll:()=>[serverMessage, legacyMessage],querySelector:()=>serverMessage,prepend(){}};
  const root = {dataset:{}};
  const workspace = {topics:{},setTopic(){}};
  let poll;
  const document = {readyState:'complete',documentElement:root,querySelector(selector){
    if(selector === '#app #messages, #m-app #m-messages') return messages;
    if(selector === '#app, #m-app') return {classList:{contains:()=>false}};
    return null;
  },querySelectorAll:()=>[],addEventListener(){},createElement(){return {hidden:false,textContent:''}}};
  const context = vm.createContext({document,window:{XinjiWorkspace:workspace},localStorage:storageApi,
    fetch:async()=>({ok:true,json:async()=>({session:{id:'session',persona_id:'nianxiang',interaction_mode:'companion'}})}),
    MutationObserver:class {observe(){} takeRecords(){}},setInterval:fn=>{poll=fn;return 1},clearInterval(){},Date,CustomEvent:class{}});
  vm.runInContext(fs.readFileSync('web/persona-switch.js','utf8'),context);
  await new Promise(resolve=>setImmediate(resolve));
  poll();
  assert.equal(workspace.topics.matches('a','小鲸鱼·工作',serverMessage),true);
  assert.equal(workspace.topics.matches('a','念响·陪伴',serverMessage),false);
  assert.equal(workspace.topics.matches('old','小鲸鱼·工作',legacyMessage),true);
  assert.equal(workspace.topics.matches('local-pending','念响·陪伴',{dataset:{}}),true);
  assert.equal(workspace.topics.matches('a','全部',serverMessage),true);
});
