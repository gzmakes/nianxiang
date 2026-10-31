const connectionContext = require("./helpers/connection-context.cjs");
// Re-entering the source directory must bind usable buttons for the new review.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/m.js','utf8');
function clip(a,b){const i=source.indexOf(a),j=source.indexOf(b,i);assert.ok(i>=0&&j>i);return source.slice(i,j);}
function setup(){
 const nodes=new Map(),calls=[],opened=[];let currentButton;
 const $=id=>{if(!nodes.has(id)){const classes=new Set();nodes.set(id,{innerHTML:'',textContent:'',value:'',classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x),toggle:(x,on)=>on?classes.add(x):classes.delete(x)},querySelectorAll:selector=>selector==='[data-real]'?[currentButton]:[]});}return nodes.get(id);};
 const state={session:{id:'canonical'},messages:[{id:'user',text:'持续的对话'}]},ctx=connectionContext({$,state,wz:{},esc:String,openMobileWizard(){},
  openMobileReal:(...args)=>opened.push(args),api:async(path,opts)=>{calls.push({path,opts});if(path.startsWith('/api/lark/account?'))return{enabled:false,ready:true};currentButton={dataset:{real:'local_files'}};return{sources:[{id:'local_files',name:'本机资料',status:'ready',blurb:'只选需要的文件',icon:'⌂'}]};}});
 vm.runInContext('let mobileSourceFormEpoch=0,mobileOpeningEntry=0;'+clip('  function clearMobileSourceForm()', '  async function openMobileReal(')+
  clip('  async function showMobileOnboarding()', '  async function boot()')+
  source.split('\n').find(line=>line.includes('$("#m-back-2").onclick = '))+
  '\nthis.open=showMobileOnboarding;this.step=showWz;',ctx);
 $('#m-input').value='未发送草稿';return{ctx,$,state,calls,opened,get button(){return currentButton;}};
}
test('the H5 source directory checks real metadata without reading contents, sending, or creating a new conversation',async()=>{
 const e=setup();await e.ctx.open();assert.equal(e.calls.length,2);assert.equal(e.calls[0].path,'/api/onboarding/sources?force=1');assert.equal(e.calls[0].opts?.method,undefined);assert.equal(e.calls[1].path,'/api/lark/account?session_id=canonical');assert.ok(e.calls.every(call=>!call.opts?.method||call.opts.method==='GET'));assert.equal(e.opened.length,0);assert.equal(e.state.session.id,'canonical');assert.equal(e.$('#m-input').value,'未发送草稿');
 e.button.onclick();assert.equal(e.opened[0][0],'local_files');assert.equal(e.calls.length,2);
});
test('returning from a source detail refreshes the directory and leaves its new buttons usable',async()=>{
 const e=setup();await e.ctx.open();const old=e.button;e.ctx.step(3);assert.equal(e.$('#m-wz-2').classList.contains('is-hidden'),true);
 assert.equal(typeof e.$('#m-back-2').onclick,'function');await e.$('#m-back-2').onclick();assert.equal(e.calls.length,4);assert.equal(e.$('#m-wz-2').classList.contains('is-hidden'),false);
 old.onclick();assert.equal(e.opened.length,0);e.button.onclick();assert.equal(e.opened.length,1);assert.equal(e.opened[0][0],'local_files');assert.equal(e.$('#m-input').value,'未发送草稿');
});
