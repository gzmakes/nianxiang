const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

for (const mobile of [false, true]) {
  const name = mobile ? 'mobile' : 'desktop';
  function mount(supported = true) {
    const source = fs.readFileSync(mobile ? 'web/m.js' : 'web/app.js', 'utf8');
    const start = source.indexOf('  function setupVoice() {');
    const end = source.indexOf(mobile ? '\n  let mobilePetChatSession' : '\n  let petChatSession', start);
    const button = {classList:{add(){}, remove(){}}, textContent:''};
    const input = {value:'', focus(){ this.focused = true; }};
    const sent = [], notices = [];
    let instance;
    class Recognition {
      constructor(){ instance = this; }
      start(){ this.onstart(); }
      stop(){ this.onend(); }
    }
    const ctx = {window:{SpeechRecognition:supported ? Recognition : undefined}, els:{input}, selectedImage:null,
      $:(selector)=>selector === '#mic-btn' || selector === '#m-mic' ? button : input,
      toast: text=>notices.push(text), sendMessage:text=>sent.push(text), send:text=>sent.push(text),
      recognition:null, listening:false, recog:null, recogListening:false};
    vm.runInNewContext(source.slice(start,end)+'\nsetupVoice();',ctx);
    return {button,input,sent,notices,get recognition(){return instance;}};
  }
  test(`${name}: click starts one-shot recognition and sends only recognized speech`,()=>{
    const ui=mount(); ui.button.onclick(); assert.equal(ui.recognition.continuous,false);
    ui.recognition.onresult({results:[[{transcript:'你好'}]]}); ui.recognition.onend();
    assert.deepEqual(ui.sent,['你好']);
  });
  test(`${name}: existing draft is retained and not sent automatically`,()=>{
    const ui=mount(); ui.input.value='草稿'; ui.button.onclick();
    ui.recognition.onresult({results:[[{transcript:'你好'}]]}); ui.recognition.onend();
    assert.equal(ui.input.value,'草稿\n你好'); assert.deepEqual(ui.sent,[]); assert.equal(ui.input.focused,true);
  });
  test(`${name}: denial does not send an existing draft`,()=>{
    const ui=mount(); ui.input.value='草稿'; ui.button.onclick();
    ui.recognition.onerror({error:'not-allowed'}); ui.recognition.onend();
    assert.deepEqual(ui.sent,[]); assert.equal(ui.input.value,'草稿'); assert.match(ui.notices[0],/权限/);
  });
  test(`${name}: unsupported recognition explains how to continue`,()=>{
    const ui=mount(false); ui.button.onclick(); assert.match(ui.notices[0],/不支持语音识别/);
  });
}
