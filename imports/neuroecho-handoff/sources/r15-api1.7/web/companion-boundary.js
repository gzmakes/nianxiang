/* Explicit, revision-checked companion controls. Reading never claims a contact. */
window.XinjiCompanionBoundary = (() => {
  const copy=(key,fallback)=>window.EchoShared?.copy?.[key] ?? fallback;
  const listeners=new Set(),controllers=new Set();
  function invalidate(){for(const callback of listeners)callback();try{window.xinjiDesktop?.proactiveChanged?.();}catch(_){}}
  function subscribe(callback){listeners.add(callback);return()=>listeners.delete(callback);}
  function create({api,getSessionId,host}) {
    let sid=null,boundary=null,capabilities=null,busy=false,epoch=0,status='我在，聊天照常。';
    if(!host)return {refresh:async()=>{},stop(){},capabilities:()=>capabilities};
    host.innerHTML='<span class="companion-boundary-copy" data-b-copy role="status">我在，聊天照常。</span><div class="companion-boundary-actions"><button type="button" class="text-btn" data-b-today>今天先安静</button><button type="button" class="text-btn" data-b-pause>暂停关心</button><button type="button" class="text-btn" data-b-resume hidden>恢复关心</button><button type="button" class="text-btn" data-b-refresh aria-label="重新核对陪伴设置">核对</button></div>';
    const $=s=>host.querySelector(s);
    host.setAttribute?.('aria-label',copy('companion.boundary.title','按你的节奏'));
    for(const [action,key,fallback] of [['today','companion.boundary.today','今天先安静'],['pause','companion.boundary.pause','暂停轻问'],['resume','companion.boundary.resume','恢复按约定轻问']]) $('[data-b-'+action+']').textContent=copy(key,fallback);
    function render(){
      const ready=window.XinjiContactContract.supported(capabilities) && window.XinjiContactContract.validBoundary(boundary);
      $('[data-b-copy]').textContent=status;
      for(const key of ['today','pause','resume'])$('[data-b-'+key+']').disabled=busy||!ready;
      $('[data-b-resume]').hidden=!ready||boundary.mode==='active';
      $('[data-b-pause]').hidden=ready&&boundary.mode!=='active';
    }
    function canRefresh(){return !busy;}
    function acceptSnapshot(value,current=getSessionId()){
      if(busy || !current || getSessionId()!==current || !window.XinjiContactContract.validBoundary(value))return false;
      epoch++;sid=current;
        if(boundary && boundary.revision!==value.revision)invalidate();
        boundary=value;status=value.mode==='active'?copy('companion.boundary.title','按你的节奏')+' · '+copy('companion.boundary.active','只在你约定的窗口里轻问'):value.mode==='paused'?'先不主动问你，需要时随时聊。':'先安静到 '+new Date(value.until).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})+'，聊天照常。';render();
      return true;
    }
    async function refresh(){
      const current=getSessionId();if(!current||busy)return;
      const ticket=++epoch;if(sid!==current){sid=current;boundary=null;invalidate();}
      try{
        const cap=await api('/api/capabilities');if(ticket!==epoch||getSessionId()!==current)return;capabilities=cap;
        if(!window.XinjiContactContract.supported(cap)){boundary=null;status='当前服务暂不支持关心设置，聊天照常。';render();return;}
        const value=await api('/api/companion-boundary?session_id='+encodeURIComponent(current));
        if(ticket!==epoch||getSessionId()!==current)return;
        if(!window.XinjiContactContract.validBoundary(value))throw Error('设置回执不完整');
        acceptSnapshot(value,current);
      }catch(_){if(ticket===epoch&&getSessionId()===current){boundary=null;status='暂时没能核对关心设置。聊天和已留的事项还在。';render();}}
    }
    async function change(mode,until=null){
      if(busy||!window.XinjiContactContract.supported(capabilities)||!window.XinjiContactContract.validBoundary(boundary)||getSessionId()!==sid)return;
      const before=boundary,current=sid,ticket=++epoch;
      const confirm=await window.XinjiDialogs?.confirm?.({title:mode==='active'?'恢复轻声关心？':mode==='until'?'今天先安静？':'暂停主动关心？',message:mode==='active'?'只允许之后重新约定的轻问，旧许可不会恢复。待办仍可查看；系统通知仍需另外开启。':copy('companion.boundary.effect','已有轻问许可会失效，之后需重新约定；聊天和待办仍可查看。')+' 已显示的信息可能已经被看见，无法保证收回。',confirmLabel:mode==='active'?'好，恢复':mode==='until'?'今天先安静':'先暂停'});
      if(!confirm||ticket!==epoch||getSessionId()!==current)return;
      busy=true;status='正在核对设置…';invalidate();render();
      try{
        const body={session_id:current,expected_revision:before.revision,confirmed:true,mode,until,time_zone:window.XinjiContactContract.timeZone()};
        const value=await api('/api/companion-boundary',{method:'PUT',body:JSON.stringify(body)});
        if(ticket!==epoch||getSessionId()!==current)return;
        if(!window.XinjiContactContract.validBoundary(value)||value.mode!==mode||value.revision<=before.revision)throw Error('回执不完整');
        boundary=value;invalidate();
      }catch(error){if(ticket===epoch&&getSessionId()===current)status=error.status===409?'别处已改过设置。这次没有覆盖，请核对后再决定。':'设置结果待核对；不会自动重试。';}
      finally{busy=false;render();}
      if(ticket===epoch){const previous=status;await refresh();if(previous.includes('覆盖')||previous.includes('待核对')){$('[data-b-copy]').textContent=previous;}}
    }
    $('[data-b-today]').onclick=()=>{const until=new Date();until.setHours(24,0,0,0);return change('until',until.toISOString());};
    $('[data-b-pause]').onclick=()=>change('paused');$('[data-b-resume]').onclick=()=>change('active');$('[data-b-refresh]').onclick=refresh;
    function visibility(){epoch++;invalidate();if(!document.hidden)void refresh();}
    document.addEventListener('visibilitychange',visibility);window.addEventListener('pagehide',visibility);
    const timer=setInterval(()=>{if(!document.hidden)void refresh();},30000);render();
    const controller={refresh,canRefresh,acceptSnapshot,capabilities:()=>capabilities,stop(){controllers.delete(controller);epoch++;clearInterval(timer);document.removeEventListener('visibilitychange',visibility);window.removeEventListener('pagehide',visibility);}};controllers.add(controller);return controller;
  }
  return {create,invalidate,subscribe,refreshAll:()=>Promise.all([...controllers].map(value=>value.refresh()))};
})();
