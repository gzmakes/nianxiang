const {fileURLToPath}=require('node:url');
const {sameOrigin}=require('./service-connection');
function mainFrame(event,window){return !!window&&!window.isDestroyed()&&event?.sender===window.webContents&&event.senderFrame===window.webContents.mainFrame}
function ownerIPC(event,window,mode,origin){return mode==='own'&&mainFrame(event,window)&&sameOrigin(event.senderFrame.url,origin)}
function sharedIPC(event,window,mode,origin){return mode==='shared'&&mainFrame(event,window)&&sameOrigin(event.senderFrame.url,origin)}
function fileIPC(event,window,target){if(!mainFrame(event,window))return false;try{const url=new URL(event.senderFrame.url);return !url.search&&!url.hash&&fileURLToPath(url)===target}catch(_){return false}}
function hardenSharedSession(session){
 session.setPermissionRequestHandler((_window,_permission,callback)=>callback(false));session.setPermissionCheckHandler(()=>false);
 session.setDevicePermissionHandler?.(()=>false);session.on('will-download',event=>event.preventDefault());
}
module.exports={mainFrame,ownerIPC,sharedIPC,fileIPC,hardenSharedSession};
