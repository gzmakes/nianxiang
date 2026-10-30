const $=s=>document.querySelector(s);
const tray=new URLSearchParams(location.search).get('mode')==='tray';
$('#tray').hidden=!tray;$('#quick').hidden=tray;
$('#close').onclick=()=>window.xinjiPanel.command({action:'hide'});
$('#pause').onclick=()=>window.xinjiPanel.command({action:'pause'});
$('#resume').onclick=()=>window.xinjiPanel.command({action:'resume'});
document.querySelectorAll('[data-open]').forEach(button=>button.onclick=()=>window.xinjiPanel.command({action:button.dataset.open}));
$('#draft-form').onsubmit=async event=>{event.preventDefault();const text=$('#draft').value.trim();if(text)await window.xinjiPanel.command({action:'draft',text});};
document.addEventListener('keydown',event=>{if(event.key==='Escape')window.xinjiPanel.command({action:'hide'});});
window.xinjiPanel.summary().then(data=>{
 if(!data)return;$('#status').textContent=data.label;
 $('#one-thing').textContent=data.error||(data.item?data.item.title:'现在没有待确认的事项。');
 $('#see-task').hidden=!data.item;
 const paused=Date.parse(data.pausedUntil||'')>Date.now();$('#pause').hidden=paused;$('#resume').hidden=!paused;
}).catch(()=>{$('#status').textContent='暂时无法读取状态';$('#one-thing').textContent='可以打开回响后重试。';});
