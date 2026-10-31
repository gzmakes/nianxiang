/* Device-only presentation preferences. No model, account or conversation writes. */
(() => {
  const key = 'xinji_ui_settings_v1';
  const defaults = window.EchoShared?.defaults || {reduceMotion:false, reduceTransparency:false, lightIntensity:.7};
  const listeners = new Set();
  const media = (query) => typeof matchMedia === 'function' ? matchMedia(query) : {matches:false};
  const motion = media('(prefers-reduced-motion: reduce)'), transparency = media('(prefers-reduced-transparency: reduce)');
  function clean(value={}) { return {reduceMotion:value.reduceMotion === true, reduceTransparency:value.reduceTransparency === true, lightIntensity:Number.isFinite(Number(value.lightIntensity)) ? Math.max(0,Math.min(1,Number(value.lightIntensity))) : defaults.lightIntensity}; }
  function read() { try { return clean(JSON.parse(localStorage.getItem(key) || 'null') || defaults); } catch (_) { return {...defaults}; } }
  let settings = read();
  function apply() {
    const root = document.documentElement;
    root.dataset.reduceMotion = String(motion.matches || settings.reduceMotion);
    root.dataset.reduceTransparency = String(transparency.matches || settings.reduceTransparency);
    root.style.setProperty('--echo-light-intensity', settings.lightIntensity);
    listeners.forEach(fn => fn({...settings}));
  }
  function updateSettings(patch) { settings=clean({...settings,...patch}); try {localStorage.setItem(key,JSON.stringify(settings));}catch(_){} apply(); return {...settings}; }
  motion.addEventListener?.('change',apply); transparency.addEventListener?.('change',apply);
  window.addEventListener('storage',event=>{if(event.key===key){settings=read();apply();}});
  const lightMarkup = '<span class="presence-light" role="img" aria-label="状态光：状态同时以文字显示"><span class="presence-light-core"></span></span>';
  const escape = (value) => String(value ?? '').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  function searchRecords(state,query) {
    const term=String(query||'').trim().toLocaleLowerCase();
    if(!term) return [];
    return [...(state.messages||[]).map(item=>({...item,type:'message'})), ...(state.memories||[]).filter(item=>item.status!=='deleted').map(item=>({...item,type:'memory'}))]
      .filter(item=>String(item.text||'').toLocaleLowerCase().includes(term)).slice(0,60).map(item=>({id:item.id,type:item.type,text:item.text,role:item.role,status:item.status,kind:item.kind}));
  }
  function createTopics(storage) {
    if (!storage) { try { storage=localStorage; } catch (_) { storage={getItem:()=>null,setItem(){}}; } }
    const topicKey='xinji_topic_views_v1'; let assignments={};
    try {const saved=JSON.parse(storage.getItem(topicKey)||'{}');if(saved && typeof saved==='object' && !Array.isArray(saved)) assignments=Object.fromEntries(Object.entries(saved).filter(([id,label])=>id && typeof label==='string' && label.length<=20));}catch(_){}
    const get=id=>assignments[id] || '日常';
    return {get,list:()=>['日常',...new Set(Object.values(assignments).filter(label=>label!=='日常'))],matches:(id,filter)=>filter==='全部'||get(id)===filter,
      assign(id,label){label=String(label||'日常').trim();if(!id || !label || label==='全部' || label.length>20)return false;assignments[id]=label;try{storage.setItem(topicKey,JSON.stringify(assignments));}catch(_){}return true;}};
  }
  function mountSettings(container) {
    container._designDispose?.();
    container.innerHTML='<div class="design-settings"><h3>显示与动效</h3><label class="design-toggle"><span><b>减少动态</b><small>系统开启时始终生效。</small></span><input type="checkbox" data-design-motion></label><label class="design-toggle"><span><b>降低透明度</b><small>操作层改为接近不透明的白色。</small></span><input type="checkbox" data-design-transparency></label><label class="design-light-control"><span>光的强度</span><input type="range" min="0" max="1" step="0.05" data-design-light aria-label="光的强度"></label><p class="note">这些偏好只保存在本设备，不改变记忆或模型。</p></div>';
    const m=container.querySelector('[data-design-motion]'),t=container.querySelector('[data-design-transparency]'),l=container.querySelector('[data-design-light]');
    const sync=()=>{m.checked=settings.reduceMotion;t.checked=settings.reduceTransparency;l.value=settings.lightIntensity;};
    m.onchange=()=>updateSettings({reduceMotion:m.checked});t.onchange=()=>updateSettings({reduceTransparency:t.checked});l.oninput=()=>updateSettings({lightIntensity:Number(l.value)});
    listeners.add(sync);container._designDispose=()=>listeners.delete(sync);sync();
  }
  function createWorkspace({getState,onJump,fallbackFocus,backgrounds=[]}) {
    const topics=createTopics();let selected='全部',topicContainer=null;
    const dialog=document.createElement('section');dialog.className='design-search is-hidden';dialog.setAttribute('role','dialog');dialog.setAttribute('aria-modal','true');dialog.setAttribute('aria-label','搜索当前对话和记忆');
    dialog.innerHTML='<div class="design-search-card"><div class="design-search-head"><input type="search" placeholder="搜索这段对话和记忆" aria-label="搜索当前对话和记忆"><button type="button" class="icon-btn" data-search-close aria-label="关闭搜索">×</button></div><p class="note">只搜索当前已加载的对话与记忆，不上传搜索词。</p><div class="design-search-results" aria-live="polite"></div></div>';
    document.body.appendChild(dialog);
    const input=dialog.querySelector('input'),results=dialog.querySelector('.design-search-results');
    const controller=window.XinjiWelcome.create({dialog,backgrounds,storageKey:null,fallbackFocus,closeButtons:[dialog.querySelector('[data-search-close]')]});
    const refreshSearch=()=>{const records=searchRecords(getState(),input.value);results.innerHTML=records.length?records.map((item,index)=>`<button type="button" data-search-result="${index}"><span>${item.type==='memory'?(item.kind==='inference'&&item.status!=='confirmed'?'推测 · 待确认':item.status==='confirmed'?'已确认记忆':'待确认记忆'):item.role==='user'?'你说过':'回响'}</span><p>${escape(item.text)}</p></button>`).join(''):`<p class="note">${input.value.trim()?'没有匹配的记录。':'输入关键词，从已有记录中查找。'}</p>`;results.querySelectorAll('[data-search-result]').forEach(button=>button.onclick=()=>{const item=records[Number(button.dataset.searchResult)];controller.close({remember:false});setTopic('全部');onJump(item);});};
    input.oninput=refreshSearch;
    function openSearch(){if(document.querySelector('dialog[open], [aria-modal="true"]:not(.is-hidden):not(.design-search)'))return false;refreshSearch();controller.open();input.focus();return true;}
    function mountTopics(container){topicContainer=container;const labels=['全部',...topics.list()];container.innerHTML=labels.map(label=>`<button type="button" class="topic-chip ${selected===label?'active':''}" data-topic-filter="${escape(label)}" aria-pressed="${selected===label}">${escape(label)}</button>`).join('');container.querySelectorAll('[data-topic-filter]').forEach(button=>button.onclick=()=>setTopic(button.dataset.topicFilter));}
    function filterMessages(container){container.querySelectorAll('[data-message-id]').forEach(element=>element.classList.toggle('is-topic-hidden',!topics.matches(element.dataset.messageId,selected,element)));}
    function setTopic(label){selected=label; if(topicContainer)mountTopics(topicContainer);document.dispatchEvent(new CustomEvent('xinji-topic-change',{detail:{topic:selected}}));}
    async function tag(id){if(String(id).startsWith('local-'))return;const label=await window.XinjiDialogs.prompt({title:'标记话题',message:'仅本设备的视图分类，不是个人记忆，也不会建立新对话。',value:topics.get(id),maxLength:20});if(label!==null && topics.assign(id,label)){if(topicContainer)mountTopics(topicContainer);setTopic(String(label || "日常").trim());}}
    document.addEventListener('keydown',event=>{if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){event.preventDefault();openSearch();}});
    document.addEventListener('click',event=>{const button=event.target.closest('[data-topic-message]');if(button)tag(button.dataset.topicMessage);});
    return {openSearch,mountTopics,filterMessages,setTopic,topics};
  }
  function applyCopy(root = document) { (root.querySelectorAll?.('[data-copy-key]') || []).forEach(element => { const text = window.EchoShared?.copy?.[element.dataset.copyKey]; if (typeof text === 'string') element.textContent = text; }); }
  window.XinjiDesign={applyCopy,getSettings:()=>({...settings}),updateSettings,subscribe(fn){listeners.add(fn);return()=>listeners.delete(fn);},lightMarkup,mountSettings,createTopics,searchRecords,createWorkspace};
  applyCopy();
  apply();
})();
