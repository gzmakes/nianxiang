const test=require('node:test'),assert=require('node:assert/strict'),{EventEmitter}=require('node:events');
const {validatePort,matchingHealth,inspectMacListener,createBackendLifecycle}=require('../backend-lifecycle');
function child(){const c=new EventEmitter();Object.assign(c,{pid:501,exitCode:null,killed:false,stdout:new EventEmitter(),stderr:new EventEmitter(),kills:0});c.kill=signal=>{c.kills++;c.killed=true;c.signal=signal;return true};return c}
const good=()=>Promise.resolve({ok:true,json:async()=>({ok:true,product:'xinji-echo'})});
function fixture(extra={}){const c=child(),spawns=[],inspections=[];let clock=0;const lifecycle=createBackendLifecycle({root:'/fixture/project',python:'/fixture/python',platform:'darwin',portAvailable:async()=>true,fetch:good,spawn:(...args)=>{spawns.push(args);return c},inspectListener:async(port,pid)=>{inspections.push([port,pid]);return{pids:[501]}},pause:async ms=>{clock+=ms},now:()=>clock,timeoutMs:600,...extra});return{c,spawns,inspections,lifecycle}}

test('port defaults and product health have strict validation',()=>{assert.equal(validatePort(18787),18787);for(const value of [0,65536,2.5,'x'])assert.throws(()=>validatePort(value));assert.equal(matchingHealth({ok:true,product:'xinji-echo'}),true);for(const body of [{ok:true},{ok:true,product:'another-app'},{ok:false,product:'xinji-echo'}])assert.equal(matchingHealth(body),false)});
test('verified existing local service is borrowed, never spawned or stopped',async()=>{const env=fixture({portAvailable:async()=>false});assert.deepEqual(await env.lifecycle.start(),{port:18787,borrowed:true,pid:null});assert.equal(env.spawns.length,0);assert.equal(env.inspections.length,2);assert.equal(env.lifecycle.borrowed,true);env.lifecycle.stop();assert.equal(env.c.kills,0)});
test('foreign HTTP 200 on the requested port is rejected without spawning or scanning',async()=>{const env=fixture({portAvailable:async()=>false,fetch:async()=>({ok:true,json:async()=>({ok:true,product:'foreign'})})});await assert.rejects(env.lifecycle.start(),/端口已占用|端口.*占用/);assert.equal(env.spawns.length,0);assert.equal(env.inspections.length,0)});
test('same product from another directory is not borrowed',async()=>{const env=fixture({portAvailable:async()=>false,inspectListener:async()=>{throw Error('wrong cwd')}});await assert.rejects(env.lifecycle.start(),/当前念响副本/);assert.equal(env.spawns.length,0)});
test('listener replacement during verification is not borrowed',async()=>{let count=0;const env=fixture({portAvailable:async()=>false,inspectListener:async()=>({pids:[++count]})});await assert.rejects(env.lifecycle.start(),/端口/);assert.equal(env.spawns.length,0)});
test('self-start uses exactly the requested port, verifies child pid, and stops only that child once',async()=>{const env=fixture();assert.deepEqual(await env.lifecycle.start(),{port:18787,borrowed:false,pid:501});assert.equal(env.spawns.length,1);assert.equal(env.spawns[0][1].at(-1),'18787');assert.equal(env.spawns[0][2].cwd,'/fixture/project');assert.deepEqual(env.inspections,[[18787,501]]);env.lifecycle.stop();env.lifecycle.stop();assert.equal(env.c.kills,1);assert.equal(env.c.signal,'SIGTERM')});
test('a healthy product listener that is not the child causes startup failure and only the child is stopped',async()=>{const env=fixture({inspectListener:async(_port,pid)=>{assert.equal(pid,501);throw Error('foreign pid')}});await assert.rejects(env.lifecycle.start(),/当前念响副本/);assert.equal(env.c.kills,1)});
test('an early child exit interrupts a hanging health request immediately',async()=>{let c;const env=fixture({fetch:()=>new Promise(()=>{}),spawn:()=>{c=child();queueMicrotask(()=>{c.exitCode=2;c.emit('exit',2,null)});return c}});const started=Date.now();await assert.rejects(env.lifecycle.start(),/后端已退出.*2/);assert.ok(Date.now()-started<500);assert.equal(c.kills,0)});
test('missing Python is reported clearly without waiting or selecting another interpreter/database',async()=>{let spawns=0;const env=fixture({fetch:()=>new Promise(()=>{}),spawn:()=>{spawns++;const c=child();queueMicrotask(()=>{const e=Error('not found');e.code='ENOENT';c.emit('error',e)});return c}});await assert.rejects(env.lifecycle.start(),/未能启动.*ENOENT.*所选 Python.*没有改用其他解释器或数据库/);assert.equal(spawns,1)});
test('a non-product health response cannot finish owned startup and timeout stops only its child',async()=>{const env=fixture({fetch:async()=>({ok:true,json:async()=>({ok:true,product:'foreign'})})});await assert.rejects(env.lifecycle.start(),/启动超时/);assert.equal(env.c.kills,1);assert.equal(env.inspections.length,0);assert.equal(env.spawns.length,1)});
test('unknown platform fails closed before reading an existing service or starting a child',async()=>{let reads=0;const env=fixture({platform:'unknown',fetch:async()=>{reads++;return good()}});await assert.rejects(env.lifecycle.start(),/仅支持 macOS 和 Windows/);assert.equal(reads,0);assert.equal(env.spawns.length,0)});

function lsof(cwds,addresses={111:'127.0.0.1:18787'}){const calls=[];const execute=async(_bin,args)=>{calls.push(args);if(args.includes('-Fpn'))return{stdout:Object.keys(addresses).map(pid=>`p${pid}\nn${addresses[pid]}`).join('\n')};const pid=args[args.indexOf('-p')+1];return{stdout:`p${pid}\nn${cwds[pid]}\n`}};return{execute,calls}}
test('lsof checks canonical cwd paths and never asks for environment or credentials',async()=>{const env=lsof({111:'/alias/project'}),realpath=p=>p==='/alias/project'?'/real/project':p;assert.deepEqual(await inspectMacListener(18787,'/real/project',111,env.execute,realpath),{pids:[111]});assert.equal(env.calls.length,2);assert.ok(env.calls[1].includes('cwd'));assert.ok(env.calls.every(args=>!args.includes('+e')&&!args.includes('environ')))});
test('lsof rejects mismatched cwd even when health could claim the product name',async()=>{const env=lsof({111:'/different/project'});await assert.rejects(inspectMacListener(18787,'/real/project',null,env.execute,p=>p),/不属于当前原型目录/)});
test('lsof rejects wildcard listeners and a foreign pid on the same port',async()=>{let env=lsof({111:'/real/project'},{111:'*:18787'});await assert.rejects(inspectMacListener(18787,'/real/project',null,env.execute,p=>p),/127.0.0.1/);env=lsof({111:'/real/project'});await assert.rejects(inspectMacListener(18787,'/real/project',222,env.execute,p=>p),/不是本次启动的后端/)});

test('Windows self-start passes explicit app directory, uses hidden child and retains the fixed port',async()=>{const env=fixture({platform:'win32'});await env.lifecycle.start();assert.deepEqual(env.spawns[0][1].slice(-2),['--app-dir','/fixture/project']);assert.equal(env.spawns[0][2].windowsHide,true);assert.deepEqual(env.inspections,[[18787,501]]);env.lifecycle.stop();assert.equal(env.c.kills,1)});
test('portable Mac starts isolated no-bytecode bootstrap with an argv data path and same listener ownership',async()=>{
  const env=fixture({bootstrap:'/fixture/project/desktop_bootstrap.py',dataDir:'/profile with spaces/backend'});
  await env.lifecycle.start();
  assert.deepEqual(env.spawns[0][1],['-I','-B','/fixture/project/desktop_bootstrap.py','--data-dir','/profile with spaces/backend','--port','18787']);
  assert.equal(env.spawns[0][2].cwd,'/fixture/project');assert.deepEqual(env.inspections,[[18787,501]]);
  env.lifecycle.stop();assert.equal(env.c.kills,1);
});
test('portable Mac never borrows an occupied listener because cwd cannot prove its private data profile',async()=>{
  let reads=0;const env=fixture({bootstrap:'/fixture/bootstrap.py',dataDir:'/other-profile',portAvailable:async()=>false,fetch:async()=>{reads++;return good()}});
  await assert.rejects(env.lifecycle.start(),/端口/);assert.equal(reads,0);assert.equal(env.spawns.length,0);assert.equal(env.inspections.length,0);
});

test('developer external-data self-start keeps venv argv, original profile and fixed local port',async()=>{
  const env=fixture({python:'/existing/.venv/bin/python',runner:'/fixture/project/scripts/run_paired_service.py',dataDir:'/private original profile',port:18827});
  await env.lifecycle.start();
  assert.equal(env.spawns[0][0],'/existing/.venv/bin/python');
  assert.deepEqual(env.spawns[0][1],['-I','-B','/fixture/project/scripts/run_paired_service.py','--data-dir','/private original profile','--local-port','18827']);
  assert.deepEqual(env.inspections,[[18827,501]]);env.lifecycle.stop();assert.equal(env.c.kills,1);
});
test('developer external-data mode can borrow a verified existing profile without killing it',async()=>{
  const env=fixture({runner:'/fixture/project/scripts/run_paired_service.py',dataDir:'/private original profile',portAvailable:async()=>false});
  assert.equal((await env.lifecycle.start()).borrowed,true);
  assert.equal(env.spawns.length,0);assert.equal(env.inspections.length,2);env.lifecycle.stop();assert.equal(env.c.kills,0);
});
test('developer profile ownership failure refuses borrowing and never falls back to cwd or another port',async()=>{
  const env=fixture({runner:'/fixture/project/scripts/run_paired_service.py',dataDir:'/selected-profile',portAvailable:async()=>false,inspectListener:async()=>{throw Error('different profile')}});
  await assert.rejects(env.lifecycle.start(),/所选数据空间/);assert.equal(env.spawns.length,0);assert.equal(env.c.kills,0);
});
function profileLsof(opened='p111\nf3\nn/private/data.db.server.lock\n') {
  const calls=[];
  const execute=async(_bin,args)=>{calls.push(args);if(args.includes('-Fpn'))return {stdout:'p111\nn127.0.0.1:18787\n'};
    if(args.includes('cwd'))return {stdout:'p111\nn/real/project\n'};
    if(args.includes('-Ffn'))return {stdout:opened};throw Error('unexpected process query');};
  return {calls,execute};
}
test('Mac profile verification asks only the listener for the selected lease-file descriptor',async()=>{
  const env=profileLsof();
  assert.deepEqual(await inspectMacListener(18787,'/real/project',null,env.execute,p=>p,'/private'),{pids:[111]});
  assert.deepEqual(env.calls.at(-1),['-nP','-a','-p','111','-Ffn','--','/private/data.db.server.lock']);
  assert.ok(env.calls.every(args=>!args.includes('command')&&!args.includes('environ')&&!args.includes('+e')));
});
test('Mac refuses wrong profile, cwd-only descriptor, missing lease and redirected lease path',async()=>{
  for(const opened of ['p111\nf3\nn/other/data.db.server.lock\n','p111\nfcwd\nn/private/data.db.server.lock\n','']) {
    const env=profileLsof(opened);await assert.rejects(inspectMacListener(18787,'/real/project',null,env.execute,p=>p,'/private'),/所选后端数据目录/);
  }
  const env=profileLsof();await assert.rejects(inspectMacListener(18787,'/real/project',null,env.execute,p=>p==='/private/data.db.server.lock'?'/other/data.db.server.lock':p,'/private'),/不是原路径/);
  assert.equal(env.calls.length,0);
});


test('stop while port availability is pending prevents any late spawn or borrow',async()=>{let release;const wait=new Promise(r=>release=r);const env=fixture({portAvailable:()=>wait});const pending=env.lifecycle.start();env.lifecycle.stop();release(true);await assert.rejects(pending,/取消/);assert.equal(env.spawns.length,0);assert.equal(env.c.kills,0)});
test('stop during child health wait kills exactly owned child and cannot return a healthy start',async()=>{let release;const wait=new Promise(r=>release=r);const env=fixture({fetch:()=>wait});const pending=env.lifecycle.start();await new Promise(r=>setImmediate(r));assert.equal(env.spawns.length,1);env.lifecycle.stop();release({ok:true,json:async()=>({ok:true,product:'xinji-echo'})});await assert.rejects(pending,/取消/);assert.equal(env.c.kills,1);env.lifecycle.stop();assert.equal(env.c.kills,1)});
test('stop during existing listener verification never kills the externally managed process',async()=>{let release;const wait=new Promise(r=>release=r);const env=fixture({portAvailable:async()=>false,fetch:()=>wait});const pending=env.lifecycle.start();await new Promise(r=>setImmediate(r));env.lifecycle.stop();release({ok:true,json:async()=>({ok:true,product:'xinji-echo'})});await assert.rejects(pending,/取消/);assert.equal(env.spawns.length,0);assert.equal(env.c.kills,0)});
