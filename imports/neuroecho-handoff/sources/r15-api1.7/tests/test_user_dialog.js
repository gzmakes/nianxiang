const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function fixture(nested=false){
 const dialogs=[];let focused=null;
 function element(){return {hidden:false,value:'',textContent:'',attrs:{},listeners:{},isConnected:true,classList:{toggle(){}},setAttribute(k,v){this.attrs[k]=v},addEventListener(k,v){this.listeners[k]=v},focus(){focused=this},closest(){return null},remove(){this.isConnected=false}};}
 const source=element();source.appendChild=d=>{dialogs.push(d);d.isConnected=true};
 const previous=element();previous.closest=selector=>selector.includes('role=')&&nested?source:null;
 const body=element();body.appendChild=d=>dialogs.push(d);
 const document={activeElement:previous,body,createElement(){const d=element();const nodes={};for(const key of ['h2','p','textarea','label','[data-confirm]','[data-cancel]','form'])nodes[key]=element();nodes.label.querySelector=()=>element();d.querySelector=s=>nodes[s];d.showModal=()=>{d.open=true};d.close=()=>{d.open=false};d.nodes=nodes;return d;}};
 const context={window:{},document,Promise};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/user-dialog.js'),'utf8'),context);
 return {ui:context.window.XinjiDialogs,dialogs,previous,get focused(){return focused}};
}
const tick=async()=>{await Promise.resolve();await Promise.resolve();};
const event=()=>({preventDefault(){},stopImmediatePropagation(){}});
test('prompt preserves plain text and submits without a native window.prompt',async()=>{
 const f=fixture();const p=f.ui.prompt({title:'<b>title</b>',value:'<script>data</script>'});await tick();const d=f.dialogs[0];
 assert.equal(d.nodes.h2.textContent,'<b>title</b>');assert.equal(d.nodes.textarea.value,'<script>data</script>');assert.equal(d.innerHTML.includes('<script>'),false);
 d.nodes.textarea.value='改后的原话';d.nodes.form.listeners.submit(event());assert.equal(await p,'改后的原话');assert.equal(f.focused,f.previous);
});
test('cancel and Escape return null or false, never a destructive acceptance',async()=>{
 const f=fixture();const prompt=f.ui.prompt({value:'keep'});await tick();f.dialogs[0].listeners.keydown({...event(),key:'Escape'});assert.equal(await prompt,null);
 const confirm=f.ui.confirm({danger:true});await tick();const d=f.dialogs[1];assert.equal(f.focused,d.nodes['[data-cancel]']);d.nodes['[data-cancel]'].listeners.click();assert.equal(await confirm,false);
});
test('dialogs queue and attach inside the active source dialog',async()=>{
 const f=fixture(true);const a=f.ui.confirm({title:'one'}),b=f.ui.prompt({title:'two'});await tick();assert.equal(f.dialogs.length,1);
 f.dialogs[0].nodes.form.listeners.submit(event());assert.equal(await a,true);await tick();assert.equal(f.dialogs.length,2);
 f.dialogs[1].nodes['[data-cancel]'].listeners.click();assert.equal(await b,null);
});
