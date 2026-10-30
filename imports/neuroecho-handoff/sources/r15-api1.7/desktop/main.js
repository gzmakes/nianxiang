const {app,BrowserWindow,ipcMain,dialog,Tray,Menu,nativeImage,globalShortcut,screen,shell,Notification,session} = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const {randomUUID} = require('node:crypto');
const {fileURLToPath}=require('node:url');
const {probeService,partitionFor,selectionStore,createSelectionFlow,sameOrigin}=require('./service-connection');
const {ownerIPC,sharedIPC,fileIPC,hardenSharedSession}=require('./connection-security');
const {createBackendLifecycle} = require('./backend-lifecycle');
const {backendPaths}=require('./runtime-paths');
const {readTextFile} = require('./bridge');
const {revealWindow} = require('./window-lifecycle');
const {normalizeState,validCommand,tomorrowAtNine,effectiveState,stateLabel} = require('./desktop-state');
const {createFollowupNotifier,legacyNotificationResult} = require('./notification-policy');
app.setName('回响');
let bundledRoot, bundledPort, bundledProfile;
try {
  const pointer=require('./project-root.json');
  bundledRoot=pointer.root || (pointer.relativeRoot && path.resolve(__dirname,pointer.relativeRoot));
  bundledPort=pointer.port;
  if(typeof pointer.profile==='string' && /^[a-z0-9][a-z0-9.-]{0,63}$/i.test(pointer.profile))bundledProfile=pointer.profile;
} catch (_) {}
const ROOT=path.resolve(process.env.XINJI_PROJECT_ROOT || bundledRoot || path.join(__dirname,'..'));
const PORT=process.env.XINJI_PORT || bundledPort || 18787;
if(process.env.XINJI_DESKTOP_DATA_DIR)app.setPath('userData',path.resolve(process.env.XINJI_DESKTOP_DATA_DIR));
else if(bundledProfile)app.setPath('userData',path.join(app.getPath('appData'),bundledProfile));
const backendRuntime=backendPaths({root:ROOT,platform:process.platform,pythonOverride:process.env.XINJI_PYTHON,dataDir:app.getPath('userData')});
const PYTHON=backendRuntime.python;
let win=null,tray=null,panel=null,backend=null,port=PORT,state='quiet',ready=false;
let mode='own',selected={version:1,mode:'own'},selector=null,selectorMessage='',connectionStore=null,selectionFlow=null,connectionEpoch=0,quitting=false,sharedTimer=null;
const spaceWindows=new Map(),sharedLeases=new Map();
let prefs={pausedUntil:null,snoozed:{},notificationAttempts:[],contactAttempts:[]}; let preferencesPath;
let notifier=null,notificationTimer=null,ownStart=null,pendingOwnBackend=null;
const activeNotifications=new Set();
let shortcutAvailable=false;
const ownOrigin=()=>`http://127.0.0.1:${port}`;
const origin=()=>mode==='shared'?selected.origin:ownOrigin();
function readPreferences(){
  preferencesPath=path.join(app.getPath('userData'),'desktop-preferences.json');
  try { const saved=JSON.parse(fs.readFileSync(preferencesPath,'utf8')); prefs={pausedUntil:typeof saved.pausedUntil==='string'?saved.pausedUntil:null,snoozed:saved.snoozed||{},notificationAttempts:Array.isArray(saved.notificationAttempts)?saved.notificationAttempts.filter(Number.isFinite):[],contactAttempts:Array.isArray(saved.contactAttempts)?saved.contactAttempts.filter(x=>typeof x==='string'):[]}; } catch (_) {}
}
function savePreferences(){
  const temporary=`${preferencesPath}.${randomUUID()}.tmp`;
  try {fs.writeFileSync(temporary,JSON.stringify(prefs),{mode:0o600,flag:'wx'});fs.renameSync(temporary,preferencesPath);return true;}
  catch(_) {try{fs.unlinkSync(temporary);}catch(_){}return false;}
}
function closeFollowupNotices(){
  notifier?.invalidate?.();
  for(const note of activeNotifications){try{note.close();}catch(_){}}
  activeNotifications.clear();
}
function isMain(event){return win?.connectionMode==='own'&&ownerIPC(event,win,mode,ownOrigin());}
function isPanelURL(url){try{return fileURLToPath(new URL(url))===path.join(__dirname,'panel.html');}catch(_){return false;}}
function isPanel(event){return mode==='own' && !!panel && event.sender===panel.webContents && event.senderFrame===panel.webContents.mainFrame && isPanelURL(event.senderFrame.url);}
function external(url){try { const u=new URL(url);if(u.protocol==='https:'&&!u.username&&!u.password)shell.openExternal(u.href); }catch(_) {}}
function secureWindow(window, main=false){
  window.webContents.setWindowOpenHandler(({url})=>{if(window.connectionMode!=='shared')external(url);return {action:'deny'};});
  window.webContents.on('will-navigate',(event,url)=>{
    let allow=false;try{allow=main?sameOrigin(url,window.connectionOrigin):isPanelURL(url);}catch(_){}
    if(!allow){event.preventDefault();if(window.connectionMode!=='shared')external(url);}
  });
}
function emit(command){
  if(mode==='shared'&&!leaseFor(selected)?.active){openSelector();return;}
  if(!win)createWindow();
  if(!win){openSelector();return;}
  revealWindow(win);
  if(ready)win.webContents.send('desktop:command',command);
  else {const target=win;target.webContents.once('did-finish-load',()=>{if(win===target)target.webContents.send('desktop:command',command);});}
}
function emitQuiet(){if(mode==='own'&&win&&ready)win.webContents.send('desktop:command',{action:'quiet',pausedUntil:prefs.pausedUntil});refreshTray();}
function pause(){if(mode!=='own')return;closeFollowupNotices();prefs.pausedUntil=tomorrowAtNine();savePreferences();emitQuiet();panel?.hide();}
function resume(){if(mode!=='own')return;closeFollowupNotices();prefs.pausedUntil=null;savePreferences();emitQuiet();panel?.hide();}
function createWindow(){
  if(mode==='own'&&!backend?.started){openSelector('原空间的服务尚未核验。请明确选择已有服务，或再次尝试返回原空间。');return null;}
  const key=mode==='own'?'own':partitionFor(selected);
  if(mode==='shared')prepareSharedSession(selected);
  const cached=spaceWindows.get(key);if(cached&&!cached.isDestroyed()){win=cached;ready=cached.connectionLoaded===true;revealWindow(win);return win;}
  ready=false;
  const windowMode=mode,windowOrigin=origin(),partition=mode==='shared'?partitionFor(selected):undefined;
  win=new BrowserWindow({width:1000,height:830,minWidth:780,minHeight:640,title:'回响',show:false,
    icon:path.join(__dirname,'assets','echo.png'),
    backgroundColor:'#EDF1FF',titleBarStyle:process.platform==='win32'?'hidden':'hiddenInset',trafficLightPosition:{x:18,y:20},
    titleBarOverlay:process.platform==='win32'?{color:'#EDF1FF',symbolColor:'#1B2433',height:48}:undefined,
    backgroundMaterial:process.platform==='win32'?'mica':undefined,
    vibrancy:process.platform==='darwin'?'under-window':undefined,visualEffectState:'followWindow',
    webPreferences:{preload:path.join(__dirname,windowMode==='shared'?'shared-preload.js':'preload.js'),...(partition?{partition}:{}),contextIsolation:true,nodeIntegration:false,sandbox:true}});
  win.connectionMode=windowMode;win.connectionOrigin=windowOrigin;win.connectionLoaded=false;spaceWindows.set(key,win);
  secureWindow(win,true);
  win.on('focus',closeFollowupNotices);
  const currentWindow=win;
  win.once('ready-to-show',()=>{if(win===currentWindow)revealWindow(currentWindow);});
  win.webContents.on('did-fail-load',(_,code,description,url,isMainFrame)=>{
    if(code===-3 || isMainFrame===false || currentWindow.isDestroyed() || win!==currentWindow)return;
    revealWindow(currentWindow);
    dialog.showErrorBox('回响界面未能载入',`本机界面暂时无法载入（${code}）。对话数据仍保留。请确认本机服务可用后，在窗口按 ${process.platform==='darwin'?'⌘R':'Ctrl+R'} 重试。`);
  });
  win.webContents.on('render-process-gone',()=>{
    if(currentWindow.isDestroyed()||win!==currentWindow)return;
    revealWindow(currentWindow);
    dialog.showErrorBox('回响界面需要重新载入',`界面进程已停止，对话数据仍保留。请在窗口按 ${process.platform==='darwin'?'⌘R':'Ctrl+R'} 重新载入。`);
  });
  win.webContents.on('did-finish-load',()=>{currentWindow.connectionLoaded=true;if(win!==currentWindow)return;ready=true;emitQuiet();});
  win.loadURL(`${windowOrigin}/?desktop=1`).catch(()=>{if(windowMode==='shared'&&win===currentWindow)quarantineShared('所选服务暂时无法载入，原空间没有被替换。');});
  win.on('close',()=>{if(process.platform!=='darwin'&&win===currentWindow&&!quitting)app.quit();});
  win.on('closed',()=>{spaceWindows.delete(key);if(win===currentWindow){win=null;ready=false;}});
  return win;
}
function refreshTray(){
  if(!tray)return;
  const value=effectiveState(state,prefs.pausedUntil),icon=nativeImage.createFromPath(path.join(__dirname,'assets',`tray-${value==='failed'?'thinking':value}.png`));
  if(process.platform==='darwin')icon.setTemplateImage(true);
  tray.setImage(process.platform==='win32'?nativeImage.createFromPath(path.join(__dirname,'assets','echo.png')):icon);tray.setToolTip(`回响 · ${stateLabel(state,prefs.pausedUntil)}`);
}
function togglePanel(panelMode='quick'){
  if(mode!=='own'){if(!leaseFor(selected)?.active){openSelector();return;}if(win)revealWindow(win);return;}
  const panelKind=panelMode;
  if(!panel){
    panel=new BrowserWindow({width:640,height:264,frame:false,resizable:false,show:false,alwaysOnTop:true,skipTaskbar:true,backgroundColor:'#EDF1FF',
      vibrancy:process.platform==='darwin'?'popover':undefined,visualEffectState:'active',
      webPreferences:{preload:path.join(__dirname,'panel-preload.js'),contextIsolation:true,nodeIntegration:false,sandbox:true}});
    secureWindow(panel,false);panel.on('blur',()=>panel?.hide());panel.on('closed',()=>{panel=null;});
  }
  if(panel.isVisible()&&panel.mode===panelKind){panel.hide();return;}
  panel.mode=panelKind;panel.setSize(panelKind==='tray'?360:640,panelKind==='tray'?440:264);
  if(panelKind==='tray'&&tray){
    const bounds=tray.getBounds(),area=screen.getDisplayMatching(bounds).workArea;
    const x=Math.max(area.x,Math.min(bounds.x+bounds.width/2-180,area.x+area.width-360));
    panel.setPosition(Math.round(x),Math.round(Math.max(area.y,bounds.y+bounds.height+8)));
  }else panel.center();
  panel.loadFile(path.join(__dirname,'panel.html'),{query:{mode:panelKind}}).then(()=>{panel?.show();panel?.focus();});
}
function createTray(){
  tray=new Tray(nativeImage.createFromPath(path.join(__dirname,'assets','tray-quiet.png')));
  refreshTray();
  tray.on('click',()=>togglePanel('tray'));
  tray.on('right-click',()=>tray.popUpContextMenu(Menu.buildFromTemplate([
    {label:'打开回响',click:()=>emit({action:'chat'})},{label:'连接与空间…',click:()=>openSelector()},{label:'唤起输入条',enabled:mode==='own',click:()=>togglePanel('quick')},
    {label:'管理跟进通知',click:()=>emit({action:'today'})},{label:'本机系统通知暂停到明天 09:00',enabled:mode==='own',click:pause},{label:'恢复本机系统通知',enabled:mode==='own',click:resume},{type:'separator'},{label:'退出回响',click:()=>app.quit()}])));
}
async function summary(){
  if(mode!=='own')return {label:'已连接本机服务；桌面通知和输入条未启用',item:null};
  const ticket=connectionEpoch,base=ownOrigin();
  const out={label:stateLabel(state,prefs.pausedUntil),pausedUntil:prefs.pausedUntil,shortcutAvailable,item:null};
  try{
    const c=await fetch(`${base}/api/conversation`,{signal:AbortSignal.timeout(3000)}).then(r=>r.json());
    const a=await fetch(`${base}/api/actions?session_id=${encodeURIComponent(c.session.id)}`,{signal:AbortSignal.timeout(3000)}).then(r=>r.json());
    if(mode!=='own'||ticket!==connectionEpoch)return {label:'连接已更换，请打开当前对话',item:null};
    const item=(a.actions||[]).find(x=>x.status==='previewed');
    if(item)out.item={title:String(item.title).slice(0,120),kind:item.kind};
  }catch(_){out.error='暂时没能读取待确认事项，打开回响后可重试。';}
  return out;
}
const selectorFile=path.join(__dirname,'connection-selector.html');
function isSelector(event){return fileIPC(event,selector,selectorFile);}
function openSelector(message=''){
  if(quitting)return;
  selectorMessage=message||selectorMessage;
  if(selector&&!selector.isDestroyed()){revealWindow(selector);return;}
  selector=new BrowserWindow({width:760,height:860,minWidth:640,minHeight:640,title:'回响 · 连接与空间',backgroundColor:'#F8FAFF',show:false,
    webPreferences:{preload:path.join(__dirname,'selector-preload.js'),contextIsolation:true,nodeIntegration:false,sandbox:true}});
  const current=selector;current.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  current.webContents.on('will-navigate',(event,url)=>{try{if(fileURLToPath(new URL(url))!==selectorFile)event.preventDefault();}catch(_){event.preventDefault();}});
  current.once('ready-to-show',()=>revealWindow(current));current.loadFile(selectorFile);
  current.on('closed',()=>{if(selector===current){selector=null;selectionFlow?.invalidate();}});
}
function leaseFor(value){return sharedLeases.get(partitionFor(value));}
function quarantineShared(message){
  if(mode!=='shared')return;const lease=leaseFor(selected);if(lease)lease.active=false;
  win?.hide();openSelector(message);
}
function prepareSharedSession(value){
  const key=partitionFor(value);let lease=sharedLeases.get(key);
  if(lease){lease.active=true;return lease;}
  const target=session.fromPartition(key);lease={active:true,selection:{...value}};sharedLeases.set(key,lease);hardenSharedSession(target);
  target.webRequest.onBeforeRequest({urls:['<all_urls>']},(details,callback)=>{
    if(!lease.active||!sameOrigin(details.url,value.origin))return callback({cancel:true});
    // Reads stay cheap; each new document and each mutation is checked before forwarding.
    // Never replay a request. A local service replacement between HTTP requests still needs
    // a future server-side instance precondition for an atomic guarantee.
    if(details.resourceType!=='mainFrame'&&['GET','HEAD','OPTIONS'].includes(details.method||'GET'))return callback({cancel:false});
    const ticket=connectionEpoch;
    probeService(value.origin,{expected:value}).then(()=>{const ok=lease.active&&ticket===connectionEpoch&&mode==='shared'&&partitionFor(selected)===key;callback({cancel:!ok});},()=>{callback({cancel:true});if(lease.active&&ticket===connectionEpoch&&mode==='shared'&&partitionFor(selected)===key)quarantineShared('服务离线或身份已变化，请先重新核对。草稿仍留在原空间。');});
  });
  target.webRequest.onHeadersReceived({urls:['http://*/*','https://*/*']},(details,callback)=>callback({cancel:details.statusCode>=300&&details.statusCode<400}));
  return lease;
}
function stopOwnedNotifier(){if(notificationTimer)clearInterval(notificationTimer);notificationTimer=null;closeFollowupNotices();notifier=null;panel?.destroy();panel=null;}
function startOwnedNotifier(){
  if(mode!=='own'||notifier)return;const base=ownOrigin();
  notifier=createFollowupNotifier({origin:()=>base,getPrefs:()=>prefs,savePrefs:savePreferences,
    request:(url,options)=>mode==='own'&&sameOrigin(url,base)?fetch(url,options):Promise.reject(Error('Space changed')),
    show:showFollowupNotice,supported:()=>mode==='own'&&Notification.isSupported(),close:closeFollowupNotices,
    isForeground:()=>mode==='own'&&!!win&&!win.isDestroyed()&&win.isVisible()&&!win.isMinimized()&&win.isFocused()});
  void notifier.tick();notificationTimer=setInterval(()=>void notifier?.tick(),30000);notificationTimer.unref();
}
async function ensureOwnBackend(){
  if(quitting)return;
  if(backend?.started)return;
  if(ownStart)return ownStart;
  ownStart=(async()=>{const candidate=createBackendLifecycle({root:ROOT,...backendRuntime,python:PYTHON,port:PORT,onStdout:d=>process.stdout.write(d),onStderr:d=>process.stderr.write(d)});
    pendingOwnBackend=candidate;
    try{const result=await candidate.start();if(quitting){candidate.stop();return;}candidate.started=true;backend=candidate;port=result.port;}
    finally{if(pendingOwnBackend===candidate)pendingOwnBackend=null;}
  })();
  try{await ownStart;}finally{ownStart=null;}
}
async function activateSpace(value){
  const ticket=++connectionEpoch;
  if(quitting)return false;
  if(value.mode==='own')await ensureOwnBackend();
  if(ticket!==connectionEpoch||quitting)return false;
  stopOwnedNotifier();if(mode==='shared'){const old=leaseFor(selected);if(old)old.active=false;}
  win?.hide();selected=value;mode=value.mode;ready=false;state='quiet';
  createWindow();if(mode==='own')startOwnedNotifier();refreshTray();
  selectorMessage='';selector?.close();return true;
}
async function verifyCurrentShared(){
  if(mode!=='shared'||selector?.isVisible())return;const value=selected,ticket=connectionEpoch;
  try{await probeService(value.origin,{expected:value});}catch(_){if(mode==='shared'&&ticket===connectionEpoch)quarantineShared('服务离线或身份已变化。请重新核对；不会自动进入另一个空空间。');}
}
ipcMain.handle('connection:status',event=>{if(!isSelector(event))throw Error('Unavailable sender');return {selection:selected.mode==='shared'?selected:connectionStore?.load(),message:selectorMessage||'连接前请核对范围；原空间的草稿与待核对请求不会搬移。'};});
ipcMain.handle('connection:verify',(event,value)=>{if(!isSelector(event))throw Error('Unavailable sender');return selectionFlow.verify(value);});
ipcMain.handle('connection:invalidate',event=>{if(!isSelector(event))return false;selectionFlow.invalidate();return true;});
ipcMain.handle('connection:connect',(event,value)=>{if(!isSelector(event))throw Error('Unavailable sender');return selectionFlow.connect(value);});
ipcMain.handle('connection:own',(event,value)=>{if(!isSelector(event))throw Error('Unavailable sender');return selectionFlow.own(value?.confirmed);});
ipcMain.handle('connection:close',event=>{if(!isSelector(event))return false;if(mode==='shared'&&!leaseFor(selected)?.active)return false;selector.close();if(win&&!win.isDestroyed())revealWindow(win);return true;});
ipcMain.handle('desktop:open-connections',event=>{if(!isMain(event)&&!(win?.connectionMode==='shared'&&sharedIPC(event,win,mode,selected.origin)))return false;openSelector();return true;});
ipcMain.handle('desktop:shared-info',event=>{if(!sharedIPC(event,win,mode,selected.origin))throw Error('Unavailable sender');return {platform:process.platform,version:app.getVersion(),native:false,connectionMode:'shared',notificationSupported:false,shortcutAvailable:false};});
ipcMain.handle('desktop:info',event=>{if(!isMain(event))throw Error('Unavailable sender');return {platform:process.platform,version:app.getVersion(),native:true,shortcutAvailable,pausedUntil:prefs.pausedUntil,notificationSupported:Notification.isSupported()};});
ipcMain.handle('desktop:set-state',(event,value)=>{if(!isMain(event))return false;state=normalizeState(value?.state);refreshTray();return true;});
ipcMain.handle('desktop:pick-text',async event=>{
  if(!isMain(event))return {ok:false,reason:'unavailable'};
  const picked=await dialog.showOpenDialog(win,{title:'选择一份文本资料，只读',properties:['openFile'],filters:[{name:'文本资料',extensions:['md','markdown','txt','json']}]});
  if(picked.canceled||!picked.filePaths.length)return {ok:false,reason:'canceled'};
  if(!isMain(event))return {ok:false,reason:'unavailable'};
  return readTextFile(picked.filePaths[0]);
});
ipcMain.handle('desktop:panel-data',event=>isPanel(event)?summary():null);
ipcMain.handle('desktop:panel-command',(event,value)=>{
  if(!isPanel(event))return false;
  if(value?.action==='pause'){pause();return true;}
  if(value?.action==='resume'){resume();return true;}
  if(value?.action==='hide'){panel.hide();return true;}
  const command=validCommand(value);if(!command)return false;
  panel.hide();emit(command);return true;
});
ipcMain.handle('desktop:notify-task',async(event,actionId)=>{
  if(!isMain(event)||typeof actionId!=='string'||actionId.length>128)return {ok:false};
  return legacyNotificationResult();
});
ipcMain.handle('desktop:proactive-changed',event=>{if(!isMain(event))return false;closeFollowupNotices();return true;});
function showFollowupNotice(options,{expiresAt}={}){
  const note=new Notification(options);activeNotifications.add(note);
  const remaining=Date.parse(expiresAt)-Date.now();
  const expiry=Number.isFinite(remaining)?setTimeout(()=>{try{note.close();}catch(_){}},Math.max(0,Math.min(remaining,24*60*60*1000))):null;
  note.once('close',()=>{if(expiry)clearTimeout(expiry);});
  note.on('click',()=>emit({action:'today'}));
  note.once('close',()=>activeNotifications.delete(note));note.once('failed',()=>activeNotifications.delete(note));
  try{note.show();}catch(error){activeNotifications.delete(note);throw error;}
}
if(!app.requestSingleInstanceLock())app.quit();
else{
  app.on('second-instance',()=>emit({action:'chat'}));
  app.whenReady().then(async()=>{
    if(process.platform==='win32')app.setAppUserModelId('cn.xinji.echo.local');
    readPreferences();
    connectionStore=selectionStore(app.getPath('userData'));
    selectionFlow=createSelectionFlow({save:value=>connectionStore.save(value),activate:activateSpace});
    const saved=connectionStore.load();
    createTray();
    try{
      if(saved?.invalid)openSelector('本机连接选择无法核对，尚未打开任何空间。请明确选择。');
      else if(saved?.mode==='shared'){selected=saved;mode='shared';const ticket=connectionEpoch;try{const verified=await probeService(saved.origin,{expected:saved});if(ticket===connectionEpoch)await activateSpace(verified);}catch(_){if(ticket===connectionEpoch)openSelector('上次的服务离线或身份已变，请重新核对。不会自动切回空空间。');}}
      else await activateSpace({version:1,mode:'own'});
    }catch(error){if(!quitting)openSelector(error.message+' 可以显式选择已经启动的本机服务；没有自动更换端口。');}
    if(quitting)return;
    sharedTimer=setInterval(()=>void verifyCurrentShared(),20000);sharedTimer.unref();
    shortcutAvailable=globalShortcut.register('Alt+Space',()=>togglePanel('quick'));
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      {label:'回响',submenu:[{role:'about'},{label:'唤起输入条',click:()=>togglePanel('quick')},{label:'设置',accelerator:'CmdOrCtrl+,',click:()=>emit({action:'settings'})},{label:'连接与空间…',accelerator:'CmdOrCtrl+Shift+L',click:()=>openSelector()},{type:'separator'},{role:'hide'},{role:'quit'}]},
      {role:'editMenu'},{role:'viewMenu'},{role:'windowMenu'}]));
    app.on('activate',()=>{if(mode==='shared'&&!leaseFor(selected)?.active)openSelector();else if(!win&&mode==='own')createWindow();else if(win)revealWindow(win);else openSelector();});
  });
  app.on('window-all-closed',()=>{if(process.platform!=='darwin')app.quit();});
  app.on('will-quit',()=>globalShortcut.unregister('Alt+Space'));
  app.on('before-quit',()=>{quitting=true;if(sharedTimer)clearInterval(sharedTimer);if(notificationTimer)clearInterval(notificationTimer);closeFollowupNotices();pendingOwnBackend?.stop();backend?.stop();tray?.destroy();});
}
