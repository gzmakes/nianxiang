const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('xinjiPanel',{
  summary:()=>ipcRenderer.invoke('desktop:panel-data'),
  command:value=>ipcRenderer.invoke('desktop:panel-command',value),
});
