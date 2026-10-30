const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('xinjiConnectionSelector',{
 status:()=>ipcRenderer.invoke('connection:status'),verify:origin=>ipcRenderer.invoke('connection:verify',origin),
 connect:value=>ipcRenderer.invoke('connection:connect',value),own:()=>ipcRenderer.invoke('connection:own',{confirmed:true}),
 invalidate:()=>ipcRenderer.invoke('connection:invalidate'),close:()=>ipcRenderer.invoke('connection:close'),
});
