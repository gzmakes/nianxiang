// Deliberately no file picker, notification, state update or owner IPC bridge.
const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('xinjiDesktop',{
 openConnectionSettings:()=>ipcRenderer.invoke('desktop:open-connections'),
  info:()=>ipcRenderer.invoke('desktop:shared-info'),
 onCommand:callback=>{if(typeof callback!=='function')return()=>{};const listener=(_,value)=>callback(value);ipcRenderer.on('desktop:command',listener);return()=>ipcRenderer.removeListener('desktop:command',listener)},
});
