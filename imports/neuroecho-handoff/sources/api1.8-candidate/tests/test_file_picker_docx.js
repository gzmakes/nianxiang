const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
function node(){return {children:[],value:'',disabled:false,textContent:'',files:[],appendChild(x){this.children.push(x)},replaceChildren(){this.children=[]},setAttribute(){}};}
function setup(fetch){
 const input=node(),previews=node(),hint=node(),button=node(),calls=[];
 const container={innerHTML:'',querySelector:s=>({'input':input,'.file-previews':previews,'.file-hint':hint,'.file-confirm':button}[s])};
 const context={window:{},document:{createElement:node},TextDecoder,Uint8Array,Array,Error,fetch,btoa:s=>Buffer.from(s,'binary').toString('base64')};
 vm.runInNewContext(fs.readFileSync('web/file-picker.js','utf8'),context);
 context.window.XinjiFilePicker.mount(container,{sessionId:'one',onConfirm:async(files,sid)=>calls.push({files,sid})});
 return {input,previews,hint,button,calls};
}
function word(name='合成.docx'){const b=Uint8Array.from([80,75,3,4]);return {name,size:b.length,arrayBuffer:async()=>b.buffer};}
test('selected Word is locally previewed, then attached only after explicit confirmation',async()=>{
 const requests=[];const ui=setup(async(url,opt)=>{requests.push({url,body:JSON.parse(opt.body)});return {ok:true,json:async()=>({name:'合成.docx',text:'合成正文',truncated:false})}});
 ui.input.files=[word()];await ui.input.onchange();
 assert.equal(requests[0].url,'/api/local-files/preview-document');assert.equal(requests[0].body.data,'UEsDBA==');
 assert.equal(ui.previews.children[0].children[1].value,'合成正文');assert.equal(ui.calls.length,0);
 await ui.button.onclick();assert.equal(ui.calls[0].sid,'one');
 assert.deepEqual(JSON.parse(JSON.stringify(ui.calls[0].files)),[{name:'合成.docx',text:'合成正文'}]);
});
test('failed or mismatched Word previews cannot be confirmed',async()=>{
 for(const reply of [{ok:false,json:async()=>({detail:'没有正文'})},{ok:true,json:async()=>({name:'其他.docx',text:'bad',truncated:false})}]){
  const ui=setup(async()=>reply);ui.input.files=[word()];await ui.input.onchange();assert.equal(ui.button.disabled,true);await ui.button.onclick();assert.equal(ui.calls.length,0);
 }
});
test('a late Word preview cannot replace a newer file selection',async()=>{
 let resolve;
 const ui=setup(()=>new Promise(r=>resolve=r));
 ui.input.files=[word()];const old=ui.input.onchange();
 await new Promise(r=>setImmediate(r));
 const bytes=new TextEncoder().encode('新的资料');ui.input.files=[{name:'新的.txt',size:bytes.length,arrayBuffer:async()=>bytes.buffer}];
 await ui.input.onchange();resolve({ok:true,json:async()=>({name:'合成.docx',text:'旧预览',truncated:false})});await old;
 assert.equal(ui.previews.children[0].children[1].value,'新的资料');await ui.button.onclick();
 assert.equal(ui.calls[0].files[0].name,'新的.txt');
});
