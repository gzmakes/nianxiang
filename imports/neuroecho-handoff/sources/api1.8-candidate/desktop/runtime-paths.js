// A bundled runtime is optional; existing developer/Windows layouts stay valid.
const fs=require('node:fs');
const path=require('node:path');
function backendPaths({root,platform,pythonOverride,dataDir,exists=fs.existsSync}) {
  const bundled=platform==='darwin' && exists(path.join(root,'python','bin','python3.13')) && exists(path.join(root,'desktop_bootstrap.py'));
  const python=pythonOverride || (platform==='win32'
    ? (exists(path.join(root,'python','python.exe')) ? path.join(root,'python','python.exe') : path.join(root,'.venv','Scripts','python.exe'))
    : bundled ? path.join(root,'python','bin','python3.13') : path.join(root,'.venv','bin','python'));
  return {python,...(bundled ? {bootstrap:path.join(root,'desktop_bootstrap.py'),dataDir:path.join(dataDir,'backend')} : {})};
}
module.exports={backendPaths};
