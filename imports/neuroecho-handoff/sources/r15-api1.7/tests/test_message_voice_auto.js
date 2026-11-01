const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
function setup() {
  const events={}, rows=[], observers=[], store=new Map(); let hidden=false, blocked=false;
  class Observer { constructor(cb){this.cb=cb; observers.push(this)} observe(){} }
  const doc={readyState:'loading',body:{},get hidden(){return hidden},addEventListener:(n,fn)=>{(events[n] ||= []).push(fn)},
    querySelector(selector){if(selector.startsWith('#app #messages')) return {querySelectorAll:()=>rows.map(x=>x.button)};return null},
    querySelectorAll(){return rows.map(x=>x.msg)}};
  const win={NianxiangSound:{isBlocked:()=>blocked},XinjiVoice:{stop(){}},};
  const storage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)};
  const notify=()=>observers.forEach(o=>o.cb());
  function add(id,{local=true}={}){
    const attrs={'aria-pressed':'false','aria-busy':'false'};let clicks=0;
    const native={textContent:'朗读',getAttribute:k=>attrs[k],click(){clicks++;attrs['aria-pressed']='true';attrs['aria-busy']='true'}};
    const slot={querySelector:()=>null}, button={hidden:local,dataset:{},textContent:'生成语音',setAttribute(){},getAttribute(){},closest:()=>msg,click(){this.textContent='正在生成语音…'}};
    const msg={dataset:{messageId:id},querySelector:s=>s==='[data-voice-clip]'?button:s==='[data-voice-message]'?native:s==='[data-voice-clip-slot]'?slot:null};
    const item={msg,button,native,get clicks(){return clicks},end(){attrs['aria-pressed']='false';attrs['aria-busy']='false';notify()}};rows.push(item);return item;
  }
  vm.runInNewContext(fs.readFileSync('web/message-voice.js','utf8'),{window:win,document:doc,localStorage:storage,MutationObserver:Observer,queueMicrotask});
  const run=()=>{for(const fn of events.DOMContentLoaded||[])fn()};
  return{win,run,add,store,notify,setHidden:v=>hidden=v,setBlocked:v=>blocked=v};
}
test('history is silent, first fresh reply auto reads once, and replies queue in order',async()=>{
  const e=setup(), old=e.add('old');e.run();assert.equal(old.clicks,0);
  const first=e.add('first');e.win.XinjiMessageVoice.announce('first');assert.equal(first.clicks,1);assert.equal(first.button.hidden,false);
  e.win.XinjiMessageVoice.announce('first');assert.equal(first.clicks,1);
  const second=e.add('second');e.win.XinjiMessageVoice.announce('second');assert.equal(second.clicks,0);
  first.end();await Promise.resolve();assert.equal(second.clicks,1);
});
test('failed clip falls back to local speech and the next reply proceeds after it ends',async()=>{
  const e=setup();e.run();const first=e.add('first',{local:false}),second=e.add('second');
  e.win.XinjiMessageVoice.announce('first');e.win.XinjiMessageVoice.announce('second');
  assert.equal(first.button.textContent,'正在生成语音…');assert.equal(second.clicks,0);
  first.button.textContent='语音不可用，可使用朗读';e.win.XinjiMessageVoice.clipFailed('first',first.button);
  assert.equal(first.clicks,1);assert.equal(second.clicks,0);
  first.end();await Promise.resolve();assert.equal(second.clicks,1);
});
test('late clip failure after cancellation does not affect a new playback',async()=>{
  const e=setup();e.run();const first=e.add('first',{local:false});e.win.XinjiMessageVoice.announce('first');
  e.win.XinjiMessageVoice.cancel();const second=e.add('second');e.win.XinjiMessageVoice.announce('second');
  e.win.XinjiMessageVoice.clipFailed('first',first.button);assert.equal(second.clicks,1);
  const third=e.add('third');e.win.XinjiMessageVoice.announce('third');assert.equal(third.clicks,0);
  second.end();await Promise.resolve();assert.equal(third.clicks,1);
});
test('disabled, hidden, and recording states do not read or defer old replies',async()=>{
  const e=setup();e.run();e.store.set('xinji_voice_autoplay_v1','false');const a=e.add('a');e.win.XinjiMessageVoice.announce('a');
  e.store.delete('xinji_voice_autoplay_v1');e.setHidden(true);const b=e.add('b');e.win.XinjiMessageVoice.announce('b');
  e.setHidden(false);e.setBlocked(true);const c=e.add('c');e.win.XinjiMessageVoice.announce('c');e.setBlocked(false);
  await Promise.resolve();assert.equal(a.clicks+b.clicks+c.clicks,0);
  e.win.XinjiMessageVoice.announce('a');assert.equal(a.clicks,0);
});
