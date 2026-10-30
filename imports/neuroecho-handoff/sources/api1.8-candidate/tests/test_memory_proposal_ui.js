const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('web/memory-proposal.js', 'utf8');
function node(){return {className:'', textContent:'', style:{}, disabled:false, children:[], classList:{add(){},remove(){}}, replaceChildren(...x){this.children=x}}}
function setup(savedPreference = "on") {
 const box=node(), toggle=node(), state={session:{id:'s'}, messages:Array.from({length:3},()=>({role:'user'})),memories:[]}, calls=[];
 const storage=new Map();if(savedPreference!==null)storage.set("xinji_memory_proposals",savedPreference);const context={window:{},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},document:{createElement:()=>node()},Map,Set};vm.runInNewContext(source,context);
 const proposal=context.window.createMemoryProposal({box,toggle,state,api:async(p,o)=>{calls.push([p,o]);return p.startsWith('/api/memory?')?{memories:[{id:'mem'}]}:{id:'mem',kind:'fact',text:'我平时喜欢喝水',source:'对话原话 · 用户选存',status:'confirmed',source_message_id:JSON.parse(o.body).message_id}},toast(){},refresh(){}});
 return {box,toggle,state,calls,proposal};
}
test('explicit save only, ignored quote not offered again, can disable',async()=>{
 const {box,toggle,state,calls,proposal}=setup();assert.equal(proposal.shouldRequest('s'),true);
 const event={memory_proposal:{quote:'我平时喜欢喝红茶',message_id:'m'}};proposal.offer('s',event);
 assert.equal(calls.length,0);assert.equal(box.children[1].textContent,event.memory_proposal.quote);
 box.children[4].onclick();state.messages.push(...Array.from({length:8},()=>({role:'user'})));proposal.offer('s',event);assert.equal(box.children.length,0);
 proposal.offer('s',{memory_proposal:{quote:'我平时喜欢喝水',message_id:'m2'}});await box.children[3].onclick();
 assert.equal(calls[0][0],'/api/memory/proposal');assert.equal(JSON.parse(calls[0][1].body).message_id,'m2');assert.equal(state.memories.length,1);
 toggle.checked=false;toggle.onchange();assert.equal(proposal.shouldRequest('s'),false);
});
test('session switch clears unsaved proposal and prevents save',()=>{
 const {box,state,calls,proposal}=setup();proposal.offer('s',{memory_proposal:{quote:'我平时喜欢喝红茶',message_id:'m'}});const oldSave=box.children[3];
 state.session={id:'new'};proposal.sync();oldSave.onclick();assert.equal(calls.length,0);assert.equal(box.children.length,0);
});

test('new devices start with proposals off while existing explicit preferences stay intact',()=>{
 assert.equal(setup(null).proposal.shouldRequest('s'),false);assert.equal(setup('off').proposal.shouldRequest('s'),false);assert.equal(setup('on').proposal.shouldRequest('s'),true);
});
