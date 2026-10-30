// Windows loopback listener ownership. No environment or credential reads.
const path=require('node:path');
const fs=require('node:fs');
const {execFile}=require('node:child_process');
const {promisify}=require('node:util');
const run=promisify(execFile);
function windowsArguments(line){
  const args=[];let i=0;
  while(i<line.length){
    while(/\s/.test(line[i]||'')&&i<line.length)i++;
    if(i>=line.length)break;
    let value='',quoted=false;
    while(i<line.length && (quoted||!/\s/.test(line[i]))){
      let slashes=0;while(line[i]==='\\'){slashes++;i++;}
      if(line[i]==='"'){
        value+='\\'.repeat(Math.floor(slashes/2));
        if(slashes%2)value+='"';else quoted=!quoted;
        i++;
      }else{value+='\\'.repeat(slashes);if(i<line.length && (quoted||!/\s/.test(line[i])))value+=line[i++];else break;}
    }
    if(quoted)throw Error('无法核验服务命令行。');
    args.push(value);
  }
  return args;
}
const canonical=value=>path.win32.normalize(value).replace(/[\\/]+$/,'').toLowerCase();
function commandMatches(command,root,port){
  const args=windowsArguments(String(command||''));
  const expected=['-m','uvicorn','server.main:app','--host','127.0.0.1','--port',String(port),'--app-dir'];
  return args.length===10 && expected.every((value,index)=>args[index+1]===value) && canonical(args[9])===canonical(root);
}
async function inspectWindowsListener(port,root,python,expectedPid=null,execute=run,realpath=fs.realpathSync){
  const expectedRoot=realpath(root),expectedPython=realpath(python);
  const script=`$ErrorActionPreference='Stop'; $rows=@(); foreach($socket in @(Get-NetTCPConnection -LocalPort ${Number(port)} -State Listen -ErrorAction SilentlyContinue)){ $owner=Get-CimInstance Win32_Process -Filter ('ProcessId = '+$socket.OwningProcess); $rows+= [pscustomobject]@{pid=[int]$socket.OwningProcess;address=[string]$socket.LocalAddress;exe=[string]$owner.ExecutablePath;command=[string]$owner.CommandLine} }; ConvertTo-Json -Compress -InputObject @($rows)`;
  const binary=path.win32.join(process.env.SystemRoot||'C:\\Windows','System32','WindowsPowerShell','v1.0','powershell.exe');
  const result=await execute(binary,['-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',Buffer.from(script,'utf16le').toString('base64')],{timeout:6000,maxBuffer:65536,windowsHide:true});
  const rows=JSON.parse(String(result.stdout).replace(/^\uFEFF/,''));
  if(!Array.isArray(rows)||!rows.length)throw Error('未找到可核验的本机监听进程。');
  for(const row of rows){
    if(!Number.isInteger(row.pid)||row.pid<1||row.address!=='127.0.0.1')throw Error('只复用明确监听127.0.0.1的本机服务。');
    if(expectedPid!==null&&row.pid!==expectedPid)throw Error('端口不属于本次启动的进程。');
    if(!row.exe||canonical(realpath(row.exe))!==canonical(expectedPython)||!commandMatches(row.command,expectedRoot,port))throw Error('监听进程不属于当前原型目录。');
  }
  return {pids:[...new Set(rows.map(row=>row.pid))].sort((a,b)=>a-b)};
}
module.exports={inspectWindowsListener,windowsArguments,commandMatches};
