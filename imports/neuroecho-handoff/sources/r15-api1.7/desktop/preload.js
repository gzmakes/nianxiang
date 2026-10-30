const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('xinjiDesktop',{
  openConnectionSettings:()=>ipcRenderer.invoke('desktop:open-connections'),
  info:()=>ipcRenderer.invoke('desktop:info'),
  pickText:()=>ipcRenderer.invoke('desktop:pick-text'),
  updateState:value=>ipcRenderer.invoke('desktop:set-state',{state:value?.state}),
  proactiveChanged:()=>ipcRenderer.invoke('desktop:proactive-changed'),
  notifyTask:actionId=>ipcRenderer.invoke('desktop:notify-task',actionId),
  onCommand:callback=>{
    if(typeof callback!=='function')return ()=>{};
    const listener=(_,value)=>callback(value);ipcRenderer.on('desktop:command',listener);
    return ()=>ipcRenderer.removeListener('desktop:command',listener);
  },
});
