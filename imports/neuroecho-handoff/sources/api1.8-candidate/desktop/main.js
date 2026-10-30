const {app,BrowserWindow,ipcMain,dialog,Tray,Menu,nativeImage,globalShortcut,screen,shell,Notification} = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const {randomUUID} = require('node:crypto');
const {fileURLToPath}=require('node:url');
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
let prefs={pausedUntil:null,snoozed:{},notificationAttempts:[],contactAttempts:[]}; let preferencesPath;
let notifier=null,notificationTimer=null;
const activeNotifications=new Set();
let shortcutAvailable=false;
const origin=()=>`http://127.0.0.1:${port}`;
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
function isMain(event){
  if (!win || event.sender!==win.webContents || event.senderFrame!==win.webContents.mainFrame) return false;
  try{return new URL(event.senderFrame.url).origin===origin();}catch(_){return false;}
}
function isPanelURL(url){try{return fileURLToPath(new URL(url))===path.join(__dirname,'panel.html');}catch(_){return false;}}
function isPanel(event){return !!panel && event.sender===panel.webContents && event.senderFrame===panel.webContents.mainFrame && isPanelURL(event.senderFrame.url);}
function external(url){try { const u=new URL(url);if(u.protocol==='https:'&&!u.username&&!u.password)shell.openExternal(u.href); }catch(_) {}}
function secureWindow(window, main=false){
  window.webContents.setWindowOpenHandler(({url})=>{external(url);return {action:'deny'};});
  window.webContents.on('will-navigate',(event,url)=>{
    let allow=false;try{allow=main?new URL(url).origin===origin():isPanelURL(url);}catch(_){}
    if(!allow){event.preventDefault();external(url);}
  });
}
function emit(command){
  if(!win)createWindow();
  revealWindow(win);
  if(ready)win.webContents.send('desktop:command',command);
  else win.webContents.once('did-finish-load',()=>win?.webContents.send('desktop:command',command));
}
function emitQuiet(){if(win&&ready)win.webContents.send('desktop:command',{action:'quiet',pausedUntil:prefs.pausedUntil});refreshTray();}
function pause(){closeFollowupNotices();prefs.pausedUntil=tomorrowAtNine();savePreferences();emitQuiet();panel?.hide();}
function resume(){closeFollowupNotices();prefs.pausedUntil=null;savePreferences();emitQuiet();panel?.hide();}
function createWindow(){
  ready=false;
  win=new BrowserWindow({width:1000,height:830,minWidth:780,minHeight:640,title:'回响',show:false,
    icon:path.join(__dirname,'assets','echo.png'),
    backgroundColor:'#EDF1FF',titleBarStyle:process.platform==='win32'?'hidden':'hiddenInset',trafficLightPosition:{x:18,y:20},
    titleBarOverlay:process.platform==='win32'?{color:'#EDF1FF',symbolColor:'#1B2433',height:48}:undefined,
    backgroundMaterial:process.platform==='win32'?'mica':undefined,
    vibrancy:process.platform==='darwin'?'under-window':undefined,visualEffectState:'followWindow',
    webPreferences:{preload:path.join(__dirname,'preload.js'),contextIsolation:true,nodeIntegration:false,sandbox:true}});
  secureWindow(win,true);
  win.on('focus',closeFollowupNotices);
  const currentWindow=win;
  win.once('ready-to-show',()=>revealWindow(currentWindow));
  win.webContents.on('did-fail-load',(_,code,description,url,isMainFrame)=>{
    if(code===-3 || isMainFrame===false || currentWindow.isDestroyed())return;
    revealWindow(currentWindow);
    dialog.showErrorBox('回响界面未能载入',`本机界面暂时无法载入（${code}）。对话数据仍保留。请确认本机服务可用后，在窗口按 ${process.platform==='darwin'?'⌘R':'Ctrl+R'} 重试。`);
  });
  win.webContents.on('render-process-gone',()=>{
    if(currentWindow.isDestroyed())return;
    revealWindow(currentWindow);
    dialog.showErrorBox('回响界面需要重新载入',`界面进程已停止，对话数据仍保留。请在窗口按 ${process.platform==='darwin'?'⌘R':'Ctrl+R'} 重新载入。`);
  });
  win.webContents.on('did-finish-load',()=>{ready=true;emitQuiet();});
  win.loadURL(`${origin()}/?desktop=1`);
  win.on('closed',()=>{win=null;ready=false;});
}
function refreshTray(){
  if(!tray)return;
  const value=effectiveState(state,prefs.pausedUntil),icon=nativeImage.createFromPath(path.join(__dirname,'assets',`tray-${value==='failed'?'thinking':value}.png`));
  if(process.platform==='darwin')icon.setTemplateImage(true);
  tray.setImage(process.platform==='win32'?nativeImage.createFromPath(path.join(__dirname,'assets','echo.png')):icon);tray.setToolTip(`回响 · ${stateLabel(state,prefs.pausedUntil)}`);
}
function togglePanel(mode='quick'){
  if(!panel){
    panel=new BrowserWindow({width:640,height:264,frame:false,resizable:false,show:false,alwaysOnTop:true,skipTaskbar:true,backgroundColor:'#EDF1FF',
      vibrancy:process.platform==='darwin'?'popover':undefined,visualEffectState:'active',
      webPreferences:{preload:path.join(__dirname,'panel-preload.js'),contextIsolation:true,nodeIntegration:false,sandbox:true}});
    secureWindow(panel,false);panel.on('blur',()=>panel?.hide());panel.on('closed',()=>{panel=null;});
  }
  if(panel.isVisible()&&panel.mode===mode){panel.hide();return;}
  panel.mode=mode;panel.setSize(mode==='tray'?360:640,mode==='tray'?440:264);
  if(mode==='tray'&&tray){
    const bounds=tray.getBounds(),area=screen.getDisplayMatching(bounds).workArea;
    const x=Math.max(area.x,Math.min(bounds.x+bounds.width/2-180,area.x+area.width-360));
    panel.setPosition(Math.round(x),Math.round(Math.max(area.y,bounds.y+bounds.height+8)));
  }else panel.center();
  panel.loadFile(path.join(__dirname,'panel.html'),{query:{mode}}).then(()=>{panel?.show();panel?.focus();});
}
function createTray(){
  tray=new Tray(nativeImage.createFromPath(path.join(__dirname,'assets','tray-quiet.png')));
  refreshTray();
  tray.on('click',()=>togglePanel('tray'));
  tray.on('right-click',()=>tray.popUpContextMenu(Menu.buildFromTemplate([
    {label:'打开回响',click:()=>emit({action:'chat'})},{label:'唤起输入条',click:()=>togglePanel('quick')},
    {label:'管理跟进通知',click:()=>emit({action:'today'})},{label:'本机系统通知暂停到明天 09:00',click:pause},{label:'恢复本机系统通知',click:resume},{type:'separator'},{label:'退出回响',click:()=>app.quit()}])));
}
async function summary(){
  const out={label:stateLabel(state,prefs.pausedUntil),pausedUntil:prefs.pausedUntil,shortcutAvailable,item:null};
  try{
    const c=await fetch(`${origin()}/api/conversation`,{signal:AbortSignal.timeout(3000)}).then(r=>r.json());
    const a=await fetch(`${origin()}/api/actions?session_id=${encodeURIComponent(c.session.id)}`,{signal:AbortSignal.timeout(3000)}).then(r=>r.json());
    const item=(a.actions||[]).find(x=>x.status==='previewed');
    if(item)out.item={title:String(item.title).slice(0,120),kind:item.kind};
  }catch(_){out.error='暂时没能读取待确认事项，打开回响后可重试。';}
  return out;
}
ipcMain.handle('desktop:info',event=>{if(!isMain(event))throw Error('Unavailable sender');return {platform:process.platform,version:app.getVersion(),native:true,shortcutAvailable,pausedUntil:prefs.pausedUntil,notificationSupported:Notification.isSupported()};});
ipcMain.handle('desktop:set-state',(event,value)=>{if(!isMain(event))return false;state=normalizeState(value?.state);refreshTray();return true;});
ipcMain.handle('desktop:pick-text',async event=>{
  if(!isMain(event))return {ok:false,reason:'unavailable'};
  const picked=await dialog.showOpenDialog(win,{title:'选择一份文本资料，只读',properties:['openFile'],filters:[{name:'文本资料',extensions:['md','markdown','txt','json']}]});
  if(picked.canceled||!picked.filePaths.length)return {ok:false,reason:'canceled'};
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
    try{backend=createBackendLifecycle({root:ROOT,...backendRuntime,python:PYTHON,port:PORT,onStdout:d=>process.stdout.write(d),onStderr:d=>process.stderr.write(d)});port=(await backend.start()).port;}
    catch(error){dialog.showErrorBox('回响暂时无法启动',error.message);app.quit();return;}
    createWindow();createTray();
    notifier=createFollowupNotifier({origin,getPrefs:()=>prefs,savePrefs:savePreferences,request:fetch,
      show:showFollowupNotice,supported:()=>Notification.isSupported(),
      close:closeFollowupNotices,
      isForeground:()=>!!win && !win.isDestroyed() && win.isVisible() && !win.isMinimized() && win.isFocused()});
    void notifier.tick();notificationTimer=setInterval(()=>void notifier.tick(),30000);notificationTimer.unref();
    shortcutAvailable=globalShortcut.register('Alt+Space',()=>togglePanel('quick'));
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      {label:'回响',submenu:[{role:'about'},{label:'唤起输入条',click:()=>togglePanel('quick')},{label:'设置',accelerator:'CmdOrCtrl+,',click:()=>emit({action:'settings'})},{type:'separator'},{role:'hide'},{role:'quit'}]},
      {role:'editMenu'},{role:'viewMenu'},{role:'windowMenu'}]));
    app.on('activate',()=>{if(!win)createWindow();else revealWindow(win);});
  });
  app.on('window-all-closed',()=>{if(process.platform!=='darwin')app.quit();});
  app.on('will-quit',()=>globalShortcut.unregister('Alt+Space'));
  app.on('before-quit',()=>{if(notificationTimer)clearInterval(notificationTimer);closeFollowupNotices();backend?.stop();tray?.destroy();});
}
