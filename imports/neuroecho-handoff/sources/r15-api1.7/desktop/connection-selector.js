'use strict';
const api=window.xinjiConnectionSelector,$=id=>document.getElementById(id);let candidate=null,busy=false,epoch=0;
function state(text){$('status').textContent=text}
function render(){for(const id of ['origin','verify','own'])$(id).disabled=busy;$('connect').disabled=busy||!candidate||!$('confirm').checked}
function invalid(){epoch++;candidate=null;$('confirm').checked=false;$('review').hidden=true;void api.invalidate();render()}
$('origin').addEventListener('input',invalid);$('confirm').addEventListener('change',render);
$('verify').onclick=async()=>{if(busy)return;const ticket=++epoch;candidate=null;$('review').hidden=true;$('confirm').checked=false;busy=true;render();state('只核对这个地址的服务身份…');try{const result=await api.verify($('origin').value);if(ticket!==epoch||!result?.ok)return;candidate=result;$('review-origin').textContent=result.origin;$('review-version').textContent='API '+result.contract_version;$('review').hidden=false;state('已核对。请读完范围后，由你决定是否连接。')}catch(error){if(ticket===epoch)state(error.message||'暂时没能核对。尚未切换空间。')}finally{if(ticket===epoch){busy=false;render()}}};
$('connect').onclick=async()=>{if(busy||!candidate||!$('confirm').checked)return;busy=true;render();state('正在再次核对同一服务与同一对话…');try{const ok=await api.connect({nonce:candidate.nonce,origin:$('origin').value,confirmed:true});if(ok!==true)throw Error('这次选择已经变化，请重新核对。')}catch(error){state(error.message||'尚未切换，原空间仍保留。');busy=false;render()}};
$('own').onclick=async()=>{if(busy)return;busy=true;render();state('正在打开原来的本机空间…');try{await api.own()}catch(error){state(error.message||'原空间暂时无法打开，数据仍保留。');busy=false;render()}};
$('close').onclick=()=>api.close();
void api.status().then(value=>{if(value?.selection?.mode==='shared')$('origin').value=value.selection.origin;state(value?.message||'选择已有本机服务，或者继续桌面原来的空间。');render()}).catch(()=>state('暂时没能读取连接选择。原空间没有被修改。'));
