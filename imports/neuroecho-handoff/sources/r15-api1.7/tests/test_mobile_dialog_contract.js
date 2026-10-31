const connectionContext = require("./helpers/connection-context.cjs");
// Run the shipped H5 lifecycle with the shipped dialog helper, using synthetic DOM.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const helper=fs.readFileSync('web/companion-welcome.js','utf8'),mobile=fs.readFileSync('web/m.js','utf8');
class Events {
 constructor(){this.listeners=new Map();}
 addEventListener(type,fn){if(!this.listeners.has(type))this.listeners.set(type,new Set());this.listeners.get(type).add(fn);}
 removeEventListener(type,fn){this.listeners.get(type)?.delete(fn);}
 dispatch(type,values={}){const event={type,target:this,defaultPrevented:false,...values,preventDefault(){this.defaultPrevented=true;},stopPropagation(){}};for(const fn of [...(this.listeners.get(type)||[])])fn(event);return event;}
}
function setup(){
 const document=new Events(),nodes=new Map(),requests=[];
 class Element extends Events {
  constructor(id){super();this.id=id;this.attributes=new Map();this.children=[];this.inert=false;this.hidden=false;this.disabled=false;this.isConnected=true;this.value='';const classes=new Set();this.classList={add:(...xs)=>xs.forEach(x=>classes.add(x)),remove:(...xs)=>xs.forEach(x=>classes.delete(x)),contains:x=>classes.has(x)};}
  append(...items){for(const item of items){item.parentElement=this;this.children.push(item);}}
  getAttribute(key){return this.attributes.has(key)?this.attributes.get(key):null;}
  setAttribute(key,value){this.attributes.set(key,String(value));}
  removeAttribute(key){this.attributes.delete(key);}
  contains(item){return this===item||this.children.some(child=>child.contains(item));}
  closest(){for(let node=this;node;node=node.parentElement)if(node.inert||node.hidden||node.classList.contains('is-hidden'))return node;return null;}
  focus(){if(this.closest())return;document.activeElement=this;document.dispatch('focusin',{target:this});}
  querySelectorAll(){return this.children.flatMap(child=>[child,...child.querySelectorAll()]).filter(child=>child.control);}
  querySelector(){return this.querySelectorAll()[0]||null;}
 }
 const $=id=>{if(!nodes.has(id))nodes.set(id,new Element(id));return nodes.get(id);};
 const app=$('#m-app'),input=$('#m-input'),opener=$('#source-opener');app.append(opener,input);input.value='尚未发送的话';
 const wizard=$('#m-onboard'),wizardClose=$('#m-onboarding-return');wizardClose.control=true;wizard.append(wizardClose);wizard.classList.add('is-hidden');wizard.setAttribute('aria-hidden','true');
 const auth=$('#m-auth'),authClose=$('#m-auth-cancel');authClose.control=true;auth.append(authClose);auth.classList.add('is-hidden');auth.setAttribute('aria-hidden','true');
 const sheet=$('#m-sheet');sheet.classList.add('is-hidden');sheet.setAttribute('aria-hidden','true');
 const state={session:{id:'same-session'},messages:[]},window={};
 const context=connectionContext({document,window,$,$$:()=>[],state,wz:{},localStorage:{getItem(){return null;},setItem(){throw Error('generic dialog must not write welcome storage');}},
  clearMobileSourceForm:undefined,openMobileLocalFiles(){},openMobileReal(){},openMobileFeishu(){},showWz(){},closeSheet(){},toast(){},esc:String,
  api:(...args)=>{requests.push(args);throw Error('lifecycle must not access a source');},
  closeLarkAuthMobile(){context.finishAuth();}});
 vm.runInContext(helper,context);
 const from=mobile.indexOf('  let mobileOpeningEntry = '),to=mobile.indexOf('  const api = ',from);assert.ok(from>=0&&to>from);
 vm.runInContext('let mobileSourceFormEpoch=0;function clearMobileSourceForm(){mobileSourceFormEpoch++;}\n'+mobile.slice(from,to)+
  '\nthis.entry=openMobileEntry;this.closeWizard=closeMobileWizard;this.beginAuth=beginMobileAuthSurface;this.finishAuth=finishMobileAuthSurface;this.invalidate=clearMobileSourceForm;',context);
 opener.focus();return{context,document,$,state,requests,app,input,opener,wizard,wizardClose,auth,authClose,sheet};
}
test('H5 wizard exposes exactly one dialog, traps focus, and Escape restores chat and draft',async()=>{
 const e=setup();await e.context.entry('local_files',e.opener);
 assert.equal(e.wizard.getAttribute('aria-hidden'),'false');assert.equal(e.app.inert,true);assert.equal(e.app.getAttribute('aria-hidden'),'true');assert.equal(e.document.activeElement,e.wizardClose);
 e.input.focus();assert.equal(e.document.activeElement,e.wizardClose);
 const escaped=e.document.dispatch('keydown',{key:'Escape'});assert.equal(escaped.defaultPrevented,true);
 assert.equal(e.wizard.getAttribute('aria-hidden'),'true');assert.equal(e.wizard.classList.contains('is-hidden'),true);assert.equal(e.app.inert,false);assert.equal(e.app.getAttribute('aria-hidden'),null);assert.equal(e.document.activeElement,e.opener);
 assert.equal(e.input.value,'尚未发送的话');assert.equal(e.state.session.id,'same-session');assert.equal(e.requests.length,0);
});
test('H5 auth suspends the real wizard trap; Escape closes auth and restores only its source dialog',async()=>{
 const e=setup();await e.context.entry('local_files',e.opener);e.context.beginAuth();
 assert.equal(e.wizard.getAttribute('aria-hidden'),'true');assert.equal(e.auth.getAttribute('aria-hidden'),'false');assert.equal(e.document.activeElement,e.authClose);assert.equal(e.app.inert,true);
 const tab=e.document.dispatch('keydown',{key:'Tab'});assert.equal(tab.defaultPrevented,true);assert.equal(e.document.activeElement,e.authClose);
 e.document.dispatch('keydown',{key:'Escape'});
 assert.equal(e.auth.getAttribute('aria-hidden'),'true');assert.equal(e.wizard.getAttribute('aria-hidden'),'false');assert.equal(e.document.activeElement,e.wizardClose);assert.equal(e.app.inert,true);assert.equal(e.input.value,'尚未发送的话');
 e.context.closeWizard();assert.equal(e.app.inert,false);assert.equal(e.app.getAttribute('aria-hidden'),null);assert.equal(e.sheet.getAttribute('aria-hidden'),'true');assert.equal(e.requests.length,0);
});
test('H5 auth cannot restore an abandoned source context and leaves no keyboard or inert trap',async()=>{
 for(const change of ['session','epoch']){
  const e=setup();await e.context.entry('local_files',e.opener);e.context.beginAuth();
  if(change==='session')e.state.session={id:'other-session'};else e.context.invalidate();
  assert.equal(e.context.finishAuth(),false);assert.equal(e.auth.getAttribute('aria-hidden'),'true');assert.equal(e.wizard.getAttribute('aria-hidden'),'true');assert.equal(e.app.inert,false);
  assert.equal(e.document.dispatch('keydown',{key:'Tab'}).defaultPrevented,false);e.input.focus();assert.equal(e.document.activeElement,e.input);assert.equal(e.input.value,'尚未发送的话');assert.equal(e.requests.length,0);
 }
});

test('a successful source connection closes its originating settings sheet and dialog, releases focus traps and returns to the preserved chat draft',async()=>{
 const e=setup(),settings=e.$('#m-settings-connect');settings.control=true;e.sheet.append(settings);e.sheet.classList.remove('is-hidden');e.sheet._xinjiKind='settings';settings.focus();
 await e.context.entry('apple_calendar',settings);assert.equal(e.wizard.getAttribute('aria-hidden'),'false');assert.equal(e.app.inert,true);assert.equal(e.sheet.inert,true);
 Object.assign(e.context,{pairedDevicesPanel:null,followups:{stop(){}},renderAll(){},loadEngine(){},loadNextStep(){},renderStarters(){},closeLarkAuthMobile(){},localStorage:{setItem(){}}});
 const begin=mobile.indexOf('  function enterSessionData('),end=mobile.indexOf('  async function startSession(',begin);
 const closeStart=mobile.indexOf('  function closeSheet()'),closeEnd=mobile.indexOf('  async function showMemoryContextNotice()',closeStart);
 vm.runInContext(mobile.slice(begin,end)+mobile.slice(closeStart,closeEnd)+'\nthis.acceptConnection=enterSessionData;',e.context);
 e.context.acceptConnection({session:{id:'same-session'},messages:[{id:'real-intro',role:'assistant',text:'已读取的合成边界回复'}],memories:[],context:{sources:[{id:'source',connector_id:'apple_reminders'}]}});
 assert.equal(e.wizard.classList.contains('is-hidden'),true);assert.equal(e.sheet.classList.contains('is-hidden'),true);assert.equal(e.sheet._xinjiKind,null);assert.equal(e.app.inert,false);assert.equal(e.sheet.inert,false);assert.equal(e.app.getAttribute('aria-hidden'),null);assert.equal(e.document.activeElement,e.input);assert.equal(e.input.value,'尚未发送的话');assert.equal(e.state.session.id,'same-session');assert.equal(e.requests.length,0);
 assert.equal(e.document.dispatch('keydown',{key:'Tab'}).defaultPrevented,false);
});
