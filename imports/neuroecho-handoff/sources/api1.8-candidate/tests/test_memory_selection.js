const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
function clip(src,a,b) { const x=src.indexOf(a),y=src.indexOf(b,x); assert.ok(x>=0&&y>x); return src.slice(x,y); }
function element() { const classes=new Set(); return {children:[],textContent:'',checked:false,disabled:false,classList:{add:x=>classes.add(x),remove:x=>classes.delete(x)},replaceChildren(){this.children=[]},appendChild(x){this.children.push(x)}}; }
for (const [name, file, end, box, content, button] of [
 ['desktop','web/app.js','  function showResumeBanner()','#carryover-banner','#carryover-text','#carryover-accept'],
 ['mobile','web/m.js','  function renderStarters()','#m-carryover','#m-carryover-text','#m-carry-accept']
]) test(`${name} shows full memories and imports only explicitly selected`, async()=>{
 const elements=new Map(), $=s=>{if(!elements.has(s))elements.set(s,element());return elements.get(s)};
 const long='我喜欢红茶'.repeat(12), requests=[];
 const ctx=vm.createContext({$,document:{createElement:()=>element()},state:{session:{id:'s'},memories:[]},localStorage:{getItem(){return null},setItem(){}},
   api:async(path,opt)=>{requests.push([path,opt]);if(path.startsWith('/api/carryover?'))return {memories:[{id:'a',version:2,text:long},{id:'b',version:3,text:'我喜欢绿茶'}],current_confirmed:[{id:'c',version:4,text:'我偏爱安静'}]};if(path==='/api/carryover/import')return {imported:1};return {memories:[]}},
   renderAll(){},toast(){},Object});
 vm.runInContext(clip(fs.readFileSync(file,'utf8'),'  async function loadCarryover() {',end)+'\nthis.load=loadCarryover',ctx);
 await ctx.load();const children=$(content).children;assert.equal(children[1].children[1].textContent,'我偏爱安静');assert.equal(children[2].children[1].textContent,long);
 await $(button).onclick();assert.equal(requests.length,1);
 children[2].children[0].checked=true;await $(button).onclick();
 const body=JSON.parse(requests[1][1].body);assert.deepEqual(body,{session_id:'s',ids:['a'],expected_versions:{a:2},expected_target:{c:4}});
});
