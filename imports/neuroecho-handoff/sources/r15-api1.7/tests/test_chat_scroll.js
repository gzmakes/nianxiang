// Isolated behavior tests for the shared scroll controller.
const test = require('node:test');
const assert = require('node:assert/strict');
const {createChatScroll} = require('../web/chat-scroll.js');

function fixture() {
  const hidden = new Set(['is-hidden']);
  const listeners = {};
  const view = {scrollHeight:1000,clientHeight:300,scrollTop:700,
    addEventListener:(event,fn)=>{listeners[event]=fn}};
  const button = {classList:{add:s=>hidden.add(s),remove:s=>hidden.delete(s),contains:s=>hidden.has(s)},
    addEventListener:(event,fn)=>{listeners['button:'+event]=fn}};
  return {view, button, listeners, controller:createChatScroll(view,button)};
}

test('new reply follows only while reader is near bottom',()=>{
  const {view,button,controller}=fixture();
  controller.render(()=>{view.scrollHeight=1200},{newMessage:true});
  assert.equal(view.scrollTop,1200);
  assert.equal(button.classList.contains('is-hidden'),true);
});

test('new reply preserves reader position and clicking notice jumps to latest',()=>{
  const {view,button,listeners,controller}=fixture();view.scrollTop=100;
  controller.render(()=>{view.scrollHeight=1200},{newMessage:true});
  assert.equal(view.scrollTop,100);
  assert.equal(button.classList.contains('is-hidden'),false);
  listeners['button:click']();
  assert.equal(view.scrollTop,1200);
  assert.equal(button.classList.contains('is-hidden'),true);
});

test('non-message updates do not create new-message notices',()=>{
  const {view,button,controller}=fixture();view.scrollTop=100;
  controller.render(()=>{view.scrollHeight=1050});
  assert.equal(view.scrollTop,100);
  assert.equal(button.classList.contains('is-hidden'),true);
});

test('sending follows and manual scrolling to bottom clears notice',()=>{
  const {view,button,listeners,controller}=fixture();view.scrollTop=100;
  controller.render(()=>{view.scrollHeight=1200},{newMessage:true});
  view.scrollTop=900;listeners.scroll();
  assert.equal(button.classList.contains('is-hidden'),true);
  view.scrollTop=100;
  controller.render(()=>{view.scrollHeight=1400},{forceBottom:true});
  assert.equal(view.scrollTop,1400);
});
