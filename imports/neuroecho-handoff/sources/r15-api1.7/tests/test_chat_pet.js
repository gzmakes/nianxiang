const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('web/chat-pet.js','utf8');
const inventory = JSON.parse(source.match(/const INVENTORY = (\{.*?\});/)[1]);
function fixture(random=.5,{composerReady=true,reduceMotion=false,memeData=null,width=900,height=700,composerRect=null,sidebarRect=null,mobile=false,previewRect=null}={}){
  let time=1000,next=1;const timers=new Map(),rafs=new Map(), listeners={},windowListeners={};
  const make=name=>({name,style:{},dataset:{},hidden:false,offsetWidth:300,offsetHeight:169,attributes:{},events:{},children:[],
    classList:{values:new Set(),add(v){this.values.add(v)},remove(v){this.values.delete(v)},contains(v){return this.values.has(v)},toggle(v,on){on?this.values.add(v):this.values.delete(v)}},
    addEventListener(k,fn){this.events[k]=fn},setAttribute(k,v){this.attributes[k]=v},append(...a){this.children.push(...a)},replaceChildren(){this.children=[]},remove(){this.removed=true},focus(){},contains(){return false},setPointerCapture(){},
    getBoundingClientRect(){return {left:200,top:400,right:500,bottom:569,width:300,height:169}},
    play(){this.played=(this.played||0)+1;return Promise.resolve()},pause(){this.paused=true}
  });
  const hit=make('hit'),bubble=make('bubble'),root=make('root'),menu=make('menu'),vid=[make('v0'),make('v1')];
  let div=0;root.querySelector=s=>s.includes('hit')?hit:bubble;root.querySelectorAll=()=>vid;menu.querySelector=()=>menu.children[0];
  const composer={getBoundingClientRect:()=>composerReady?(composerRect||{left:100,top:620,right:800,bottom:680,width:700,height:60}):({left:0,top:0,right:0,bottom:0,width:0,height:0})};
  const preview={getBoundingClientRect:()=>previewRect||{left:0,top:0,right:0,bottom:0,width:0,height:0}};
  const dispatched=[];let inputFocused=false;const input={focus(){inputFocused=true}};
  const body=make('body');
  const doc={hidden:false,documentElement:{dataset:{}},body,querySelector:s=>s==='#m-composer'?(mobile?composer:null):s==='#m-image-preview'?(mobile?preview:null):s.includes('composer')?composer:s==='#design-context' && sidebarRect?{getBoundingClientRect:()=>sidebarRect}:s.includes('#input')?input:null,
    dispatchEvent(e){dispatched.push(e);listeners[e.type]?.(e)},
    createElement:n=>n==='button'?make('button'):div++===0?root:div===2?menu:make('panel'),addEventListener(k,fn){listeners[k]=fn}};
  const math=Object.create(Math);math.random=()=>random;
  const mediaQuery={matches:reduceMotion,addEventListener(k,fn){this.events??={};this.events[k]=fn}};
  const ctx={document:doc,window:{addEventListener(k,fn){windowListeners[k]=fn}},innerWidth:width,innerHeight:height,matchMedia:()=>mediaQuery,performance:{now:()=>time},
    setTimeout(fn,ms){const id=next++;timers.set(id,{fn,ms});return id},clearTimeout(id){timers.delete(id)},requestAnimationFrame(fn){const id=next++;rafs.set(id,fn);return id},cancelAnimationFrame(id){rafs.delete(id)},
    CustomEvent:class{constructor(type,options){this.type=type;this.detail=options?.detail}},
    MutationObserver:class{constructor(fn){this.fn=fn}observe(target){if(target===doc.documentElement)ctx.observer=this.fn;else if(target===preview)ctx.previewObserver=this.fn}},ResizeObserver:class{constructor(fn){ctx.resizeObserver=fn}observe(){}},Math:math,
    fetch:async url=>({ok:true,json:async()=>url==='/api/pet-memes'?(memeData||{available:false,memes:[]}):({available:true,animations:Object.values(inventory).flat().map(name=>({name,url:'/api/pet-assets/'+name+'.webm'}))})})};
  vm.runInNewContext(source,ctx);return {hit,bubble,root,menu,vid,timers,rafs,doc,listeners,windowListeners,ctx,body,dispatched,isInputFocused:()=>inputFocused,setReduced(value,notify=true){mediaQuery.matches=value;if(notify)mediaQuery.events?.change?.({matches:value})},setComposerReady(value){composerReady=value},setComposerRect(value){composerRect=value},setPreviewRect(value){previewRect=value},setTime(t){time=t},runFrame(t){for(const [id,fn] of [...rafs]){rafs.delete(id);fn(t)}}};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('all 106 original animations have the intended categories and event slots',()=>{
  const names=Object.values(inventory).flat();assert.equal(names.length,106);assert.equal(new Set(names).size,106);
  assert.equal(inventory.click.length,5);assert.equal(inventory.move.length,3);
  assert.equal(Object.entries(inventory).filter(([k])=>k.startsWith('random:')).flatMap(([,v])=>v).length,80);
  assert.equal(inventory['event:workStatus'].length,6);assert.equal(inventory['event:balance'].length,6);assert.equal(inventory['event:whisper'].length,3);
});
test('starts with real idle video and a click plays a different response on second video',async()=>{
  const f=fixture();await tick();assert.match(f.vid[0].src,/待机呼吸休闲/);f.hit.events.click();await tick();
  assert.ok(inventory.click.some(x=>f.vid[1].src.includes(x)));assert.equal(f.vid[1].classList.contains('is-active'),true);assert.equal(f.vid[0].classList.contains('is-active'),false);assert.equal(f.bubble.hidden,false);
  f.vid[1].onended();await tick();assert.match(f.vid[0].src,/待机呼吸休闲/);
});
test('weighted move causes visible position change when random chain selects it',async()=>{
  const f=fixture(.17);await tick();const before=f.ctx.window.NianxiangPet.getState().x;
  f.vid[0].onended();await tick();assert.ok(inventory.move.some(x=>f.vid[1].src.includes(x)));
  f.runFrame(6000);assert.notEqual(f.ctx.window.NianxiangPet.getState().x,before);
});
test('three-level menu reaches and plays an original named action',async()=>{
  const f=fixture();await tick();f.hit.events.contextmenu({preventDefault(){}});
  f.menu.children[0].children.find(x=>x.textContent.startsWith('动作')).events.click();
  f.menu.children[1].children.find(x=>x.textContent.startsWith('玩耍')).events.click();
  const action=f.menu.children[2].children.find(x=>x.textContent==='三球抛接');assert.ok(action);action.events.click();await tick();
  assert.match(f.vid[1].src,/三球抛接/);assert.equal(f.menu.hidden,true);
});
test('thinking status uses original thinking action and does not claim success on quiet',async()=>{
  const f=fixture();await tick();f.doc.documentElement.dataset.presenceState='thinking';f.ctx.observer();await tick();
  assert.match(f.vid[1].src,/工作状态-思考冒泡/);f.doc.documentElement.dataset.presenceState='quiet';f.ctx.observer();await tick();
  assert.match(f.vid[0].src,/待机呼吸休闲/);assert.equal(f.ctx.window.NianxiangPet.getState().work,null);
});
test('active work has a persistent low-priority bubble that yields to conversation and lock',async()=>{
  const f=fixture();await tick();f.ctx.window.NianxiangPet.setWork('thinking');await tick();
  assert.equal(f.bubble.textContent,'让我整理一下思路～');assert.equal(f.bubble.hidden,false);
  assert.equal([...f.timers.values()].filter(x=>x.ms===10000).length,0);
  f.ctx.window.NianxiangPet.say('对话回复',2);
  f.ctx.window.NianxiangPet.setWork('working');assert.equal(f.bubble.textContent,'对话回复');
  const timer=[...f.timers.values()].find(x=>x.ms===10000);timer.fn();
  assert.equal(f.bubble.textContent,'正在处理这一步。');assert.equal(f.bubble.hidden,false);
  f.ctx.window.NianxiangPet.setLock(true);assert.equal(f.bubble.hidden,true);
  f.ctx.window.NianxiangPet.setLock(false);assert.equal(f.bubble.hidden,false);
  f.ctx.window.NianxiangPet.setWork(null);assert.equal(f.bubble.hidden,true);
});
test('long press opens menu and drag uses capture without opening menu',async()=>{
  const f=fixture();await tick();const event={button:0,pointerId:1,pointerType:'touch',clientX:300,clientY:350};f.hit.events.pointerdown(event);
  const long=[...f.timers.values()].find(x=>x.ms===500);assert.ok(long);long.fn();assert.equal(f.menu.hidden,false);
  f.hit.events.pointerdown(event);f.setTime(1030);f.hit.events.pointermove({...event,clientX:320,preventDefault(){}});await tick();
  assert.equal(f.root.classList.contains('is-dragging'),true);assert.match(f.vid[1].src,/被鼠标拖拽悬空反馈/);
});

test('mobile dragging and throwing keep the pet body above the composer',async()=>{
  const rect={left:16,top:410,right:304,bottom:470,width:288,height:60};
  const f=fixture(.5,{mobile:true,width:320,height:568,composerRect:rect});await tick();
  const edge=rect.top-f.root.offsetHeight*335/360-8;
  const e={button:0,pointerId:1,pointerType:'touch',clientX:220,clientY:290};
  f.hit.events.pointerdown(e);f.setTime(1050);
  f.hit.events.pointermove({...e,clientY:500,preventDefault(){}});
  for(let t=1060;t<=1300;t+=20)f.runFrame(t);
  assert.ok(f.ctx.window.NianxiangPet.getState().y<=edge+1e-6);
  f.setTime(1100);f.hit.events.pointermove({...e,clientY:560,preventDefault(){}});f.setTime(1110);
  f.hit.events.pointerup({...e,clientY:560});
  for(let t=1320;t<=2300;t+=20){f.runFrame(t);assert.ok(f.ctx.window.NianxiangPet.getState().y<=edge+1e-6)}
});

test('mobile composer resize only moves the pet when its body would overlap',async()=>{
  const f=fixture(.5,{mobile:true,width:390,height:844,composerRect:{left:16,top:688,right:374,bottom:744,width:358,height:56}});await tick();
  const before=f.ctx.window.NianxiangPet.getState().y;
  f.setComposerRect({left:16,top:720,right:374,bottom:776,width:358,height:56});f.ctx.resizeObserver();
  assert.equal(f.ctx.window.NianxiangPet.getState().y,before);
  f.setComposerRect({left:16,top:400,right:374,bottom:456,width:358,height:56});f.ctx.resizeObserver();
  assert.ok(f.ctx.window.NianxiangPet.getState().y<=400-f.root.offsetHeight*335/360-8+1e-6);
});

test('a visible mobile image preview immediately moves the pet above it and restores the composer limit when hidden',async()=>{
  const f=fixture(.5,{mobile:true,width:320,height:568,composerRect:{left:16,top:412,right:304,bottom:470,width:288,height:58}});await tick();
  const before=f.ctx.window.NianxiangPet.getState().y;
  f.setPreviewRect({left:16,top:350,right:304,bottom:406,width:288,height:56});f.ctx.previewObserver();
  const previewLimit=350-f.root.offsetHeight*335/360-8;
  assert.ok(f.ctx.window.NianxiangPet.getState().y<=previewLimit+1e-6);
  assert.ok(f.ctx.window.NianxiangPet.getState().y<before);
  f.setPreviewRect(null);f.ctx.previewObserver();
  const e={button:0,pointerId:1,pointerType:'touch',clientX:200,clientY:200};
  f.hit.events.pointerdown(e);f.hit.events.pointermove({...e,clientY:500,preventDefault(){}});
  for(let t=1000;t<=1300;t+=20)f.runFrame(t);
  const after=f.ctx.window.NianxiangPet.getState().y;
  assert.ok(after>previewLimit);
  assert.ok(after<=412-f.root.offsetHeight*335/360-8+1e-6);
});

test('a menu stays anchored when a clip ends and the random chain resumes after closing',async()=>{
  const f=fixture(.17);await tick();
  const before=f.ctx.window.NianxiangPet.getState().x;
  f.hit.events.contextmenu({preventDefault(){}});
  f.vid[0].onended();await tick();
  assert.equal(f.ctx.window.NianxiangPet.getState().x,before);
  assert.equal(f.ctx.window.NianxiangPet.getState().name,inventory.idle[0]);
  assert.equal(f.rafs.size,0);
  f.listeners.keydown({key:'Escape'});await tick();
  assert.ok(inventory.move.includes(f.ctx.window.NianxiangPet.getState().name));
  f.runFrame(6000);assert.notEqual(f.ctx.window.NianxiangPet.getState().x,before);
});

test('choosing an action after a clip ends in the menu wins over automatic resume',async()=>{
  const f=fixture(.17);await tick();f.hit.events.contextmenu({preventDefault(){}});
  f.vid[0].onended();await tick();
  f.menu.children[0].children.find(x=>x.textContent.startsWith('动作')).events.click();
  f.menu.children[1].children.find(x=>x.textContent.startsWith('玩耍')).events.click();
  f.menu.children[2].children.find(x=>x.textContent==='三球抛接').events.click();await tick();
  assert.equal(f.ctx.window.NianxiangPet.getState().name,'三球抛接');
  assert.equal(f.rafs.size,0);
});

test('a long press without a synthetic click does not swallow the next tap',async()=>{
  const f=fixture();await tick();const event={button:0,pointerId:1,pointerType:'touch',clientX:300,clientY:350};
  f.hit.events.pointerdown(event);[...f.timers.values()].find(x=>x.ms===500).fn();
  f.hit.events.pointerup(event);
  const cleanup=[...f.timers.values()].find(x=>x.ms===750);assert.ok(cleanup);cleanup.fn();
  f.hit.events.pointerdown({...event,pointerId:2});f.hit.events.pointerup({...event,pointerId:2});f.hit.events.click();await tick();
  assert.ok(inventory.click.includes(f.ctx.window.NianxiangPet.getState().name));
});

test('a synthetic click immediately after a long press is suppressed',async()=>{
  const f=fixture();await tick();const event={button:0,pointerId:1,pointerType:'touch',clientX:300,clientY:350};
  f.hit.events.pointerdown(event);[...f.timers.values()].find(x=>x.ms===500).fn();
  f.hit.events.pointerup(event);f.hit.events.click();await tick();
  assert.equal(f.menu.hidden,false);assert.equal(f.ctx.window.NianxiangPet.getState().name,inventory.idle[0]);
});

test('a long-press release click cannot activate the menu under the finger',async()=>{
  const f=fixture();await tick();const event={button:0,pointerId:1,pointerType:'touch',clientX:300,clientY:350};
  f.hit.events.pointerdown(event);[...f.timers.values()].find(x=>x.ms===500).fn();f.hit.events.pointerup(event);
  let stopped=false,prevented=false;
  f.listeners.click({preventDefault(){prevented=true},stopImmediatePropagation(){stopped=true}});
  if(!stopped)f.menu.children[0].children.find(x=>x.textContent.startsWith('动作')).events.click();
  assert.equal(prevented,true);assert.equal(stopped,true);assert.equal(f.menu.children.length,1);
  // The next actual press still activates the menu immediately.
  const item=f.menu.children[0].children.find(x=>x.textContent.startsWith('动作'));
  f.menu.contains=target=>target===item;
  f.listeners.pointerdown({target:item});item.events.click();assert.equal(f.menu.children.length,2);
});

test('a fresh tap is allowed before long-press cleanup when no click was synthesized',async()=>{
  const f=fixture();await tick();const event={button:0,pointerId:1,pointerType:'touch',clientX:300,clientY:350};
  f.hit.events.pointerdown(event);[...f.timers.values()].find(x=>x.ms===500).fn();f.hit.events.pointerup(event);
  const item=f.menu.children[0].children.find(x=>x.textContent.startsWith('动作'));
  f.menu.contains=target=>target===item;
  f.listeners.pointerdown({target:item});let stopped=false;
  f.listeners.click({preventDefault(){},stopImmediatePropagation(){stopped=true}});
  if(!stopped)item.events.click();assert.equal(stopped,false);assert.equal(f.menu.children.length,2);
});


test('out-of-order play promises cannot pause the newer animation on a shared slot',async()=>{
  const f=fixture();await tick();const pending=[];let pauses=0;
  f.vid[1].play=()=>new Promise((resolve,reject)=>pending.push({resolve,reject}));
  f.vid[1].pause=()=>{pauses++};
  const first=f.ctx.window.NianxiangPet.play(inventory.click[0]);
  const second=f.ctx.window.NianxiangPet.play(inventory.click[1]);
  assert.equal(pending.length,2);pending[1].resolve();await second;
  pending[0].resolve();await first;
  assert.equal(pauses,0);assert.equal(f.ctx.window.NianxiangPet.getState().name,inventory.click[1]);
  assert.equal(f.vid[1].classList.contains('is-active'),true);
});

test('failed transition keeps the old clip able to advance the random chain',async()=>{
  const f=fixture();await tick();let calls=0;
  f.vid[1].play=()=>++calls===1?Promise.reject(new Error('decode')):Promise.resolve();
  assert.equal(await f.ctx.window.NianxiangPet.play(inventory.click[0]),false);
  assert.equal(f.ctx.window.NianxiangPet.getState().name,inventory.idle[0]);
  f.vid[0].onended();await tick();
  assert.equal(calls,2);assert.equal(f.vid[1].classList.contains('is-active'),true);
});

test('a video error after playback starts falls back and resumes the chain',async()=>{
  const f=fixture(.17);await tick();
  f.vid[0].onerror();await tick();
  assert.notEqual(f.ctx.window.NianxiangPet.getState().name,inventory.idle[0]);
  assert.equal(f.ctx.window.NianxiangPet.getState().slot,1);
  f.vid[1].onended();await tick();assert.ok(inventory.move.includes(f.ctx.window.NianxiangPet.getState().name));
});

test('errors after successful starts have a bounded recovery chain',async()=>{
  const f=fixture();await tick();
  f.vid[0].onerror();await tick();f.vid[1].onerror();await tick();f.vid[0].onerror();await tick();
  assert.equal(f.ctx.window.NianxiangPet.getState().slot,0);
  assert.equal(f.vid[0].onerror,null);assert.equal(f.bubble.textContent,'这个动作暂时播放不了。');
  assert.equal(f.vid[0].played+f.vid[1].played,3);
});

test('an obsolete video error cannot interrupt the current clip',async()=>{
  const f=fixture();await tick();const staleError=f.vid[0].onerror;
  await f.ctx.window.NianxiangPet.play(inventory.click[0]);staleError();await tick();
  assert.equal(f.ctx.window.NianxiangPet.getState().name,inventory.click[0]);
  assert.equal(f.vid[0].played+f.vid[1].played,2);
});

test('an active video error does not steal the slot from a pending explicit action',async()=>{
  const f=fixture();await tick();let resolveAction;
  f.vid[1].play=()=>new Promise(resolve=>{resolveAction=resolve});
  const pending=f.ctx.window.NianxiangPet.play(inventory.click[0]);
  f.vid[0].onerror();resolveAction();assert.equal(await pending,true);
  assert.equal(f.ctx.window.NianxiangPet.getState().name,inventory.click[0]);
});

test('failed transition recovers when old clip ends during pending playback',async()=>{
  const f=fixture();await tick();let rejectFirst,calls=0;
  f.vid[1].play=()=>++calls===1?new Promise((resolve,reject)=>{rejectFirst=reject}):Promise.resolve();
  const attempt=f.ctx.window.NianxiangPet.play(inventory.click[0]);
  f.vid[0].onended();rejectFirst(new Error('decode'));assert.equal(await attempt,false);await tick();
  assert.equal(calls,2);assert.equal(f.ctx.window.NianxiangPet.getState().name,inventory.idle[0]);
  assert.equal(f.vid[1].classList.contains('is-active'),true);
});

test('autoplay rejection waits for a user gesture rather than retrying continuously',async()=>{
  const f=fixture();await tick();let rejectFirst,calls=0;
  f.vid[1].play=()=>++calls===1?new Promise((resolve,reject)=>{rejectFirst=reject}):Promise.resolve();
  const attempt=f.ctx.window.NianxiangPet.play(inventory.click[0]);
  f.vid[0].onended();const blocked=new Error('blocked');blocked.name='NotAllowedError';rejectFirst(blocked);
  assert.equal(await attempt,false);await tick();assert.equal(calls,1);
  f.hit.events.click();await tick();assert.equal(calls,2);
});


test('delayed fade-out cannot pause a slot reused for a pending animation',async()=>{
  const f=fixture();await tick();await f.ctx.window.NianxiangPet.play(inventory.click[0]);
  const oldPause=[...f.timers.values()].find(x=>x.ms===200);assert.ok(oldPause);
  let resolveNext,pauses=0;f.vid[0].play=()=>new Promise(resolve=>{resolveNext=resolve});f.vid[0].pause=()=>{pauses++};
  const attempt=f.ctx.window.NianxiangPet.play(inventory.click[1]);
  // Model an already-queued timeout even after clearTimeout.
  oldPause.fn();assert.equal(pauses,0);resolveNext();await attempt;
  assert.equal(f.ctx.window.NianxiangPet.getState().name,inventory.click[1]);
});


test('hover opens separate cascading panels and all 106 original clips are reachable',async()=>{
  const f=fixture();await tick();f.hit.events.contextmenu({preventDefault(){}});
  f.menu.children[0].children.find(x=>x.textContent.startsWith('动作')).events.pointerenter({pointerType:'mouse'});
  assert.equal(f.menu.children.length,2);
  const groups=[['待机','idle'],['转向','turn'],['拖拽','drag'],['点击回应','click'],['移动','move'],
    ['小动作','random:小动作'],['玩耍','random:玩耍'],['吃什么','random:吃什么'],['时节','random:时节'],['文字','random:文字'],
    ['余额','event:balance'],['碎碎念','event:whisper'],['工作状态','event:workStatus']];
  const reached=[];
  for(const [label,key] of groups){
    const item=f.menu.children[1].children.find(x=>x.textContent===label+'  ›');assert.ok(item,label);
    item.events.pointerenter({pointerType:'mouse'});
    assert.equal(f.menu.children.length,3);
    const shown=f.menu.children[2].children.map(x=>x.textContent);
    assert.deepEqual(shown,inventory[key]);reached.push(...shown);
  }
  assert.equal(reached.length,106);assert.equal(new Set(reached).size,106);
});

test('menu leaves close after 200ms but reenter cancels; outside and Escape close',async()=>{
  const f=fixture();await tick();f.hit.events.contextmenu({preventDefault(){}});
  f.menu.events.pointerleave({pointerType:'touch'});assert.equal([...f.timers.values()].some(x=>x.ms===200),false);
  f.menu.events.pointerleave();let timer=[...f.timers.entries()].find(([,x])=>x.ms===200);
  assert.ok(timer);f.menu.events.pointerenter();assert.equal(f.timers.has(timer[0]),false);assert.equal(f.menu.hidden,false);
  f.menu.events.pointerleave();timer=[...f.timers.entries()].find(([,x])=>x.ms===200);timer[1].fn();assert.equal(f.menu.hidden,true);
  f.hit.events.contextmenu({preventDefault(){}});f.listeners.pointerdown({target:{}});assert.equal(f.menu.hidden,true);
  f.hit.events.contextmenu({preventDefault(){}});f.listeners.keydown({key:'Escape'});assert.equal(f.menu.hidden,true);
});

test('long press opens menu whose categories and actions can be tapped on touch',async()=>{
  const f=fixture();await tick();f.hit.events.pointerdown({button:0,pointerId:1,pointerType:'touch',clientX:300,clientY:350});
  const timer=[...f.timers.values()].find(x=>x.ms===500);timer.fn();
  f.menu.children[0].children.find(x=>x.textContent.startsWith('动作')).events.click();
  f.menu.children[1].children.find(x=>x.textContent.startsWith('点击回应')).events.click();
  f.menu.children[2].children[0].events.click();await tick();
  assert.equal(f.menu.hidden,true);assert.ok(inventory.click.includes(f.ctx.window.NianxiangPet.getState().name));
});


test('submenu expansion does not move parent panels away from the pointer',async()=>{
  const f=fixture();await tick();
  Object.defineProperty(f.menu,'offsetHeight',{get:()=>f.menu.children.length===1?60:400});
  f.hit.events.contextmenu({preventDefault(){}});const top=f.menu.style.top,left=f.menu.style.left;
  f.menu.children[0].children.find(x=>x.textContent.startsWith('动作')).events.pointerenter({pointerType:'mouse'});
  f.menu.children[1].children.find(x=>x.textContent.startsWith('玩耍')).events.pointerenter({pointerType:'mouse'});
  assert.equal(f.menu.style.top,top);assert.equal(f.menu.style.left,left);
});


test('waits for a visible composer and positions the body outside its input area',async()=>{
  const f=fixture(.5,{composerReady:false});await tick();const initial=f.ctx.window.NianxiangPet.getState();
  f.setComposerReady(true);const retry=[...f.timers.values()].find(x=>x.ms===500);assert.ok(retry);retry.fn();
  const placed=f.ctx.window.NianxiangPet.getState();
  assert.notEqual(placed.y,initial.y);assert.ok(placed.y+169*335/360<620);
  assert.ok(placed.x+300*440/640<=800);
});

test('home puts the pet to the right of the composer when space permits',async()=>{
  const r={left:100,top:620,right:800,bottom:680,width:700,height:60};
  const f=fixture(.5,{width:1400,composerRect:r});await tick();
  const state=f.ctx.window.NianxiangPet.getState();
  assert.equal(state.x+300*200/640,r.right+16);
  assert.ok(Math.abs(state.y+169*330/360-r.top)<=8.01);
  f.hit.events.contextmenu({preventDefault(){}});
  const panel=f.menu.children[0],menuLeft=parseFloat(f.menu.style.left);
  const panelRight=menuLeft+parseFloat(panel.style.left)+parseFloat(panel.style.width);
  assert.ok(Math.abs(panelRight-(state.x+300*200/640))<=9);
  const panelCenter=8+parseFloat(panel.style.top)+panel.offsetHeight/2;
  assert.ok(Math.abs(panelCenter-(state.y+169*(50+335)/720))<=25);
  assert.ok(8+parseFloat(panel.style.top)+panel.offsetHeight<=r.top-8);
  const before=[panel.style.left,panel.style.top];
  panel.children.find(x=>x.textContent.startsWith('动作')).events.click();
  assert.deepEqual([f.menu.children[0].style.left,f.menu.children[0].style.top],before);
  assert.ok(parseFloat(f.menu.children[1].style.left)<parseFloat(f.menu.children[0].style.left));
});

test('narrow viewport keeps pet above input and all menu columns in view',async()=>{
  const r={left:20,top:640,right:370,bottom:690,width:350,height:50};
  const f=fixture(.5,{width:390,height:720,composerRect:r});await tick();
  const state=f.ctx.window.NianxiangPet.getState();
  assert.ok(state.x+300*440/640<=390-8);
  assert.ok(state.y+169*335/360<r.top);
  f.hit.events.contextmenu({preventDefault(){}});
  const left=parseFloat(f.menu.style.left),width=parseFloat(f.menu.style.width);
  assert.ok(left>=8);assert.ok(left+width<=390-8);
  const root=f.menu.children[0];
  assert.ok(8+parseFloat(root.style.top)+root.offsetHeight<=720-8);
  assert.ok(8+parseFloat(root.style.top)+root.offsetHeight<=r.top-8);
});

test('home avoids a visible right sidebar when it leaves too little room beside the input',async()=>{
  const r={left:100,top:620,right:776,bottom:680,width:676,height:60};
  const side={left:864,top:100,right:1256,bottom:700,width:392,height:600};
  const f=fixture(.5,{width:1280,height:720,composerRect:r,sidebarRect:side});await tick();
  const state=f.ctx.window.NianxiangPet.getState(),bodyRight=state.x+300*440/640;
  assert.ok(bodyRight<=side.left-8);assert.ok(bodyRight<=r.right);
  assert.ok(state.y+169*335/360<r.top);
  f.hit.events.contextmenu({preventDefault(){}});
  for(const panel of f.menu.children)assert.ok(8+parseFloat(panel.style.top)+panel.offsetHeight<=r.top-8);
  f.menu.children[0].children.find(x=>x.textContent.startsWith('动作')).events.click();
  f.menu.children[1].children.find(x=>x.textContent.startsWith('玩耍')).events.click();
  for(const panel of f.menu.children)assert.ok(8+parseFloat(panel.style.top)+panel.offsetHeight<=r.top-8);
});

test('layout retries never override a position the user dragged',async()=>{
  const f=fixture(.5,{composerReady:false});await tick();const retry=[...f.timers.values()].find(x=>x.ms===500);
  const event={button:0,pointerId:1,pointerType:'mouse',clientX:300,clientY:350};f.hit.events.pointerdown(event);
  f.hit.events.pointermove({...event,clientX:320,preventDefault(){}});f.runFrame(1000);f.runFrame(1040);
  const dragged=f.ctx.window.NianxiangPet.getState();f.setComposerReady(true);retry.fn();
  const after=f.ctx.window.NianxiangPet.getState();assert.equal(after.x,dragged.x);assert.equal(after.y,dragged.y);
});

test('terminal work status holds its last frame until the ten-second timeout',async()=>{
  for(const [status,clip] of [['success','工作状态-雀跃庆祝'],['error','工作状态-垂头叹气冒汗']]){
    const f=fixture();await tick();f.ctx.window.NianxiangPet.setWork(status);await tick();
    const timer=[...f.timers.values()].find(x=>x.ms===10000);assert.ok(timer);
    const video=f.vid[f.ctx.window.NianxiangPet.getState().slot];video.onended();await tick();
    assert.equal(f.ctx.window.NianxiangPet.getState().work,status);
    assert.equal(f.ctx.window.NianxiangPet.getState().name,clip);
    timer.fn();await tick();
    assert.equal(f.ctx.window.NianxiangPet.getState().work,null);
    assert.equal(f.ctx.window.NianxiangPet.getState().name,inventory.idle[0]);
  }
});

test('an explicit menu action returns to nonterminal work when it ends',async()=>{
  const f=fixture(.5);await tick();f.ctx.window.NianxiangPet.setWork('thinking');await tick();
  f.hit.events.contextmenu({preventDefault(){}});f.menu.children[0].children.find(x=>x.textContent.startsWith('动作')).events.click();
  f.menu.children[1].children.find(x=>x.textContent.startsWith('玩耍')).events.click();
  f.menu.children[2].children[0].events.click();await tick();
  assert.equal(f.ctx.window.NianxiangPet.getState().name,'三球抛接');
  f.vid[f.ctx.window.NianxiangPet.getState().slot].onended();await tick();
  assert.equal(f.ctx.window.NianxiangPet.getState().name,'工作状态-思考冒泡');
  assert.equal(f.ctx.window.NianxiangPet.getState().kind,'work');
});

test('an explicit action returns to a terminal state until its original timeout',async()=>{
  const f=fixture();await tick();f.ctx.window.NianxiangPet.setWork('error');await tick();
  const timer=[...f.timers.values()].find(x=>x.ms===10000);
  await f.ctx.window.NianxiangPet.play(inventory.click[0]);
  f.vid[f.ctx.window.NianxiangPet.getState().slot].onended();await tick();
  assert.equal(f.ctx.window.NianxiangPet.getState().work,'error');
  assert.equal(f.ctx.window.NianxiangPet.getState().name,'工作状态-垂头叹气冒汗');
  timer.fn();await tick();
  assert.equal(f.ctx.window.NianxiangPet.getState().work,null);
  assert.equal(f.ctx.window.NianxiangPet.getState().name,inventory.idle[0]);
});

test('an explicit action ending under lock returns to terminal state only after unlock',async()=>{
  const f=fixture();await tick();f.ctx.window.NianxiangPet.setWork('error');await tick();
  const timer=[...f.timers.values()].find(x=>x.ms===10000);f.ctx.window.NianxiangPet.setLock(true);
  await f.ctx.window.NianxiangPet.play(inventory.click[0]);
  f.vid[f.ctx.window.NianxiangPet.getState().slot].onended();await tick();
  assert.equal(f.ctx.window.NianxiangPet.getState().name,inventory.click[0]);
  f.ctx.window.NianxiangPet.setLock(false);await tick();
  assert.equal(f.ctx.window.NianxiangPet.getState().name,'工作状态-垂头叹气冒汗');
  timer.fn();await tick();
  assert.equal(f.ctx.window.NianxiangPet.getState().work,null);
  assert.equal(f.ctx.window.NianxiangPet.getState().name,inventory.idle[0]);
});

test('terminal expiry while locked leaves animation paused until unlock',async()=>{
  const f=fixture();await tick();f.ctx.window.NianxiangPet.setWork('error');await tick();
  const timer=[...f.timers.values()].find(x=>x.ms===10000);
  f.ctx.window.NianxiangPet.setLock(true);
  timer.fn();await tick();assert.equal(f.ctx.window.NianxiangPet.getState().name,'工作状态-垂头叹气冒汗');
  f.ctx.window.NianxiangPet.setLock(false);await tick();
  assert.equal(f.ctx.window.NianxiangPet.getState().name,inventory.idle[0]);
});

test('closing a menu after terminal video ends keeps the final frame until expiry',async()=>{
  const f=fixture();await tick();f.ctx.window.NianxiangPet.setWork('error');await tick();
  const timer=[...f.timers.values()].find(x=>x.ms===10000);
  f.hit.events.contextmenu({preventDefault(){}});const video=f.vid[f.ctx.window.NianxiangPet.getState().slot];
  video.onended();f.listeners.keydown({key:'Escape'});await tick();
  assert.equal(f.ctx.window.NianxiangPet.getState().name,'工作状态-垂头叹气冒汗');
  assert.equal(f.ctx.window.NianxiangPet.getState().slot,1);
  timer.fn();await tick();assert.equal(f.ctx.window.NianxiangPet.getState().name,inventory.idle[0]);
});


test('menu chat is explicit, scoped to its request id, and consumes one reply',async()=>{
  const f=fixture();await tick();f.hit.events.contextmenu({preventDefault(){}});
  f.menu.children[0].children.find(x=>x.textContent.startsWith('工具')).events.click();
  f.menu.children[1].children.find(x=>x.textContent==='对话').events.click();
  assert.equal(f.isInputFocused(),true);assert.equal(f.dispatched.length,1);
  const id=f.dispatched[0].detail.requestId;assert.equal(f.ctx.window.NianxiangPet.isConversationRequested(id),true);
  assert.equal(f.ctx.window.NianxiangPet.showReply('旧回复',id+1),false);
  assert.equal(f.ctx.window.NianxiangPet.showReply('这是这一轮的回复',id),true);await tick();
  assert.equal(f.bubble.textContent,'这是这一轮的回复');
  assert.equal(f.ctx.window.NianxiangPet.showReply('重复',id),false);
});

test('terminal bubble holds a scoped reply until expiry and cancellation can remove it',async()=>{
  const f=fixture();await tick();f.hit.events.contextmenu({preventDefault(){}});
  f.menu.children[0].children.find(x=>x.textContent.startsWith('工具')).events.click();
  f.menu.children[1].children.find(x=>x.textContent==='对话').events.click();
  const id=f.dispatched[0].detail.requestId;f.ctx.window.NianxiangPet.say('任务完成',4);
  assert.equal(f.ctx.window.NianxiangPet.showReply('一'.repeat(121),id),true);
  assert.equal(f.bubble.textContent,'任务完成');
  let timer=[...f.timers.values()].find(x=>x.ms===10000);timer.fn();
  assert.equal(f.bubble.textContent,'一'.repeat(120)+'…');
  f.hit.events.contextmenu({preventDefault(){}});f.menu.children[0].children[0].events.click();
  f.menu.children[1].children.find(x=>x.textContent==='对话').events.click();
  const next=f.dispatched[1].detail.requestId;f.ctx.window.NianxiangPet.say('终态',4);
  assert.equal(f.ctx.window.NianxiangPet.showReply('不应出现',next),true);
  assert.equal(f.ctx.window.NianxiangPet.cancelConversation(next),true);
  timer=[...f.timers.values()].find(x=>x.ms===10000);timer.fn();
  assert.notEqual(f.bubble.textContent,'不应出现');
});

test('selecting a newer chat invalidates the previous request and pending reply',async()=>{
  const f=fixture();await tick();const open=()=>{f.hit.events.contextmenu({preventDefault(){}});f.menu.children[0].children[0].events.click();f.menu.children[1].children.find(x=>x.textContent==='对话').events.click()};
  open();const old=f.dispatched[0].detail.requestId;f.ctx.window.NianxiangPet.say('任务完成',4);
  assert.equal(f.ctx.window.NianxiangPet.showReply('旧内容',old),true);open();
  const next=f.dispatched[1].detail.requestId;assert.notEqual(old,next);
  assert.equal(f.ctx.window.NianxiangPet.showReply('迟到的旧内容',old),false);
  assert.equal(f.ctx.window.NianxiangPet.isConversationRequested(next),true);
  assert.equal(f.ctx.window.NianxiangPet.cancelConversation(old),false);
  assert.equal(f.ctx.window.NianxiangPet.isConversationRequested(next),true);
});


test('reduced motion freezes the automatic chain and still permits a user-selected action',async()=>{
  const f=fixture(.17,{reduceMotion:true});await tick();
  assert.equal(f.ctx.window.NianxiangPet.getState().kind,'still');assert.equal(f.vid[0].paused,true);assert.equal(f.rafs.size,0);
  f.hit.events.click();await tick();assert.equal(f.ctx.window.NianxiangPet.getState().kind,'click');
  assert.ok(inventory.click.includes(f.ctx.window.NianxiangPet.getState().name));
  f.vid[1].onended();await tick();assert.equal(f.ctx.window.NianxiangPet.getState().kind,'still');assert.equal(f.rafs.size,0);
});

test('changing the system motion preference stops automatic movement and restores the chain',async()=>{
  const f=fixture(.17);await tick();f.vid[0].onended();await tick();assert.equal(f.ctx.window.NianxiangPet.getState().kind,'move');
  f.setReduced(true);await tick();assert.equal(f.ctx.window.NianxiangPet.getState().movement,null);
  assert.equal(f.ctx.window.NianxiangPet.getState().kind,'still');assert.equal(f.rafs.size,0);
  f.setReduced(false);await tick();assert.equal(f.ctx.window.NianxiangPet.getState().kind,'idle');
});


test('scoped reply guard is rechecked when a queued bubble is ready to display',async()=>{
  const f=fixture();await tick();f.hit.events.contextmenu({preventDefault(){}});
  f.menu.children[0].children[0].events.click();f.menu.children[1].children.find(x=>x.textContent==='对话').events.click();
  const id=f.dispatched[0].detail.requestId;let current=true;
  f.ctx.window.NianxiangPet.say('任务完成',4);assert.equal(f.ctx.window.NianxiangPet.showReply('旧会话回复',id,()=>current),true);
  current=false;const timer=[...f.timers.values()].find(x=>x.ms===10000);timer.fn();
  assert.notEqual(f.bubble.textContent,'旧会话回复');assert.equal(f.bubble.hidden,true);
});

test('guard rejects an already stale reply immediately',async()=>{
  const f=fixture();await tick();f.hit.events.contextmenu({preventDefault(){}});
  f.menu.children[0].children[0].events.click();f.menu.children[1].children.find(x=>x.textContent==='对话').events.click();
  const id=f.dispatched[0].detail.requestId;
  assert.equal(f.ctx.window.NianxiangPet.showReply('旧回复',id,()=>false),false);
  assert.equal(f.ctx.window.NianxiangPet.isConversationRequested(id),false);
});


test('custom hover tooltip follows the cursor and flips at viewport edges',async()=>{
  const f=fixture();await tick();const tooltip=f.body.children[2];tooltip.offsetWidth=100;tooltip.offsetHeight=24;
  f.hit.events.pointerenter({pointerType:'mouse',clientX:895,clientY:698});
  assert.equal(tooltip.hidden,false);assert.equal(tooltip.textContent,'大肥鱼');
  assert.ok(parseFloat(tooltip.style.left)<795);assert.ok(parseFloat(tooltip.style.top)<674);
  f.hit.events.pointermove({pointerType:'mouse',clientX:100,clientY:100});
  assert.ok(parseFloat(tooltip.style.left)>100);assert.ok(parseFloat(tooltip.style.top)>100);
  f.hit.events.pointerleave();assert.equal(tooltip.hidden,true);
  f.hit.events.pointerenter({pointerType:'touch',clientX:20,clientY:20});assert.equal(tooltip.hidden,true);
});

function launchAndCatch(f){
  const start={button:0,pointerId:1,pointerType:'mouse',clientX:300,clientY:300};
  f.setTime(1000);f.hit.events.pointerdown(start);f.hit.events.pointerup(start);
  f.setTime(1100);f.hit.events.pointerdown(start);
  f.hit.events.pointermove({...start,clientX:400,preventDefault(){}});
  f.setTime(1110);f.hit.events.pointerup({...start,clientX:400});
  f.setTime(1120);f.hit.events.pointerdown({...start,clientX:380});
}

test('catching a fast flying pet shows a 2200ms score and transient particle burst',async()=>{
  const f=fixture();await tick();launchAndCatch(f);
  const card=f.body.children[3],burst=f.body.children[5];assert.equal(card.hidden,false);
  assert.match(card.children[0].textContent,/^\+\d+$/);assert.match(card.children[1].textContent,/速度/);
  assert.equal(burst.children.length,20);assert.equal(burst.className,'chat-pet-burst');
  assert.equal(f.ctx.window.NianxiangPet.getState().vx,0);
  const expiry=[...f.timers.values()].find(x=>x.ms===2200);assert.ok(expiry);expiry.fn();assert.equal(card.hidden,true);
  f.runFrame(2200);assert.equal(burst.removed,true);
});

test('reduced-motion catch retains a static score and skips particles',async()=>{
  const f=fixture();await tick();const start={button:0,pointerId:1,pointerType:'mouse',clientX:300,clientY:300};
  f.setTime(1000);f.hit.events.pointerdown(start);f.hit.events.pointerup(start);f.setTime(1100);f.hit.events.pointerdown(start);
  f.hit.events.pointermove({...start,clientX:400,preventDefault(){}});f.setTime(1110);f.hit.events.pointerup({...start,clientX:400});
  f.setReduced(true,false);f.setTime(1120);f.hit.events.pointerdown({...start,clientX:380});
  assert.equal(f.body.children[3].hidden,false);assert.equal(f.body.children.length,5);
});


test('display menu can hide the pet and restore it without blocking the composer',async()=>{
  const f=fixture();await tick();f.hit.events.contextmenu({preventDefault(){}});
  f.menu.children[0].children.find(x=>x.textContent.startsWith('工具')).events.click();
  f.menu.children[1].children.find(x=>x.textContent.startsWith('显示位置')).events.click();
  assert.equal(f.menu.children.length,3);f.menu.children[2].children.find(x=>x.textContent==='暂时收起').events.click();
  const restore=f.body.children[4];assert.equal(f.root.hidden,true);assert.equal(restore.hidden,false);
  assert.ok(parseFloat(restore.style.top)+restore.offsetHeight<620);
  restore.events.click();await tick();assert.equal(f.root.hidden,false);assert.equal(restore.hidden,true);
});

test('explicitly requested action can play while automatic chain is locked',async()=>{
  const f=fixture();await tick();f.ctx.window.NianxiangPet.setLock(true);
  await f.ctx.window.NianxiangPet.play(inventory.click[0]);
  assert.equal(f.ctx.window.NianxiangPet.getState().locked,true);assert.equal(f.ctx.window.NianxiangPet.getState().name,inventory.click[0]);
  assert.notEqual(f.vid[1].paused,true);f.vid[1].onended();await tick();
  assert.equal(f.ctx.window.NianxiangPet.getState().name,inventory.click[0]);
});

test('locking a flying pet stops its physics immediately',async()=>{
  const f=fixture();await tick();const point={button:0,pointerId:1,pointerType:'mouse',clientX:300,clientY:300};
  f.setTime(1000);f.hit.events.pointerdown(point);f.hit.events.pointerup(point);
  f.setTime(1100);f.hit.events.pointerdown(point);
  f.hit.events.pointermove({...point,clientX:400,preventDefault(){}});
  f.setTime(1110);f.hit.events.pointerup({...point,clientX:400});
  assert.notEqual(f.ctx.window.NianxiangPet.getState().vx,0);
  f.ctx.window.NianxiangPet.setLock(true);
  const before=f.ctx.window.NianxiangPet.getState();f.runFrame(1300);
  const after=f.ctx.window.NianxiangPet.getState();
  assert.equal(after.vx,0);assert.equal(after.vy,0);assert.equal(after.x,before.x);assert.equal(after.y,before.y);
});

test('unlocking resumes a work state received during the lock',async()=>{
  const f=fixture();await tick();f.ctx.window.NianxiangPet.setLock(true);
  f.ctx.window.NianxiangPet.setWork('thinking');await tick();
  assert.equal(f.ctx.window.NianxiangPet.getState().name,inventory.idle[0]);
  f.ctx.window.NianxiangPet.setLock(false);await tick();
  assert.equal(f.ctx.window.NianxiangPet.getState().name,'工作状态-思考冒泡');
  assert.equal(f.ctx.window.NianxiangPet.getState().kind,'work');
  f.vid[f.ctx.window.NianxiangPet.getState().slot].onended();await tick();
  assert.equal(f.ctx.window.NianxiangPet.getState().name,'工作状态-思考冒泡');
});


test('an explicitly selected move still moves while automatic actions are locked',async()=>{
  const f=fixture();await tick();f.ctx.window.NianxiangPet.setLock(true);
  f.hit.events.contextmenu({preventDefault(){}});f.menu.children[0].children.find(x=>x.textContent.startsWith('动作')).events.click();
  f.menu.children[1].children.find(x=>x.textContent.startsWith('移动')).events.click();
  const before=f.ctx.window.NianxiangPet.getState().x;f.menu.children[2].children[0].events.click();await tick();
  f.runFrame(6000);assert.notEqual(f.ctx.window.NianxiangPet.getState().x,before);
  assert.equal(f.ctx.window.NianxiangPet.setBalance(40),false);
});

test('balance menu reports only a supplied value and replays the correct tier even while locked',async()=>{
  const f=fixture();await tick();
  const openBalance=()=>{
    f.hit.events.contextmenu({preventDefault(){}});
    f.menu.children[0].children.find(x=>x.textContent.startsWith('工具')).events.click();
    f.menu.children[1].children.find(x=>x.textContent==='查看余额').events.click();
  };
  openBalance();assert.equal(f.bubble.textContent,'还没有可用的余额信息。');
  const clips=['余额-钱袋满溢','余额-金袋叮当','余额-钱袋如常','余额-数金皱眉','余额-袋空如洗','余额-分文不剩'];
  for(const [index,value] of [0,20,40,60,80,100].entries()){
    assert.equal(f.ctx.window.NianxiangPet.setBalance(value),true);await tick();
    assert.equal(f.ctx.window.NianxiangPet.getState().name,clips[index]);
  }
  assert.equal(f.ctx.window.NianxiangPet.setBalance(101),false);
  assert.equal(f.ctx.window.NianxiangPet.getState().balance,100);
  f.ctx.window.NianxiangPet.setLock(true);openBalance();await tick();
  assert.equal(f.bubble.textContent,'额度已使用 100%');
  assert.equal(f.ctx.window.NianxiangPet.getState().name,'余额-分文不剩');
  assert.equal(f.ctx.window.NianxiangPet.getState().locked,true);
});


test('a double-press slingshot consumes the pair instead of retriggering on a third press',async()=>{
  const f=fixture();await tick();const e={button:0,pointerId:1,pointerType:'mouse',clientX:300,clientY:300};
  f.setTime(1000);f.hit.events.pointerdown(e);f.hit.events.pointerup(e);
  f.setTime(1100);f.hit.events.pointerdown(e);f.hit.events.pointerup(e);
  f.setTime(1200);f.hit.events.pointerdown(e);f.setTime(1210);
  f.hit.events.pointermove({...e,clientX:400,preventDefault(){}});f.setTime(1220);f.hit.events.pointerup({...e,clientX:400});
  assert.equal(f.ctx.window.NianxiangPet.getState().vx,0);
});


test('manual whisper uses one local meme within its existing bubble',async()=>{
  const f=fixture(.5,{memeData:{available:true,memes:[{name:'大肥鱼开心',url:'/api/pet-memes/happy.png'}]}});await tick();
  f.hit.events.contextmenu({preventDefault(){}});f.menu.children[0].children[0].events.click();
  f.menu.children[1].children.find(x=>x.textContent==='碎碎念').events.click();await tick();
  assert.equal(f.bubble.hidden,false);assert.equal(f.bubble.children.length,1);
  const image=f.bubble.children[0];assert.equal(image.src,'/api/pet-memes/happy.png');assert.equal(image.alt,'大肥鱼表情：大肥鱼开心');
  f.ctx.window.NianxiangPet.say('任务完成',4);assert.equal(f.bubble.children.length,0);
});

test('whisper falls back to text when pictures are missing, invalid or cannot load',async()=>{
  const f=fixture(.5,{memeData:{available:true,memes:[{name:'外部',url:'https://example.test/a.png'},{name:'错路径',url:'/api/pet-assets/a.png'}]}});await tick();
  f.hit.events.contextmenu({preventDefault(){}});f.menu.children[0].children[0].events.click();
  f.menu.children[1].children.find(x=>x.textContent==='碎碎念').events.click();await tick();
  assert.equal(f.bubble.children.length,0);assert.ok(f.bubble.textContent);
  const g=fixture(.5,{memeData:{available:true,memes:[{name:'坏图',url:'/api/pet-memes/broken.png'}]}});await tick();
  g.hit.events.contextmenu({preventDefault(){}});g.menu.children[0].children[0].events.click();
  g.menu.children[1].children.find(x=>x.textContent==='碎碎念').events.click();await tick();
  const image=g.bubble.children[0];image.events.error();assert.equal(image.removed,true);assert.ok(g.bubble.textContent);
});

test('automatic whisper selects a local meme while respecting terminal bubble priority',async()=>{
  const f=fixture(.5,{reduceMotion:true,memeData:{available:true,memes:[{name:'图',url:'/api/pet-memes/a.png'}]}});await tick();
  const whisper=[...f.timers.values()].find(x=>x.ms===300000);assert.ok(whisper);whisper.fn();await tick();
  assert.equal(f.bubble.children[0].src,'/api/pet-memes/a.png');
  f.ctx.window.NianxiangPet.say('完成',4);whisper.fn();await tick();assert.equal(f.bubble.textContent,'完成');assert.equal(f.bubble.children.length,0);
});

test('manual and automatic whispers use generated text and fall back on failure',async()=>{
  const f=fixture(.5,{reduceMotion:true});await tick();let result='新鲜出炉的碎碎念';
  f.ctx.window.NianxiangPetWhisper={generate:async()=>result};
  f.hit.events.contextmenu({preventDefault(){}});f.menu.children[0].children[0].events.click();
  f.menu.children[1].children.find(x=>x.textContent==='碎碎念').events.click();await tick();
  assert.equal(f.bubble.textContent,'新鲜出炉的碎碎念');
  result='自动碎碎念';[...f.timers.values()].find(x=>x.ms===300000).fn();await tick();
  assert.equal(f.bubble.textContent,'自动碎碎念');
  f.ctx.window.NianxiangPetWhisper.generate=async()=>{throw new Error('offline')};
  [...f.timers.values()].find(x=>x.ms===300000).fn();await tick();
  assert.ok(f.bubble.textContent);assert.notEqual(f.bubble.textContent,'自动碎碎念');
});

test('late generated whispers cannot overwrite a newer interaction or status',async()=>{
  for(const change of [
    f=>f.ctx.window.NianxiangPet.say('新消息',2),
    f=>f.ctx.window.NianxiangPet.setWork('thinking'),
    f=>f.ctx.window.NianxiangPet.setLock(true),
    f=>f.listeners.pointerdown({target:{}}),
    f=>{f.doc.hidden=true;f.listeners.visibilitychange()},
    f=>{f.hit.events.contextmenu({preventDefault(){}});f.menu.children[0].children[0].events.click();f.menu.children[1].children.find(x=>x.textContent==='暂停动画').events.click()},
    f=>{f.hit.events.contextmenu({preventDefault(){}});f.menu.children[0].children[0].events.click();f.menu.children[1].children.find(x=>x.textContent.startsWith('显示位置')).events.click();f.menu.children[2].children.find(x=>x.textContent==='暂时收起').events.click()},
  ]){
    const f=fixture(.5,{reduceMotion:true});await tick();let resolve;
    f.ctx.window.NianxiangPetWhisper={generate:()=>new Promise(r=>{resolve=r})};
    [...f.timers.values()].find(x=>x.ms===300000).fn();await tick();
    change(f);const before=f.bubble.textContent;resolve('迟到的碎碎念');await tick();
    assert.notEqual(f.bubble.textContent,'迟到的碎碎念');assert.equal(f.bubble.textContent,before);
  }
});

test('a late whisper does not replace a bubble that expired during generation',async()=>{
  const f=fixture(.5,{reduceMotion:true});await tick();let resolve;
  f.ctx.window.NianxiangPet.say('先前气泡',2);
  const expiry=[...f.timers.values()].find(x=>x.ms===10000);
  f.ctx.window.NianxiangPetWhisper={generate:()=>new Promise(r=>{resolve=r})};
  [...f.timers.values()].find(x=>x.ms===300000).fn();await tick();
  expiry.fn();resolve('迟到的碎碎念');await tick();
  assert.equal(f.bubble.hidden,true);
});
