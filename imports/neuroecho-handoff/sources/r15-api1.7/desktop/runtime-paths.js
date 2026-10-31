// A bundled runtime is optional; existing developer/Windows layouts stay valid.
const fs=require('node:fs');
const path=require('node:path');
function inside(parent,child) { const relative=path.relative(parent,child);return relative==='' || (!relative.startsWith(`..${path.sep}`) && relative!=='..' && !path.isAbsolute(relative)); }
function backendDataPath(root,value) {
  if(typeof value!=='string' || !path.isAbsolute(value) || value.includes('\0'))throw new Error('后端数据目录必须是明确的绝对路径。');
  const selected=path.resolve(value),actual=fs.realpathSync(selected),actualRoot=fs.realpathSync(root);
  const info=fs.statSync(selected);
  if(fs.lstatSync(selected).isSymbolicLink() || !info.isDirectory() || (info.mode&0o077)
    || inside(actualRoot,actual) || [selected,actual].some(p=>p.split(path.sep).some(part=>part.toLowerCase().endsWith('.app')))) {
    throw new Error('后端数据目录必须是源码和 App 包体外、已存在的私有目录（0700）；不会更改权限或复制配置。');
  }
  return actual;
}
function backendPaths({root,platform,pythonOverride,dataDir,backendDataDir,exists=fs.existsSync}) {
  const bundled=platform==='darwin' && exists(path.join(root,'python','bin','python3.13')) && exists(path.join(root,'desktop_bootstrap.py'));
  const python=pythonOverride || (platform==='win32'
    ? (exists(path.join(root,'python','python.exe')) ? path.join(root,'python','python.exe') : path.join(root,'.venv','Scripts','python.exe'))
    : bundled ? path.join(root,'python','bin','python3.13') : path.join(root,'.venv','bin','python'));
  if(backendDataDir!==undefined && backendDataDir!==null) {
    if(platform!=='darwin' || bundled)throw new Error('显式外部数据目录仅用于 macOS 本机开发壳；便携版继续使用独立数据空间。');
    const runner=path.join(root,'scripts','run_paired_service.py');
    if(!exists(runner))throw new Error('当前源码缺少已审查的本机服务入口；没有回退到其他数据库。');
    return {python,runner,dataDir:backendDataPath(root,backendDataDir)};
  }
  return {python,...(bundled ? {bootstrap:path.join(root,'desktop_bootstrap.py'),dataDir:path.join(dataDir,'backend')} : {})};
}
module.exports={backendPaths,backendDataPath};
