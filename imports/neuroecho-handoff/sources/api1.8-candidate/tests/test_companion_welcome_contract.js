// Public dialog contract: keyboard access, background restoration and no data loss.
// The DOM harness models observable focus/inert behavior; no product function is copied.
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const helper = fs.readFileSync('web/companion-welcome.js', 'utf8');

class Events {
  constructor() { this.listeners = new Map(); }
  addEventListener(type, handler) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type).add(handler);
  }
  removeEventListener(type, handler) { this.listeners.get(type)?.delete(handler); }
  dispatch(type, values = {}) {
    const event = {type, target: this, defaultPrevented: false, ...values,
      preventDefault() { this.defaultPrevented = true; }, stopPropagation() {}};
    if (typeof this['on'+type] === 'function') this['on'+type](event);
    for (const handler of [...(this.listeners.get(type) || [])]) handler(event);
    return event;
  }
}

function environment({onPrimary, storage: customStorage, storageKey='welcome-test'} = {}) {
  const document = new Events(), window = new Events();
  class Element extends Events {
    constructor(name) {
      super(); this.name=name; this.attributes=new Map(); this.children=[];
      this.style={}; this.inert=false; this.hidden=false; this.disabled=false;
      this.isConnected=true; this.tabIndex=0; this.value='';
      const classes=new Set();
      this.classList={add:(...xs)=>xs.forEach(x=>classes.add(x)),remove:(...xs)=>xs.forEach(x=>classes.delete(x)),
        contains:x=>classes.has(x),toggle:(x,force)=>{const next=force ?? !classes.has(x); next?classes.add(x):classes.delete(x);return next;}};
    }
    setAttribute(key,value) { this.attributes.set(key,String(value)); }
    getAttribute(key) { return this.attributes.has(key)?this.attributes.get(key):null; }
    hasAttribute(key) { return this.attributes.has(key); }
    removeAttribute(key) { this.attributes.delete(key); }
    append(...children) { for(const child of children){child.parentElement=this;this.children.push(child);} }
    contains(child) { return this===child || this.children.some(x=>x.contains(child)); }
    closest() {
      for(let parent=this;parent;parent=parent.parentElement)
        if(parent.hidden||parent.inert||parent.classList.contains('is-hidden')) return parent;
      return null;
    }
    visible() { return this.isConnected&&!this.hidden&&!this.classList.contains('is-hidden')&&(!this.parentElement||this.parentElement.visible()); }
    getClientRects() { return this.visible()?[{width:1,height:1}]:[]; }
    focus() {
      for(let parent=this;parent;parent=parent.parentElement) if(parent.inert) return;
      if(this.visible()&&!this.disabled) document.activeElement=this;
    }
    querySelectorAll() { return this.children.flatMap(child=>[child,...child.querySelectorAll()]); }
    querySelector() { return this.querySelectorAll()[0]||null; }
  }
  document.body=new Element('body');document.body.style.overflow='auto';document.documentElement=document.body;
  const app=new Element('app'),alreadyInert=new Element('another-dialog-background');
  alreadyInert.inert=true;alreadyInert.setAttribute('aria-hidden','true');
  const opener=new Element('welcome-opener'),composer=new Element('composer');composer.value='还没有发送的心事';
  app.append(opener,composer);
  const dialog=new Element('welcome');dialog.classList.add('is-hidden');dialog.setAttribute('aria-hidden','true');
  const closeButton=new Element('close'),primary=new Element('primary');dialog.append(closeButton,primary);
  document.body.append(app,alreadyInert,dialog);opener.focus();
  const storage=new Map(), requests=[];
  const localStorage={getItem:key=>storage.has(key)?storage.get(key):null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
  const session={id:'existing-session'}, message={id:'user-draft'};
  let closed=0;
  const context=vm.createContext({window,document,localStorage,HTMLElement:Element,
    getComputedStyle:element=>({display:element.visible()?'block':'none',visibility:'visible'}),
    requestAnimationFrame:callback=>{callback();return 1;},cancelAnimationFrame(){},setTimeout,clearTimeout,
    fetch:(...args)=>{requests.push(args);throw Error('dialog must not read private sources');}});
  window.localStorage=localStorage;vm.runInContext(helper,context);
  const welcome=window.XinjiWelcome.create({dialog,openers:[opener],closeButtons:[closeButton],primaryButton:primary,
    backgrounds:[app,alreadyInert],version:'contract-v1',storageKey,storage:customStorage,fallbackFocus:composer,
    onPrimary:()=>onPrimary?.({welcome,app,composer,session,message}),onClose:()=>closed++});
  return {welcome,dialog,app,alreadyInert,opener,composer,primary,closeButton,document,window,storage,requests,session,message,
    get closed(){return closed;}};
}

test('first empty conversation can welcome once; manual reopen preserves session and draft and reads nothing',()=>{
  const env=environment();
  env.welcome.maybeShow({messages:[{role:'assistant',text:'你好'}]});
  assert.equal(env.welcome.isOpen(),true);assert.equal(env.app.inert,true);
  assert.equal(env.dialog.classList.contains('is-hidden'),false);
  assert.equal(env.dialog.getAttribute('aria-hidden'),'false');
  env.welcome.close();assert.equal(env.welcome.isOpen(),false);
  assert.equal(env.dialog.classList.contains('is-hidden'),true);
  assert.equal(env.dialog.getAttribute('aria-hidden'),'true');
  env.welcome.maybeShow({messages:[]});assert.equal(env.welcome.isOpen(),false);
  env.welcome.open();assert.equal(env.welcome.isOpen(),true);
  assert.equal(env.session.id,'existing-session');assert.equal(env.composer.value,'还没有发送的心事');
  assert.equal(env.requests.length,0);
});

test('restoring an existing user conversation never forces the welcome dialog',()=>{
  const env=environment();env.welcome.maybeShow({messages:[{role:'user',text:'已有的经历'}]});
  assert.equal(env.welcome.isOpen(),false);assert.equal(env.app.inert,false);
  assert.equal(env.composer.value,'还没有发送的心事');
});

test('Escape restores original inert and aria states even after repeated open',()=>{
  const env=environment();const ariaBefore=env.app.getAttribute('aria-hidden');
  env.welcome.open();env.welcome.open();
  env.document.dispatch('keydown',{key:'Escape'});
  assert.equal(env.welcome.isOpen(),false);assert.equal(env.app.inert,false);
  assert.equal(env.app.getAttribute('aria-hidden'),ariaBefore);
  assert.equal(env.alreadyInert.inert,true);assert.equal(env.alreadyInert.getAttribute('aria-hidden'),'true');
  assert.equal(env.document.activeElement,env.opener);assert.equal(env.closed,1);
});

test('primary action restores background before focusing the existing composer',()=>{
  let invoked=0;
  const env=environment({onPrimary:({welcome,app,composer})=>{
    invoked++;assert.equal(welcome.isOpen(),false);assert.equal(app.inert,false);composer.focus();
  }});
  env.welcome.open();env.primary.dispatch('click');
  assert.equal(invoked,1);assert.equal(env.document.activeElement,env.composer);
  assert.equal(env.composer.value,'还没有发送的心事');assert.equal(env.requests.length,0);
});

test('Tab loops inside an open dialog, then stops trapping when closed',()=>{
  const env=environment();env.welcome.open();env.primary.focus();
  const next=env.document.dispatch('keydown',{key:'Tab',shiftKey:false});
  assert.equal(next.defaultPrevented,true);assert.equal(env.document.activeElement,env.closeButton);
  const previous=env.document.dispatch('keydown',{key:'Tab',shiftKey:true});
  assert.equal(previous.defaultPrevented,true);assert.equal(env.document.activeElement,env.primary);
  env.welcome.close();const outside=env.document.dispatch('keydown',{key:'Tab'});
  assert.equal(outside.defaultPrevented,false);
});

test('native dialog focus loss does not dismiss the welcome and detach traps',()=>{
  const env=environment();env.welcome.open();env.window.dispatch('blur');env.document.dispatch('visibilitychange');
  assert.equal(env.welcome.isOpen(),true);assert.equal(env.app.inert,true);
  env.welcome.close();assert.equal(env.app.inert,false);
});

test('closing after opener disappears focuses the visible composer instead of a hidden control',()=>{
  const env=environment();env.welcome.open();env.opener.isConnected=false;
  env.welcome.close();assert.equal(env.document.activeElement,env.composer);
  assert.equal(env.composer.value,'还没有发送的心事');
});

test('a generic source wizard restores background without writing welcome dismissal state',()=>{
  const env=environment({storageKey:null});env.welcome.open();env.welcome.close();
  assert.equal(env.storage.size,0);assert.equal(env.app.inert,false);
  env.welcome.open();env.document.dispatch('keydown',{key:'Escape'});
  assert.equal(env.storage.size,0);assert.equal(env.welcome.isOpen(),false);
});

test('unavailable browser storage cannot trap or repeatedly force a first welcome',()=>{
  const env=environment({storage:{getItem(){throw Error('storage unavailable')},setItem(){throw Error('storage unavailable')}}});
  assert.doesNotThrow(()=>env.welcome.maybeShow({messages:[]}));
  env.welcome.close();assert.equal(env.app.inert,false);
  assert.equal(env.welcome.maybeShow({messages:[]}),false);
  env.welcome.open();assert.equal(env.welcome.isOpen(),true);
});
