// Backend ownership for macOS and Windows desktop clients; never inspect credentials.
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const {spawn, execFile} = require('node:child_process');
const {promisify} = require('node:util');
const {inspectWindowsListener}=require('./windows-listener');
const run = promisify(execFile);

function validatePort(value) {
  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('XINJI_PORT 必须是 1–65535 的整数。');
  return port;
}
function matchingHealth(value) { return value?.ok === true && value?.product === 'xinji-echo'; }
function portAvailable(port) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', error => error.code === 'EADDRINUSE' ? resolve(false) : reject(error));
    server.listen({host:'127.0.0.1',port,exclusive:true}, () => server.close(() => resolve(true)));
  });
}
async function inspectMacListener(port, root, expectedPid = null, execute = run, realpath = fs.realpathSync, dataDir = null) {
  const actualRoot = realpath(root);
  const expectedLock = dataDir === null ? null : path.join(realpath(dataDir),'data.db.server.lock');
  const profileLock = expectedLock === null ? null : realpath(expectedLock);
  if(profileLock!==expectedLock)throw new Error('所选数据目录的专用锁文件不是原路径，无法核验服务归属。');
  const {stdout} = await execute('/usr/sbin/lsof', ['-nP','-a',`-iTCP:${port}`,'-sTCP:LISTEN','-Fpn'], {timeout:1500,maxBuffer:65536});
  const listeners = [];
  let current = null;
  for (const line of String(stdout).split('\n')) {
    if (/^p\d+$/.test(line)) { current={pid:Number(line.slice(1)),addresses:[]};listeners.push(current); }
    else if (line.startsWith('n') && current) current.addresses.push(line.slice(1));
  }
  if (!listeners.length) throw new Error('未找到可核验的监听进程。');
  for (const listener of listeners) {
    if (expectedPid !== null && listener.pid !== expectedPid) throw new Error('端口监听进程不是本次启动的后端。');
    if (!listener.addresses.length || listener.addresses.some(address => address !== `127.0.0.1:${port}`)) throw new Error('只复用明确监听 127.0.0.1 的本机服务。');
    const cwd = await execute('/usr/sbin/lsof', ['-a','-p',String(listener.pid),'-d','cwd','-Fn'], {timeout:1500,maxBuffer:65536});
    const names = String(cwd.stdout).split('\n').filter(line => line.startsWith('n')).map(line => line.slice(1));
    if (names.length !== 1 || realpath(names[0]) !== actualRoot) throw new Error('监听进程不属于当前原型目录。');
    if(profileLock!==null) {
      // DatabaseLease keeps this exact file descriptor open for the worker's
      // lifetime. Query only its metadata, never DB/config contents or argv.
      // macOS lsof does not report Python flock as a record-lock field.
      const opened=await execute('/usr/sbin/lsof',['-nP','-a','-p',String(listener.pid),'-Ffn','--',profileLock],{timeout:1500,maxBuffer:65536});
      let numericFd=false,matched=false;
      for(const field of String(opened.stdout).split('\n')) {
        if(field.startsWith('f'))numericFd=/^f\d+$/.test(field);
        else if(field.startsWith('n') && numericFd && field.slice(1)===profileLock)matched=true;
      }
      if(!matched)throw new Error('监听进程未持有所选后端数据目录的专用锁文件；没有复用其他空间。');
    }
  }
  return {pids:[...new Set(listeners.map(listener => listener.pid))].sort((a,b)=>a-b)};
}

function createBackendLifecycle(options) {
  const root=path.resolve(options.root), python=options.python;
  const port=validatePort(options.port ?? 18787), platform=options.platform ?? process.platform;
  const available=options.portAvailable || portAvailable;
  const fetchImpl=options.fetch || globalThis.fetch;
  const spawnImpl=options.spawn || spawn;
  const inspect=options.inspectListener || ((value, expectedPid) => platform==='win32' ? inspectWindowsListener(value,root,python,expectedPid) : inspectMacListener(value, root, expectedPid,run,fs.realpathSync,options.runner ? options.dataDir : null));
  const pause=options.pause || (ms=>new Promise(resolve=>setTimeout(resolve,ms)));
  const now=options.now || Date.now, timeout=options.timeoutMs ?? 20000;
  let child=null, owned=false, borrowed=false, settled=false, childFailure=null, exitSignal;
  const foreign = () => new Error(`本机 ${port} 端口已占用，或无法验证为当前念响副本${options.runner ? '的所选数据空间' : ''}。请核对服务，或在「连接与空间」明确选择已有服务；桌面不会另换端口打开同一数据库。`);

  async function health() {
    try {
      const response=await fetchImpl(`http://127.0.0.1:${port}/api/health`, {signal:AbortSignal.timeout(1000),redirect:'error',cache:'no-store',credentials:'omit'});
      return response.ok && matchingHealth(await response.json());
    } catch (_) { return false; }
  }
  let stopRequested=false;
  function checkStopped(){if(stopRequested)throw new Error('桌面正在退出，已取消后端启动。');}
  function stop() {
    stopRequested=true;
    if (owned && child && child.exitCode == null && !child.killed) child.kill('SIGTERM');
  }
  async function start() {
    if (settled) throw new Error('桌面后端生命周期不能重复启动。');
    settled=true;checkStopped();
    if (!['darwin','win32'].includes(platform)) throw new Error('当前桌面仅支持 macOS 和 Windows 的服务归属核验；未连接或启动后端。');
    if(options.runner && (platform!=='darwin' || options.bootstrap || typeof options.dataDir!=='string' || !path.isAbsolute(options.dataDir)))throw new Error('本机开发服务入口需要明确的 macOS 外部数据目录。');
    const free=await available(port);checkStopped();
    if (!free) {
      // A matching bundle cwd alone does not prove the same private app-data
      // profile. Portable clients own their child and never borrow by cwd.
      if (options.bootstrap) throw foreign();
      if (!(await health())) throw foreign();checkStopped();
      try {
        const before=await inspect(port, null);checkStopped();
        if (!(await health())) throw foreign();checkStopped();
        const after=await inspect(port, null);checkStopped();
        if (before.pids.join(',') !== after.pids.join(',')) throw foreign();
      } catch (_) { throw foreign(); }
      checkStopped();borrowed=true;
      return {port,borrowed:true,pid:null};
    }
    const args=options.bootstrap
      ? ['-I','-B',options.bootstrap,'--data-dir',options.dataDir,'--port',String(port)]
      : options.runner ? ['-I','-B',options.runner,'--data-dir',options.dataDir,'--local-port',String(port)]
      : ['-m','uvicorn','server.main:app','--host','127.0.0.1','--port',String(port)];
    if(platform==='win32')args.push('--app-dir',root);
    checkStopped();child=spawnImpl(python, args, {cwd:root,stdio:['ignore','pipe','pipe'],windowsHide:true});
    owned=true;
    exitSignal=new Promise(resolve => {
      child.once('error', error => {childFailure=new Error(error.code==='ENOENT'
        ? '后端未能启动（ENOENT）：所选 Python 或服务启动目录已不可用。请核对本机开发壳配置；没有改用其他解释器或数据库。'
        : `后端未能启动：${error.code || '进程错误'}`);resolve({failed:true});});
      child.once('exit', (code, signal) => {childFailure=new Error(`后端已退出（${signal || (code ?? '未知状态')}），请查看终端启动日志。`);resolve({failed:true});});
    });
    child.stdout?.on('data', data=>options.onStdout?.(data));
    child.stderr?.on('data', data=>options.onStderr?.(data));
    const deadline=now()+timeout;
    try {
      while (now()<deadline) {
        checkStopped();
        if (childFailure || child.exitCode != null) throw childFailure || new Error('后端已退出。');
        const ready=await Promise.race([health(),exitSignal]);
        checkStopped();
        if (ready?.failed || childFailure) throw childFailure || new Error('后端已退出。');
        if (ready === true) {
          try { await inspect(port, child.pid); } catch (_) { throw foreign(); }
          if (childFailure || child.exitCode != null) throw childFailure || new Error('后端已退出。');
          checkStopped();return {port,borrowed:false,pid:child.pid};
        }
        await Promise.race([pause(200),exitSignal]);
      }
      throw new Error(`后端启动超时（端口 ${port}）。请查看终端日志；没有自动换端口。`);
    } catch (error) { stop(); throw error; }
  }
  return {start,stop,get port(){return port;},get borrowed(){return borrowed;}};
}
module.exports={validatePort,matchingHealth,portAvailable,inspectMacListener,createBackendLifecycle};
