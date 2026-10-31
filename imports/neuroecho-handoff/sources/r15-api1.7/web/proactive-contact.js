/* A passive list is not a contact. Only an explicit window may create a banner/OS attempt. */
window.XinjiProactiveContact = {create({api,getSessionId}) {
  const rules=window.XinjiContactContract,storageKey='xinji_contact_attempts_v1';
  let host=null,notice=null,running=true,busy=false,epoch=0,active=null,expiryTimer=null;
  const attempted=new Set();
  try{for(const key of JSON.parse(localStorage.getItem(storageKey)||'[]'))if(typeof key==='string')attempted.add(key);}catch(_){}
  function hide(){if(expiryTimer)clearTimeout(expiryTimer);expiryTimer=null;host?.remove();host=null;try{notice?.close();}catch(_){}notice=null;active=null;}
  function invalidate(){epoch++;hide();}
  const unsubscribe=window.XinjiCompanionBoundary?.subscribe(invalidate);
  const desktop=()=>!!window.xinjiDesktop;
  function current(ticket,sid,hidden){return running&&epoch===ticket&&getSessionId()===sid&&document.hidden===hidden;}
  function reserveLocal(item){
    const key=rules.identity(item);if(attempted.has(key))return false;
    attempted.add(key);try{const value=JSON.stringify([...attempted]);localStorage.setItem(storageKey,value);return localStorage.getItem(storageKey)===value;}catch(_){return false;}
  }
  async function refresh(){
    if(!running||busy)return;
    const sid=getSessionId();if(!sid){invalidate();return;}
    const hidden=document.hidden;
    if(hidden&&(desktop()||!globalThis.Notification||globalThis.Notification.permission!=='granted')){invalidate();return;}
    busy=true;const ticket=epoch;
    try{
      const caps=await api('/api/capabilities');if(!current(ticket,sid,hidden))return;
      if(!rules.supported(caps)){hide();return;}
      const boundary=await api('/api/companion-boundary?session_id='+encodeURIComponent(sid));
      if(!current(ticket,sid,hidden))return;
      if(!rules.validBoundary(boundary)||boundary.mode!=='active'){hide();return;}
      const settings=await api('/api/followup-notification-settings?session_id='+encodeURIComponent(sid));
      if(!current(ticket,sid,hidden)||!Number.isSafeInteger(settings?.revision)||settings.revision<0){hide();return;}
      const list=await api('/api/followups?session_id='+encodeURIComponent(sid));
      if(!current(ticket,sid,hidden))return;
      const items=(Array.isArray(list.followups)?list.followups:[]).filter(item=>rules.eligible(item,sid)&&item.boundary_revision===boundary.revision);
      if(active){const live=items.find(item=>rules.identity(item)===rules.identity(active.item));if(!live||active.revision!==boundary.revision||active.settingsRevision!==settings.revision)hide();else return;}
      if(hidden&&settings.enabled!==true)return;
      const item=items.find(value=>!attempted.has(rules.identity(value)));if(!item)return;
      if(!reserveLocal(item))return; // failed durable ledger: never issue an untracked attempt
      const channel=hidden?'system':'in_app';
      const claim=await api('/api/followups/'+encodeURIComponent(item.id)+'/contact/claim',{method:'POST',body:JSON.stringify({session_id:sid,occurrence_at:item.due_at,channel})});
      if(!current(ticket,sid,hidden)||!rules.claimMatches(claim,item,channel))return;
      const check=await api('/api/followup-contacts/'+encodeURIComponent(claim.claim_id)+'/recheck',{method:'POST',body:JSON.stringify({session_id:sid})});
      if(!current(ticket,sid,hidden)||!rules.recheckMatches(check,claim,item,channel)||!rules.eligible(item,sid))return;
      active={item,revision:boundary.revision,settingsRevision:settings.revision};
      expiryTimer=setTimeout(hide,Math.max(0,Date.parse(item.contact_expires_at)-Date.now()));
      if(hidden){
        if(globalThis.Notification.permission!=='granted'||desktop())return;
        notice=new globalThis.Notification('回响 · 有一条你留下的跟进',{body:'方便的时候，打开回响看看。',silent:true,tag:'xinji-contact-'+claim.claim_id});
        notice.onclick=()=>{try{globalThis.focus();}catch(_){}hide();};
      }else{
        host=document.createElement('aside');host.className='followup-reminder';host.setAttribute('role','status');host.setAttribute('aria-live','polite');
        const title=document.createElement('strong');title.textContent='你留的那件事，要看看吗？';
        const content=document.createElement('p');content.textContent=item.content;
        const hint=document.createElement('small');hint.textContent='不急。事项一直留在 Today，不用现在处理。';
        const dismiss=document.createElement('button');dismiss.type='button';dismiss.textContent='先收起';dismiss.onclick=hide;
        host.append(title,content,hint,dismiss);document.body.append(host);
        window.NianxiangSound?.play('notify');
      }
      // submitted describes this local presentation call, never delivery/read/task completion.
      void api('/api/followup-contacts/'+encodeURIComponent(claim.claim_id)+'/finish',{method:'POST',body:JSON.stringify({session_id:sid,state:'submitted'})}).catch(()=>{});
    }catch(_){if(current(ticket,sid,hidden))hide();}finally{busy=false;}
  }
  function visibility(){invalidate();if(!document.hidden)void refresh();}
  document.addEventListener('visibilitychange',visibility);
  function pagehide(event){invalidate();if(!event.persisted)stop();}
  function pageshow(event){if(event.persisted)void refresh();}
  window.addEventListener('pagehide',pagehide);window.addEventListener('pageshow',pageshow);
  const timer=setInterval(refresh,30000);
  function stop(){running=false;invalidate();clearInterval(timer);unsubscribe?.();document.removeEventListener('visibilitychange',visibility);window.removeEventListener('pagehide',pagehide);window.removeEventListener('pageshow',pageshow);}
  void refresh();return {refresh,stop,invalidate};
}};
