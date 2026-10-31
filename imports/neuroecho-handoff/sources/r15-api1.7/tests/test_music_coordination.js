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

test('starting conversation music stops the local background, and recording/voice/quiet stop it', async () => {
  const env = setup(), sound = env.window.NianxiangSound, ambient = env.window.XinjiAmbientMusic;
  env.click(); assert.equal(env.audios[0].paused, false);
  assert.equal(await ambient.start(), true); assert.equal(env.audios[0].paused, true); assert.equal(ambient.playing(), true);
  sound.setRecording(true); assert.equal(ambient.playing(), false); assert.equal(await ambient.start(), false);
  sound.setRecording(false); assert.equal(await ambient.start(), true);
  sound.setVoiceActive(true); assert.equal(ambient.playing(), false); assert.equal(await ambient.start(), false);
  sound.setVoiceActive(false); assert.equal(await ambient.start(), true);
  env.setQuiet(true); assert.equal(ambient.playing(), false); assert.equal(await ambient.start(), false);
  env.setQuiet(false); assert.equal(ambient.playing(), false);
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
