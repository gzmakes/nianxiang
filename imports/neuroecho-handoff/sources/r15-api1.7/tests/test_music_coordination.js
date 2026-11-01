const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup() {
  const listeners = {}, windowListeners = {}, audios = [], observers = [];
  let quiet = false, resumeAudio;
  const document = {
    hidden: false, readyState: 'loading', body: {}, currentScript: {src:'http://localhost/static/soundscape.js'},
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    dispatchEvent(event) { for (const fn of listeners[event.type] || []) fn(event); },
    querySelector(selector) { return selector.includes('data-b-resume') && quiet ? {hidden:false} : null; },
    getElementById() { return null; }
  };
  class Audio {
    constructor() { this.paused = true; audios.push(this); }
    play() { this.paused = false; return Promise.resolve(); }
    pause() { this.paused = true; }
  }
  class AudioContext {
    constructor() { this.state = 'running'; this.currentTime = 0; this.destination = {}; }
    createGain() { return {gain:{value:0,setValueAtTime(){},linearRampToValueAtTime(){},exponentialRampToValueAtTime(){},cancelScheduledValues(){}},connect(){}}; }
    createBiquadFilter() { return {frequency:{},Q:{},connect(){}}; }
    createDelay() { return {delayTime:{},connect(){}}; }
    createOscillator() { return {frequency:{},detune:{},connect(){},start(){},stop(){}}; }
    resume() { return resumeAudio ? resumeAudio() : Promise.resolve(); }
  }
  const window = {AudioContext, addEventListener(type, fn) {(windowListeners[type] ||= []).push(fn);}, dispatchEvent(event) {for (const fn of windowListeners[event.type] || []) fn(event);}};
  const localStorage = {getItem(key) {return key === 'xinji_soundscape_v1' ? JSON.stringify({music:true}) : null;}, setItem(){}};
  const sandbox = {window, document, localStorage, Audio, URL, CustomEvent: class {constructor(type, init) {this.type=type; this.detail=init.detail;}},
    MutationObserver: class {constructor(fn) {observers.push(fn);} observe(){}}, setTimeout(){return 1;}, clearTimeout(){}, setInterval(){return 1;}, clearInterval(){}};
  vm.runInNewContext(fs.readFileSync('web/soundscape.js','utf8'),sandbox);
  vm.runInNewContext(fs.readFileSync('web/ambient-music.js','utf8'),sandbox);
  document.dispatchEvent({type:'DOMContentLoaded'});
  return {window, document, audios, click() {document.dispatchEvent({type:'click', target:{closest(){return null;}}});}, setQuiet(value) {quiet=value; observers.forEach(fn=>fn());},
    setResume(fn) {resumeAudio=fn;}, setSuspended() {window.AudioContext = class extends AudioContext {constructor(){super();this.state='suspended';}};}};
}

test('recording and quiet pause music while voice only ducks it', async () => {
  const env = setup(), sound = env.window.NianxiangSound, ambient = env.window.XinjiAmbientMusic;
  env.click(); assert.equal(env.audios[0].paused, false);
  assert.equal(await ambient.start(), true); assert.equal(env.audios[0].paused, true); assert.equal(ambient.playing(), true);
  sound.setRecording(true); assert.equal(ambient.playing(), false); assert.equal(await ambient.start(), false);
  sound.setRecording(false); assert.equal(await ambient.start(), true);
  sound.setVoiceActive(true); assert.equal(ambient.playing(), true); assert.equal(sound.isBlocked(), false);
  sound.setVoiceActive(false); assert.equal(ambient.playing(), true);
  env.setQuiet(true); assert.equal(ambient.playing(), false); assert.equal(await ambient.start(), false);
  env.setQuiet(false); assert.equal(ambient.playing(), false);
});

test('entering quiet mode stops the current voice and clears queued auto playback', () => {
  const env = setup(), calls = [];
  env.window.XinjiMessageVoice = {cancel: () => calls.push('cancel')};
  env.window.XinjiVoice = {stop: () => calls.push('stop')};
  env.click(); env.setQuiet(true);
  assert.deepEqual(calls, ['cancel', 'stop']);
  assert.equal(env.audios[0].paused, true);
  env.setQuiet(false);
  assert.deepEqual(calls, ['cancel', 'stop']);
});

test('switching back to local music cancels a pending conversation music start', async () => {
  const env = setup(); let resolve;
  env.setSuspended(); env.setResume(() => new Promise(r => {resolve=r;}));
  const start = env.window.XinjiAmbientMusic.start();
  env.click(); assert.equal(env.audios[0].paused, false);
  resolve(); assert.equal(await start, false);
  assert.equal(env.window.XinjiAmbientMusic.playing(), false);
  assert.equal(env.audios[0].paused, false);
});

test('compact sound settings retain saved choices and working controls', async () => {
  const saved = {music:false,effects:true,theme:'tide',musicVolume:0.4,effectsVolume:0.6};
  const store = new Map([['xinji_soundscape_v1', JSON.stringify(saved)]]), elements = new Map();
  const node = () => ({value:'',checked:false,hidden:false,textContent:'',setAttribute(){}});
  const panel = {isConnected:true,innerHTML:'',querySelector(selector) {if (!elements.has(selector)) elements.set(selector,node()); return elements.get(selector);}};
  const document = {currentScript:{src:'http://localhost/static/soundscape.js'},readyState:'loading',hidden:false,
    addEventListener(){},querySelector(){return null},createElement(){return panel}};
  const localStorage = {getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)};
  class Audio {constructor(){this.paused=true;this.currentTime=0;} play(){this.paused=false;return Promise.resolve();} pause(){this.paused=true;}}
  const win={dispatchEvent(){}};
  vm.runInNewContext(fs.readFileSync('web/soundscape.js','utf8'),{window:win,document,localStorage,Audio,URL,
    CustomEvent:class {},setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,clearInterval(){},Date,Math,JSON});
  const container={querySelector:()=>null,appendChild(){}};win.NianxiangSound.mount(container);
  const get=key=>elements.get(`[${key}]`);
  assert.equal(get('data-sound-music').checked,false);assert.equal(get('data-sound-effects').checked,true);
  assert.equal(get('data-sound-theme').value,'tide');assert.equal(get('data-sound-music-volume').value,0.4);assert.equal(get('data-sound-effects-volume').value,0.6);
  get('data-sound-theme').onchange({target:{value:'stardust'}});
  get('data-sound-music-volume').oninput({target:{value:'0.3'}});
  get('data-sound-effects-volume').oninput({target:{value:'0.5'}});
  assert.deepEqual(JSON.parse(store.get('xinji_soundscape_v1')),{...saved,theme:'stardust',musicVolume:0.3,effectsVolume:0.5});
  get('data-breath-start').onclick();assert.equal(win.NianxiangSound.getState().guiding,true);
  get('data-breath-start').onclick();assert.equal(win.NianxiangSound.getState().guidePaused,true);
  get('data-breath-end').onclick();assert.equal(win.NianxiangSound.getState().guiding,false);
  get('data-sound-silence').onclick();assert.equal(win.NianxiangSound.getState().effects,false);
});


test('voice ramps background volume down and restores the latest chosen volume without resuming stopped music', () => {
  let now = 0, serial = 0; const timers = new Map(), audios = [], elements = new Map();
  const node = () => ({value:'',checked:false,hidden:false,textContent:'',setAttribute(){}});
  const panel = {isConnected:true,innerHTML:'',querySelector(selector) {if (!elements.has(selector)) elements.set(selector,node()); return elements.get(selector);}};
  const document = {currentScript:{src:'http://localhost/static/soundscape.js'},readyState:'loading',hidden:false,addEventListener(){},querySelector(){return null},createElement(){return panel}};
  const localStorage = {getItem(){return JSON.stringify({music:false,musicVolume:0.5})},setItem(){}};
  class Audio {constructor(){this.paused=true;this.volume=1;audios.push(this)} play(){this.paused=false;return Promise.resolve()} pause(){this.paused=true}}
  const win={dispatchEvent(){}}; const tick=(ms)=>{const end=now+ms;while(true){let entry=[...timers.entries()].sort((a,b)=>a[1].at-b[1].at)[0];if(!entry || entry[1].at>end) break;timers.delete(entry[0]);now=entry[1].at;entry[1].fn()}now=end};
  vm.runInNewContext(fs.readFileSync('web/soundscape.js','utf8'),{window:win,document,localStorage,Audio,URL,CustomEvent:class {},
    setTimeout:(fn,ms)=>{const id=++serial;timers.set(id,{fn,at:now+ms});return id},clearTimeout:id=>timers.delete(id),setInterval:()=>1,clearInterval(){},Date:{now:()=>now},Math,JSON});
  win.NianxiangSound.mount({querySelector:()=>null,appendChild(){}});
  win.NianxiangSound.setMusicEnabled(true); const music=audios[0]; assert.equal(music.volume,0.5);
  win.NianxiangSound.setVoiceActive(true); tick(200); assert.ok(music.volume<0.5&&music.volume>0.36);assert.equal(music.paused,false);
  tick(250); assert.ok(Math.abs(music.volume-0.36)<1e-8);
  elements.get('[data-sound-music-volume]').oninput({target:{value:'0.8'}});tick(450);assert.ok(Math.abs(music.volume-0.576)<1e-8);
  win.NianxiangSound.setVoiceActive(false);tick(200);assert.ok(music.volume>0.576&&music.volume<0.8);tick(250);assert.ok(Math.abs(music.volume-0.8)<1e-8);
  win.NianxiangSound.setVoiceActive(true);win.NianxiangSound.setMusicEnabled(false);win.NianxiangSound.setVoiceActive(false);tick(450);assert.equal(music.paused,true);
});
