const {test}=require('node:test'),assert=require('node:assert/strict');
const {inspectWindowsListener,windowsArguments,commandMatches}=require('../windows-listener');
const root='C:\\Echo app\\project',python=root+'\\python\\python.exe';
const command=`"${python}" -m uvicorn server.main:app --host 127.0.0.1 --port 18787 --app-dir "${root}"`;
const row={pid:201,address:'127.0.0.1',exe:python,command};
const read=rows=>async(binary,args,options)=>{assert.ok(binary.endsWith('powershell.exe'));assert.ok(args.includes('-NonInteractive'));assert.ok(options.windowsHide);const script=Buffer.from(args.at(-1),'base64').toString('utf16le');assert.ok(!/Get-ChildItem Env:|Get-Content|environ/i.test(script));return {stdout:JSON.stringify(rows)}};
test('Windows command line preserves quoted Unicode/space paths and requires explicit project target',()=>{
 assert.equal(commandMatches(command,root,18787),true);
 assert.deepEqual(windowsArguments('"C:\\中文 目录\\python.exe" -m uvicorn'),['C:\\中文 目录\\python.exe','-m','uvicorn']);
 for(const altered of [command.replace(root+'"','C:\\other"'),command.replace('--app-dir','--reload'),command+' --workers 4',command.replace('127.0.0.1','0.0.0.0')])assert.equal(commandMatches(altered,root,18787),false);
});
test('Windows verified process returns owner, without stopping or scanning other ports',async()=>{
 assert.deepEqual(await inspectWindowsListener(18787,root,python,201,read([row]),p=>p),{pids:[201]});
});
test('Windows wildcard sockets, foreign python, wrong pid and wrong project fail closed',async()=>{
 for(const bad of [{...row,address:'0.0.0.0'},{...row,exe:'C:\\foreign\\python.exe'},{...row,pid:202},{...row,command:command.replace('--app-dir','--reload')}])await assert.rejects(inspectWindowsListener(18787,root,python,201,read([bad]),p=>p));
 await assert.rejects(inspectWindowsListener(18787,root,python,null,read([]),p=>p));
});
