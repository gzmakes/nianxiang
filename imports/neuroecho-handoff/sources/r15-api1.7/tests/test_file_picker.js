const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
function node() {return {children:[],textContent:'',value:'',disabled:false,files:[],appendChild(x){this.children.push(x)},replaceChildren(){this.children=[]},setAttribute(){}};}
function setup(options={}) {
  const input=node(), previews=node(), hint=node(), button=node(), container={innerHTML:'',querySelector(s){return {'input':input,'.file-previews':previews,'.file-hint':hint,'.file-confirm':button}[s]}};
  const window={}, document={createElement:()=>node()}, calls=[];
  const ctx=vm.createContext({window,document,TextDecoder,Array,Error});
  vm.runInContext(fs.readFileSync('web/file-picker.js','utf8'),ctx);
  window.XinjiFilePicker.mount(container,{sessionId:'existing',...options,onConfirm:async(files,sid)=>calls.push({files,sid})});
  return {input,previews,hint,button,calls,container};
}
const enc = new TextEncoder();
function file(name,text,size) {const bytes=enc.encode(text);return {name,size:size ?? bytes.length,arrayBuffer:async()=>bytes.buffer};}

test('only selected synthetic files are read, previewed fully, then sent on confirmation', async()=>{
  const t=setup();let reads=0;
  const a=file('a.txt','合成资料'), b=file('b.md','第二段合成内容');
  const wrapped={...a,arrayBuffer:async()=>{reads++;return a.arrayBuffer()}};
  t.input.files=[wrapped,b];await t.input.onchange();
  assert.equal(reads,1); assert.equal(t.calls.length,0); assert.equal(t.previews.children[0].children[1].value,'合成资料');
  await t.button.onclick();assert.equal(t.calls.length,1);assert.equal(t.calls[0].sid,'existing');
  assert.deepEqual(JSON.parse(JSON.stringify(t.calls[0].files)),[{name:'a.txt',text:'合成资料'},{name:'b.md',text:'第二段合成内容'}]);
});

test('limits and invalid content reject before confirmation',async()=>{
 for(const files of [[file('a.exe','a')],[file('a.txt','a',262145)],[file('a.txt','a'),file('b.txt','b'),file('c.txt','c'),file('d.txt','d')],[file('a.txt','a\0b')]]){
   const t=setup();t.input.files=files;await t.input.onchange();assert.equal(t.button.disabled,true);await t.button.onclick();assert.equal(t.calls.length,0);
 }
});

test('long files preview and send exactly the retained prefix',async()=>{
 const t=setup();t.input.files=[file('long.txt','x'.repeat(5000))];await t.input.onchange();assert.equal(t.previews.children[0].children[1].value.length,4000);
 assert.match(t.previews.children[0].children[0].textContent,/仅前 4000/);await t.button.onclick();assert.equal(t.calls[0].files[0].text.length,4000);
});

test('an emoji at Unicode position 4000 stays intact and is not marked truncated',async()=>{
 const text='x'.repeat(3999)+'😀',t=setup();t.input.files=[file('emoji-boundary.txt',text)];await t.input.onchange();
 assert.equal(t.previews.children[0].children[1].value,text);assert.match(t.previews.children[0].children[0].textContent,/完整内容/);
 await t.button.onclick();assert.equal(t.calls[0].files[0].text,text);assert.equal(Array.from(t.calls[0].files[0].text).length,4000);
 assert.equal(new TextDecoder('utf-8',{fatal:true}).decode(enc.encode(t.calls[0].files[0].text)),text);
});

test('an emoji after Unicode position 4000 is omitted and marked truncated',async()=>{
 const retained='x'.repeat(4000),t=setup();t.input.files=[file('emoji-after-limit.txt',retained+'😀')];await t.input.onchange();
 assert.equal(t.previews.children[0].children[1].value,retained);assert.match(t.previews.children[0].children[0].textContent,/仅前 4000/);
 await t.button.onclick();assert.equal(t.calls[0].files[0].text,retained);
});

test('Chinese text uses the same Unicode prefix for preview and confirmed payload',async()=>{
 const retained='中'.repeat(3999)+'文',t=setup();t.input.files=[file('中文.txt',retained+'字')];await t.input.onchange();
 assert.equal(t.previews.children[0].children[1].value,retained);assert.match(t.previews.children[0].children[0].textContent,/仅前 4000/);
 await t.button.onclick();assert.equal(t.calls[0].files[0].text,retained);
});

test('empty and whitespace-only input never creates a confirmable preview',async()=>{
 for(const text of ['', ' \n\t']){const t=setup();t.input.files=[file('empty.txt',text)];await t.input.onchange();
  assert.equal(t.button.disabled,true);assert.equal(t.previews.children.length,0);await t.button.onclick();assert.equal(t.calls.length,0);
 }
});

test('failed request with unknown outcome cannot be resubmitted automatically',async()=>{
 const t=setup();let calls=0;const ctx=vm.createContext({window:{},document:{createElement:()=>node()},TextDecoder,Array,Error});vm.runInContext(fs.readFileSync('web/file-picker.js','utf8'),ctx);
 ctx.window.XinjiFilePicker.mount(t.container,{sessionId:'s',onConfirm:async()=>{calls++;throw Error('connection lost')}});
 t.input.files=[file('a.txt','hello')];await t.input.onchange();await t.button.onclick();assert.equal(t.button.disabled,true);await t.button.onclick();assert.equal(calls,1);assert.match(t.hint.textContent,/结果未确认/);
});

// The system file chooser is the explicit final selection for the compact flow.
test('compact file selection attaches once without a second confirmation and preserves the selected Unicode prefix',async()=>{
 const t=setup({autoAttach:true});t.input.files=[file('selected.md','合成资料😀')];await t.input.onchange();
 assert.equal(t.calls.length,1);assert.equal(t.calls[0].sid,'existing');assert.equal(t.calls[0].files[0].text,'合成资料😀');await t.button.onclick();assert.equal(t.calls.length,1);
});
test('a file read completing after closing the compact flow is never automatically attached',async()=>{
 let current=true,resolve;const waiting=new Promise(r=>resolve=r),t=setup({autoAttach:true,isCurrent:()=>current});
 t.input.files=[{name:'selected.md',size:1,arrayBuffer:()=>waiting}];const reading=t.input.onchange();current=false;resolve(new TextEncoder().encode('合成').buffer);await reading;
 assert.equal(t.calls.length,0);assert.equal(t.button.disabled,true);
});
