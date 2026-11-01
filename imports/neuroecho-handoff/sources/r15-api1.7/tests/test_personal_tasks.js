const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/personal-tasks.js','utf8'),key='xinji_personal_tasks_v1';
function setup(initial, options={}) {
 const values=new Map(initial===undefined?[]:[[key,initial]]),events=[],locks=[];
 const localStorage={getItem:k=>values.get(k)||null,setItem:(k,v)=>{if(options.fail)throw Error('quota');values.set(k,v);}};
 const navigator=options.locks?{locks:{request:(name,fn)=>{locks.push(name);return Promise.resolve(fn());}}}:{};
 const window={dispatchEvent:e=>events.push(e.type)};
 const ctx=vm.createContext({window,localStorage,navigator,CustomEvent:class {constructor(type){this.type=type;}},Promise,JSON});
 vm.runInContext(source,ctx);return {api:window.XinjiPersonalTasks,values,events,locks};
}
const part=(text,id='local-a')=>({id,text,sessionId:'s1'});
test('only explicit nonempty creation requests add tasks, preserving old records and unsent preceding text',async()=>{
 const old=[{title:'已有',detail:'已经存在'}],f=setup(JSON.stringify(old));
 assert.equal(await f.api.record(part('我要创建任务：  ')),false);
 assert.equal(await f.api.record(part('请帮我创建任务：整理资料')),false);
 assert.equal(await f.api.record(part('原来的草稿\n我要创建任务：整理材料\n分两步完成')),true);
 const saved=JSON.parse(f.values.get(key));assert.deepEqual(saved[0],old[0]);
 assert.equal(saved[1].title,'整理材料');assert.equal(saved[1].detail,'整理材料\n分两步完成');assert.equal(saved[1].originMessageId,'local-a');assert.equal(saved[1].sessionId,'s1');assert.deepEqual(f.events,['xinji-personal-tasks-change']);
});
test('the same queued message is idempotent while a separate explicit message can create the same task',async()=>{
 const f=setup(undefined,{locks:true});assert.equal(await f.api.record(part('我要创建任务：整理')),true);
 assert.equal(await f.api.record(part('我要创建任务：整理')),false);assert.equal(await f.api.record(part('我要创建任务：整理','local-b')),true);
 assert.equal(JSON.parse(f.values.get(key)).length,2);assert.equal(f.locks.length,3);
});
test('invalid or unavailable storage never destroys pre-existing content or reports success',async()=>{
 const f=setup('{broken');await assert.rejects(f.api.record(part('我要创建任务：整理')));assert.equal(f.values.get(key),'{broken');assert.equal(f.events.length,0);
 const g=setup('[]',{fail:true});await assert.rejects(g.api.record(part('我要创建任务：整理')));assert.equal(g.values.get(key),'[]');assert.equal(g.events.length,0);
});
