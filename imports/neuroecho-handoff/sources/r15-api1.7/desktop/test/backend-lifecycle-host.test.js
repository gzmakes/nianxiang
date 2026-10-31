// Real macOS lsof against a test-owned Node listener and a synthetic open file.
// No app backend, SQLite, credentials, real data directory or fixed port is used.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process'),{once}=require('node:events');
const {createBackendLifecycle}=require('../backend-lifecycle');
test('Mac host check borrows only the listener holding the selected profile descriptor, never kills it',{skip:process.platform!=='darwin',timeout:15000},async t=>{
  const folder=fs.mkdtempSync(path.join(os.tmpdir(),'echo-profile-listener-'));
  const root=path.join(folder,'source'),data=path.join(folder,'selected'),other=path.join(folder,'other');
  fs.mkdirSync(root);fs.mkdirSync(data,{mode:0o700});fs.mkdirSync(other,{mode:0o700});fs.writeFileSync(path.join(other,'data.db.server.lock'),'');
  const code=`const fs=require('node:fs'),http=require('node:http'),path=require('node:path');
    const fd=fs.openSync(path.join(process.argv[1],'data.db.server.lock'),'w',0o600);
    const server=http.createServer((_q,r)=>{r.setHeader('Content-Type','application/json');r.end(JSON.stringify({ok:true,product:'xinji-echo'}));});
    server.listen(0,'127.0.0.1',()=>console.log(server.address().port));
    process.stdin.resume();process.stdin.on('end',()=>server.close(()=>{fs.closeSync(fd);process.exit(0);}));`;
  const child=spawn(process.execPath,['-e',code,data],{cwd:root,stdio:['pipe','pipe','ignore']});
  t.after(async()=>{if(child.exitCode===null){child.kill('SIGTERM');await once(child,'exit');}fs.rmSync(folder,{recursive:true,force:true});});
  const [chunk]=await once(child.stdout,'data'),port=Number(String(chunk).trim());assert.ok(port>0&&port!==18827);
  let spawns=0;const options={root,python:'/unused/venv/bin/python',platform:'darwin',runner:path.join(root,'scripts/run_paired_service.py'),port,spawn:()=>{spawns++;throw Error('must not spawn');}};
  const matching=createBackendLifecycle({...options,dataDir:data});assert.equal((await matching.start()).borrowed,true);
  matching.stop();assert.equal(child.killed,false);assert.equal(child.exitCode,null);assert.equal(spawns,0);
  const mismatched=createBackendLifecycle({...options,dataDir:other});await assert.rejects(mismatched.start(),/所选数据空间/);
  mismatched.stop();assert.equal(child.killed,false);assert.equal(spawns,0);
});
