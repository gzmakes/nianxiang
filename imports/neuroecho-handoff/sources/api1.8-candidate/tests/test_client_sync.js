// Exercise version boundaries and foreground races, with synthetic records only.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture(){const ctx=vm.createContext({window:{},localStorage:{},document:{}});vm.runInContext(fs.readFileSync('web/client-sync.js','utf8'),ctx);return ctx.window;}
test('memory writes require advertised CAS support and never downgrade to an unchecked write',async()=>{
 const sync=fixture().XinjiMemorySync,calls=[];
 const api=async(path,options)=>{calls.push({path,options});return{features:{}}};
 await assert.rejects(sync.patch(api,{id:'m',version:2},{text:'合成纠正'}),/尚不支持记忆版本核对/);
 await assert.rejects(sync.remove(api,{id:'m',version:2}),/尚不支持记忆版本核对/);
 assert.equal(calls.length,1);assert.equal(calls[0].path,'/api/capabilities');
});
test('CAS snapshots the viewed version before capability lookup and encodes IDs and delete versions',async()=>{
 const sync=fixture().XinjiMemorySync,calls=[],memory={id:'id/合成',version:3};let ready;
 const api=async(path,options)=>{calls.push({path,options});if(path==='/api/capabilities')return new Promise(r=>ready=r);return{version:4};};
 const saving=sync.patch(api,memory,{text:'保留全文',expected_version:99});memory.version=4;
 ready({features:{memory_expected_version_patch:true,memory_expected_version_delete:true}});await saving;
 assert.deepEqual(JSON.parse(calls[1].options.body),{text:'保留全文',expected_version:3});assert.equal(calls[1].path,'/api/memory/id%2F%E5%90%88%E6%88%90');
 await sync.remove(api,memory);assert.match(calls[2].path,/\?expected_version=4$/);assert.equal(calls[2].options.method,'DELETE');
});
test('a transient metadata failure can be checked again, but an actual conflict is never automatically retried',async()=>{
 const sync=fixture().XinjiMemorySync;let metadata=0,writes=0;
 const conflict=Object.assign(Error('已变化'),{status:409,code:'memory_version_conflict'});
 const api=async path=>{if(path==='/api/capabilities'){if(++metadata===1)throw Error('暂时离线');return{features:{memory_expected_version_patch:true}};}writes++;throw conflict;};
 await assert.rejects(sync.patch(api,{id:'m',version:1},{text:'草稿'}),/暂时离线/);
 await assert.rejects(sync.patch(api,{id:'m',version:1},{text:'草稿'}),error=>sync.isConflict(error));
 assert.equal(metadata,2);assert.equal(writes,1);
});
test('foreground refresh discards a snapshot if an editor or outgoing turn starts during the read',async()=>{
 const sync=fixture().XinjiForegroundSync;let idle=true,reads=0,applied=0,now=10000,release;
 const refresh=sync.create({canRefresh:()=>idle,clock:()=>now,read:()=>{reads++;return new Promise(r=>release=r)},apply:()=>applied++});
 const reading=refresh();assert.equal(await refresh(),false);idle=false;release({synthetic:true});assert.equal(await reading,false);assert.equal(applied,0);
 idle=true;now+=1600;const again=refresh();release({synthetic:true});assert.equal(await again,true);assert.equal(applied,1);assert.equal(reads,2);assert.equal(await refresh(),false);
});
test('draft restore never overwrites current input and persistence has no service writes',()=>{
 const ctx=vm.createContext({window:{addEventListener(){}},document:{addEventListener(){}},localStorage:{}});vm.runInContext(fs.readFileSync('web/client-sync.js','utf8'),ctx);
 const values=new Map([['xinji_composer_draft_v1_h5','未发合成内容']]),storage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)},input={value:'',addEventListener(event,fn){this.changed=fn}};
 const draft=ctx.window.XinjiForegroundSync.draft(input,'h5',storage);assert.equal(input.value,'未发合成内容');input.value='补充';input.changed();assert.equal(values.get('xinji_composer_draft_v1_h5'),'补充');input.value='';draft.save();assert.equal(values.get('xinji_composer_draft_v1_h5'),'');
 input.value='当前输入';ctx.window.XinjiForegroundSync.draft(input,'h5',storage);assert.equal(input.value,'当前输入');
});
