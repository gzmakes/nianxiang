const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const src=fs.readFileSync('web/m.js','utf8');
const start=src.indexOf('  let mSelectedImage = null'), end=src.indexOf('  function cancelPending()',start);
assert.ok(start>=0&&end>start);
function setup(){
 const nodes=new Map(),toastMessages=[],readers=[];
 const $=key=>{if(!nodes.has(key))nodes.set(key,{value:'',src:'',classList:{add(){},remove(){}},removeAttribute(){this.src=''}});return nodes.get(key)};
 const state={session:{id:'A'}};
 class Reader{constructor(){readers.push(this)}readAsDataURL(file){this.file=file}}
 const c=vm.createContext({$,state,toast:x=>toastMessages.push(x),FileReader:Reader,Map});
 vm.runInContext(`let mActiveTurn=null,mQueuedTurns=[],mTurnQueue=[],mUncertainTurns=new Map();\n${src.slice(start,end)}\nthis.select=selectMobileImage;this.clear=clearMobileImage;this.current=()=>mSelectedImage;`,c);
 return{c,state,readers,toastMessages};
}
test('H5 image selection validates file type and size before reading',()=>{
 const e=setup();e.c.select({type:'image/gif',size:5});e.c.select({type:'image/png',size:4*1024*1024+1});
 assert.equal(e.readers.length,0);assert.equal(e.toastMessages.length,2);
});
test('H5 image selection discards stale reads after removal or switching session',()=>{
 const e=setup();e.c.select({type:'image/png',size:5});e.c.clear();e.readers[0].result='data:image/png;base64,AAAA';e.readers[0].onload();assert.equal(e.c.current(),null);
 e.c.select({type:'image/png',size:5});e.state.session.id='B';e.readers[1].result='data:image/png;base64,AAAA';e.readers[1].onload();assert.equal(e.c.current(),null);
});
test('H5 image selection only accepts validated data URLs and retains selected session',()=>{
 const e=setup();e.c.select({type:'image/png',size:5});e.readers[0].result='data:image/png;base64,AAAA';e.readers[0].onload();
 assert.equal(e.c.current().dataUrl,'data:image/png;base64,AAAA');assert.equal(e.c.current().sessionId,'A');
});
test('H5 image control supplies an icon after the icon-only design system and stays in the narrow composer',()=>{
 const html=fs.readFileSync('web/m.html','utf8'),css=fs.readFileSync('web/m-image.css','utf8');
 assert.ok(html.indexOf('/static/m-image.css')>html.indexOf('/static/design-system.css'));
 assert.match(css,/#m-app #m-image-btn\s*\{\s*--c-icon:url/);
 assert.match(css,/@media\s*\(max-width:359px\)[\s\S]*#m-app #m-composer\s*\{\s*flex-wrap:nowrap/);
 assert.match(css,/#m-image-preview:not\(\.is-hidden\)[\s\S]*#m-composer \.send/);
});
