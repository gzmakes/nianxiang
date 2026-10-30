// Run shipped desktop/H5 functions with fake timing and API responses; never contact Feishu.
const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
function setup(mobile) {
 const source=fs.readFileSync(mobile?'web/m.js':'web/app.js','utf8');
 const start=source.indexOf(mobile?'  let mAuthTimer = null;':'  let authPollTimer = null;');
 const end=source.indexOf(mobile?'  function renderMemeText':'  async function openApps()',start);
 const nodes=new Map(), intervals=new Map(), timeouts=[], cleared=[], apiCalls=[], lifecycle=[];
 let sourceOpen=false;
 let next=0, handler=async path=>({status:'pending',url:'https://example.invalid/'+path});
 function $(id){if(!nodes.has(id)){const classes=new Set(['is-hidden']);nodes.set(id,{classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x)},textContent:'',href:'',src:'',focus(){lifecycle.push(['focus',id,sourceOpen]);}})}return nodes.get(id)}
 const ctx={$, api:(...args)=>{apiCalls.push(args[0]);return handler(...args)},
   setInterval:fn=>{const id=++next;intervals.set(id,fn);return id},clearInterval:id=>{cleared.push(id);intervals.delete(id)},
   setTimeout:fn=>timeouts.push(fn),toast(){},els:{onboarding:{classList:{contains:()=>true}}},showWz(){},loadRealSources(){},loadToday(){},wz:{},chooseScenario(){},
   XinjiSourceDialog:{isOpen:()=>sourceOpen},closeSourceDialog(){lifecycle.push(['close-source']);sourceOpen=false;},
   prepareSourceDialog(){lifecycle.push(['return-source']);sourceOpen=true;},renderFeishuPicker(){lifecycle.push(['show-picker']);}};
 ctx.window=ctx;
 vm.createContext(ctx);
 vm.runInContext(source.slice(start,end)+`\nthis.open=${mobile?'startLarkAuthMobile':'startLarkAuth'};this.close=${mobile?'closeLarkAuthMobile':'closeLarkAuth'};`,ctx);
 return {ctx,$,intervals,timeouts,cleared,apiCalls,lifecycle,openSource:()=>sourceOpen=true,setHandler:fn=>handler=fn,modal:mobile?'#m-auth':'#auth-modal',status:mobile?'#m-auth-status':'#auth-status'};
}
test('desktop authorization releases the source-dialog focus trap before focusing auth, then returns to its picker',async()=>{
 const h=setup(false);h.openSource();await h.ctx.open('document');
 assert.equal(h.lifecycle[0][0],'close-source');
 const focus=h.lifecycle.find(step=>step[0]==='focus');assert.equal(focus[1],'#auth-close');assert.equal(focus[2],false);
 h.ctx.close();assert.ok(h.lifecycle.some(step=>step[0]==='return-source'));assert.ok(h.lifecycle.some(step=>step[0]==='show-picker'));
 assert.equal(h.apiCalls.length,1);assert.equal(h.apiCalls[0],'/api/auth/lark/start');
});
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}}
for (const mobile of [false,true]) {
 const label=mobile?'H5':'desktop';
 test(`${label}: closing while start is in flight does not revive the flow`,async()=>{
  const h=setup(mobile), d=deferred();h.setHandler(()=>d.promise);
  const first=h.ctx.open('search');h.ctx.close();d.resolve({status:'pending',url:'https://example.invalid/old'});await first;
  assert.equal(h.$(h.modal).classList.contains('is-hidden'),true);assert.equal(h.intervals.size,0);
 });
 test(`${label}: stale poll cannot finish or clear a newer flow`,async()=>{
  const h=setup(mobile), d=deferred();h.setHandler(path=>path.endsWith('/search/status')?d.promise:Promise.resolve({status:'pending',url:'https://example.invalid/ok'}));
  await h.ctx.open('search');const oldPoll=[...h.intervals.values()][0]();await h.ctx.open('document');
  assert.equal(h.intervals.size,1);d.resolve({status:'success'});await oldPoll;
  assert.equal(h.intervals.size,1);assert.equal(h.$(h.status).textContent,'等待你在飞书中确认…');
 });
 test(`${label}: stale success timeout cannot close a newly opened modal`,async()=>{
  const h=setup(mobile);h.setHandler(path=>Promise.resolve(path.endsWith('/search/start')?{status:'success'}:{status:'pending',url:'https://example.invalid/new'}));
  await h.ctx.open('search');assert.equal(h.timeouts.length,1);
  await h.ctx.open('document');h.timeouts[0]();assert.equal(h.$(h.modal).classList.contains('is-hidden'),false);
 });
 test(`${label}: a late error after close cannot change a newly opened flow`,async()=>{
  const h=setup(mobile), d=deferred();let n=0;h.setHandler(()=>++n===1?d.promise:Promise.resolve({status:'pending',url:'https://example.invalid/new'}));
  const old=h.ctx.open('search');h.ctx.close();await h.ctx.open('document');d.resolve({status:'error',error:'old failure'});await old;
  assert.equal(h.$(h.status).textContent,'等待你在飞书中确认…');assert.equal(h.intervals.size,1);
 });
}
