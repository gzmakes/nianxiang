/* An optional self-report journal. No automatic chat, memory, diagnosis or contact. */
window.XinjiMood = (() => {
  const copy = (key, fallback) => window.EchoShared?.copy?.[key] ?? fallback;
  const clamp = value => Math.max(-1, Math.min(1, Number(value)));
  const day = date => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
  const point = (clientX,clientY,rect) => ({x:clamp((clientX-rect.left)/rect.width*2-1),y:clamp(1-(clientY-rect.top)/rect.height*2)});
  const axisText = (value, negative, positive) => value < -.2 ? negative : value > .2 ? positive : '中间';
  function moodTint(x,y) { const a=(clamp(x)+1)/2,b=(clamp(y)+1)*.12;return 'rgb('+[198,212,255].map((v,i)=>Math.round((v*(1-a)+[255,217,198][i]*a)*(1-b)+255*b)).join(', ')+')'; }
  const dateValid = value => {try{return /^\d{4}-\d{2}-\d{2}$/.test(value)&&new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;}catch(_){return false;}};
  const coordinate = value => typeof value==='number' && Number.isFinite(value) && value>=-1 && value<=1;
  const version = value => typeof value==='string' && value.length<=64 && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && dateValid(value.slice(0,10)) && Number.isFinite(Date.parse(value));
  const entryValid = value => dateValid(value?.date) && coordinate(value.x) && coordinate(value.y) && typeof value.note==='string' && [...value.note].length<=1000 && version(value.updated_at);
  const sameEntry = (entry,body,date) => entryValid(entry) && entry.date===date && entry.x===body.x && entry.y===body.y && entry.note===body.note;
  function create({api,getSessionId,onContext,surface='web'}) {
    const draftRoot='xinji_mood_draft_v2_'+surface+':', pendingRoot='xinji_mood_pending_v1', pendingPrefix=pendingRoot+':';
    let tabId=null;
    try{const key='xinji_mood_tab_v1_'+surface;tabId=sessionStorage.getItem(key);if(!versionId(tabId)){tabId=crypto.randomUUID();sessionStorage.setItem(key,tabId);if(sessionStorage.getItem(key)!==tabId)throw Error('tab storage unavailable');}}catch(_){tabId=null;}
    const draftPrefix=draftRoot+(tabId||'unavailable')+':';
    function versionId(value){return typeof value==='string'&&value.length>0&&value.length<=128;}

    let host=null,sid=null,generation=0,currentDay=day(new Date()),month=currentDay.slice(0,7),records=[],x=0,y=0,xChosen=false,yChosen=false,versionAtEdit=null,dirty=false,sourceDirty=false,busy=false,loading=false,loaded=false,capabilities=null,pendingChange=null,reviewed=false,latestReview=null;
    const drafts=new Map();
    const $ = selector => host?.querySelector(selector);
    const valid = (ticket,session) => !!host && host.isConnected && ticket===generation && sid===session && getSessionId()===session;
    const supported = () => capabilities?.features?.daily_mood_entries===true;
    const active = () => !!sid && getSessionId()===sid;
    const ledgerSupported = () => supported() && capabilities?.features?.mood_operation_ledger===true;
    const suggestions = () => supported() && capabilities?.features?.mood_self_report_suggestions===true;
    const resource = (session,date) => encodeURIComponent(session)+':'+date;
    function status(text){const el=$('[data-mood-status]');if(el)el.textContent=text;}
    function read(key){const raw=localStorage.getItem(key);return raw?JSON.parse(raw):null;}
    function put(key,value){const text=JSON.stringify(value);localStorage.setItem(key,text);if(localStorage.getItem(key)!==text)throw Error('本机记录未确认');}
    function drop(key){localStorage.removeItem(key);if(localStorage.getItem(key)!=null)throw Error('本机记录未确认');}
    function scan(prefix,session) {
      const found=[];
      for(let i=0;i<localStorage.length;i++){const key=localStorage.key(i);if(key?.startsWith(prefix)){const item=read(key);if(item?.session_id===session)found.push({...item,key});}}
      return found;
    }
    function pendingFor(session,date){try{return scan(pendingRoot,session).find(item=>item.date===date)||null;}catch(_){return {unreadable:true};}}
    function pending(){return pendingFor(sid,currentDay);}
    function snapshot(){return {session_id:sid,date:currentDay,x,y,xChosen,yChosen,versionAtEdit,note:$('[data-mood-note]')?.value||'',source:$('[data-mood-source]')?.value||'',sourceDirty,dirty,tab_id:tabId,at:Date.now()};}
    function checkpoint(){if(!host||!sid||!dirty)return true;const draft=snapshot(),key=resource(sid,currentDay);drafts.set(key,draft);try{if(!tabId)throw Error('tab storage unavailable');put(draftPrefix+key,draft);return true;}catch(_){status('草稿仍在当前页面，暂时无法保存在本机；请先复制文字。尚未提交。');return false;}}
    function draftFor(session,date){const key=resource(session,date);if(drafts.has(key))return drafts.get(key);try{return read(draftPrefix+key);}catch(_){return null;}}
    function sameDraft(a,b){return ['session_id','date','x','y','xChosen','yChosen','versionAtEdit','note','source','sourceDirty','dirty'].every(key=>a?.[key]===b?.[key]);}
    function clearDraft(session,date){const key=resource(session,date);drafts.delete(key);drop(draftPrefix+key);}
    function restoreDraft(draft){if(!draft)return;x=draft.x;y=draft.y;xChosen=draft.xChosen===true;yChosen=draft.yChosen===true;versionAtEdit=draft.versionAtEdit??null;$('[data-mood-note]').value=draft.note||'';$('[data-mood-source]').value=draft.source||'';sourceDirty=draft.sourceDirty===true;dirty=true;}
    function draftValid(value){return value?.session_id===sid && dateValid(value.date) && coordinate(value.x) && coordinate(value.y) && ['xChosen','yChosen','sourceDirty','dirty'].every(key=>typeof value[key]==='boolean') && value.dirty===true && (value.versionAtEdit===null||version(value.versionAtEdit)) && typeof value.note==='string' && [...value.note].length<=1000 && typeof value.source==='string' && [...value.source].length<=1000 && Number.isFinite(value.at) && value.at>0 && Number.isFinite(new Date(value.at).getTime()) && versionId(value.tab_id);}
    function otherDrafts(){
      const found=[];
      for(let i=0;i<localStorage.length;i++){const key=localStorage.key(i);if(!key?.startsWith('xinji_mood_draft_v2_')||key.startsWith(draftPrefix))continue;
        try{const value=read(key);if(draftValid(value)&&key.endsWith(':'+resource(sid,value.date)))found.push({...value,key});}catch(_){}
      }
      return found.sort((a,b)=>b.at-a.at||a.key.localeCompare(b.key));
    }
    function renderDrafts(){
      const list=$('[data-mood-drafts-list]');if(!list)return;list.replaceChildren();let found;
      try{found=otherDrafts();}catch(_){$('[data-mood-drafts-info]').textContent='暂时无法读取本机草稿；当前内容仍保留。';return;}
      $('[data-mood-drafts-info]').textContent=found.length?'选择一份复制到当前页面；不会发送或保存记录，原草稿仍保留。':'没有其他标签页留下的草稿。';
      for(const draft of found){const row=document.createElement('div');row.className='mood-draft-row';const title=document.createElement('b');title.textContent=draft.date;const note=document.createElement('p');note.textContent=[...draft.note||draft.source||'仅调整了位置'].slice(0,80).join('');const time=document.createElement('p');time.textContent='本机草稿 · '+new Date(draft.at).toLocaleString();const restore=document.createElement('button');restore.type='button';restore.textContent=copy('mood.drafts.restore','在本页继续这份草稿');restore.disabled=busy||loading||!loaded||!supported()||!!pending()||!!pendingFor(sid,draft.date);restore.onclick=()=>restoreOtherDraft(draft);row.append(title,note,time,restore);list.append(row);}
    }
    function restoreOtherDraft(candidate){
      if(!active()||busy||loading||!loaded||!supported()||pending()||pendingFor(sid,candidate.date)){status('请先核对这一天的待确认操作；恢复草稿不会替换原请求。');renderDrafts();return;}
      try{const fresh=read(candidate.key);if(!draftValid(fresh)||!sameDraft(fresh,candidate)||fresh.at!==candidate.at){status('这份草稿已经变化，请重新选择。');renderDrafts();return;}
        if(!checkpoint())return;
        if(dirty&&currentDay===fresh.date&&!sameDraft(snapshot(),fresh)){if(!tabId||!crypto?.randomUUID)throw Error('无法保留当前草稿');const saved={...snapshot(),tab_id:'draft-saved-'+crypto.randomUUID()};put(draftRoot+saved.tab_id+':'+resource(sid,currentDay),saved);}
        selectDate(fresh.date,{restore:false});restoreDraft(fresh);if(!checkpoint())return;drawCalendar();updatePoint();renderDrafts();status('已复制到本页，原草稿仍保留。尚未提交，确认后才会记录。');
      }catch(_){status('暂时无法恢复；当前内容和原草稿仍保留，请先复制文字。');}
    }
    const isLedger = op => op?.transport==='mood-ledger-v1';
    const terminal = op => ledgerValid(op)&&receiptValid(op.receipt,op)&&['applied','conflict','cancelled'].includes(op.receipt.state);
    function requestId(value){return typeof value==='string'&&value.length>=8&&value.length<=128&&/^[A-Za-z0-9][A-Za-z0-9._:-]+$/.test(value);}
    async function operationHash(raw){if(!crypto?.subtle?.digest||typeof TextEncoder!=='function')throw Error('当前环境无法核对请求，请使用较新的浏览器。');const bytes=new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw)));return Array.from(bytes,value=>value.toString(16).padStart(2,'0')).join('');}
    function ledgerValid(op){
      if(!isLedger(op)||!pendingValid(op)||!requestId(op.id)||typeof op.operation_json!=='string'||typeof op.cancelRequested!=='boolean')return false;
      try{const inner=JSON.parse(op.operation_json),kind=op.kind==='put'?'save':'delete',keys=kind==='save'?['kind','date','expected_updated_at','x','y','note']:['kind','date','expected_updated_at'];return Object.keys(inner).sort().join()===keys.sort().join()&&inner.kind===kind&&inner.date===op.date&&inner.expected_updated_at===op.body.expected_updated_at&&(inner.expected_updated_at===null||version(inner.expected_updated_at))&&(kind==='save'?coordinate(inner.x)&&coordinate(inner.y)&&typeof inner.note==='string'&&[...inner.note].length<=1000&&inner.x===op.body.x&&inner.y===op.body.y&&inner.note===op.body.note:version(inner.expected_updated_at));}catch(_){return false;}
    }
    async function hashedOperation(op){if(!ledgerValid(op))throw Error('本机请求不完整');const hash=await operationHash(op.operation_json);if(op.operation_sha256!=null&&op.operation_sha256!==hash)throw Error('本机请求校验不一致');if(op.operation_sha256===hash)return op;const saved=read(op.key);if(saved?.id!==op.id||saved.operation_json!==op.operation_json)throw Error('待核对请求已经变化');const next={...saved,operation_sha256:hash};put(op.key,next);return {...next,key:op.key};}
    function receiptValid(receipt,op,{query=false}={}){
      if(!receipt||Object.keys(receipt).length!==6||!['session_id','request_id','operation_sha256','kind','state','result_updated_at'].every(key=>Object.prototype.hasOwnProperty.call(receipt,key))||receipt.session_id!==op.session_id||receipt.request_id!==op.id)return false;
      if(receipt.state==='not_found')return query&&receipt.operation_sha256===null&&receipt.kind===null&&receipt.result_updated_at===null;
      if(typeof receipt.operation_sha256!=='string'||!/^[0-9a-f]{64}$/.test(receipt.operation_sha256)||receipt.operation_sha256!==op.operation_sha256||receipt.kind!==(op.kind==='put'?'save':'delete')||!['applied','conflict','cancelled'].includes(receipt.state))return false;
      if(receipt.state==='cancelled')return receipt.result_updated_at===null;
      if(receipt.state==='conflict')return receipt.result_updated_at===null||version(receipt.result_updated_at);
      return version(receipt.result_updated_at)&&(op.kind==='delete'?receipt.result_updated_at===op.body.expected_updated_at:receipt.result_updated_at!==op.body.expected_updated_at);
    }
    function saveReceipt(op,receipt){const saved=read(op.key);if(saved?.id!==op.id||saved.operation_json!==op.operation_json||saved.operation_sha256!==op.operation_sha256)throw Error('待核对请求已经变化');const next={...saved,state:receipt.state,receipt};put(op.key,next);return {...next,key:op.key};}
    function renderOperation(){
      const op=pending(),box=$('[data-mood-operation]');if(!box)return;box.hidden=!isLedger(op);if(!isLedger(op))return;
      $('[data-mood-operation-original]').textContent=(op.kind==='put'?'记录 ':'删除 ')+op.date+(op.kind==='put'?'\n'+(op.body?.note||'没有附言'):'');
      const state=terminal(op)?op.receipt.state:null,canUse=ledgerSupported()&&ledgerValid(op);$('[data-mood-operation-info]').textContent=state==='applied'?copy('mood.recovery.applied','这次提交已经处理；以当前记录为准，取消不会回滚。'):state==='cancelled'?copy('mood.recovery.cancelled','已确认取消这次提交，草稿还在。'):state==='conflict'?'这次请求遇到版本冲突，没有覆盖已有记录。':op.cancelRequested?'已请求取消；在核对结束前不会再提交此请求。取消只阻止尚未执行的请求，不回滚已有记录。':'结果暂未确认。可核对、用同一请求重试，或取消尚未执行的请求。';
      $('[data-mood-operation-check]').disabled=busy||loading||!canUse;
      $('[data-mood-operation-retry]').hidden=op.cancelRequested||terminal(op);$('[data-mood-operation-retry]').disabled=busy||loading||!canUse;
      $('[data-mood-operation-cancel]').hidden=terminal(op);$('[data-mood-operation-cancel]').disabled=busy||loading||!canUse;
      $('[data-mood-operation-cancel]').textContent=copy('mood.recovery.cancel','取消这次提交');
    }
    function updatePoint(){
      if(!host)return;const blocked=busy||loading||!!pending(),map=$('[data-mood-map]'),orb=$('[data-mood-point]');
      orb.hidden=!(xChosen&&yChosen);orb.style.left=((x+1)*50)+'%';orb.style.top=((1-y)*50)+'%';map.style.setProperty('--mood-tint',moodTint(x,y));
      $('[data-mood-x]').value=String(x);$('[data-mood-y]').value=String(y);
      $('[data-mood-state]').textContent=xChosen&&yChosen?`感受：${axisText(x,'偏不愉快','偏愉快')} · 精力：${axisText(y,'偏低','偏高')}`:'点选平面，或分别调整下面两条滑杆。';
      for(const name of ['x','y','prev','next'])$('[data-mood-'+name+']').disabled=blocked||!supported();
      for(const name of ['note','source']){const field=$('[data-mood-'+name+']');field.disabled=busy||loading||!supported();field.readOnly=!!pending();}
      $('[data-mood-open]').disabled=!supported();$('[data-mood-save]').disabled=blocked||!loaded||!supported()||!xChosen||!yChosen;
      $('[data-mood-analyze]').disabled=blocked||!loaded||!suggestions();$('[data-mood-reload]').disabled=busy||loading||!supported();
      $('[data-mood-delete]').disabled=blocked||!loaded;$('[data-mood-delete-confirm]').disabled=blocked||!loaded;
      $('[data-mood-context]').disabled=blocked||!loaded||!xChosen||!yChosen||typeof onContext!=='function';
      const unresolvedNew=!isLedger(pending())&&pending()?.kind==='put'&&pending()?.body?.expected_updated_at==null&&pending()?.state!=='conflict'&&latestReview===null;
      $('[data-mood-use-version]').hidden=!pending()||!reviewed||unresolvedNew||(isLedger(pending())&&(!ledgerSupported()||!terminal(pending())));$('[data-mood-use-version]').disabled=busy||loading;renderDrafts();renderOperation();
    }
    function drawCalendar(){
      const grid=$('[data-mood-calendar]');if(!grid)return;const [yr,mo]=month.split('-').map(Number),first=new Date(yr,mo-1,1),days=new Date(yr,mo,0).getDate();$('[data-mood-month]').textContent=`${yr} 年 ${mo} 月`;grid.replaceChildren();
      for(const text of ['日','一','二','三','四','五','六']){const el=document.createElement('span');el.className='mood-weekday';el.textContent=text;grid.append(el);}
      for(let i=0;i<first.getDay();i++)grid.append(document.createElement('span'));
      for(let n=1;n<=days;n++){const date=`${month}-${String(n).padStart(2,'0')}`,button=document.createElement('button');button.type='button';button.className='mood-date';button.textContent=String(n);if(date===currentDay)button.classList.add('selected');if(records.some(item=>item.date===date))button.classList.add('recorded');button.setAttribute('aria-label',date+(records.some(item=>item.date===date)?'，有已保存记录':''));button.setAttribute('aria-pressed',String(date===currentDay));button.onclick=()=>{if(date!==currentDay)requestChange(()=>selectDate(date));};grid.append(button);}
    }
    function selectDate(date,{restore=true}={}){
      currentDay=date;month=date.slice(0,7);const entry=records.find(item=>item.date===date);x=entry?.x??0;y=entry?.y??0;xChosen=!!entry;yChosen=!!entry;versionAtEdit=entry?.updated_at??null;dirty=false;sourceDirty=false;reviewed=false;latestReview=null;pendingChange=null;
      $('[data-mood-note]').value=entry?.note||'';$('[data-mood-source]').value='';$('[data-mood-date-label]').textContent=(date===day(new Date())?'今天 · ':'')+date;$('[data-mood-delete]').hidden=!entry;$('[data-mood-delete-confirm]').hidden=true;$('[data-mood-suggestion]').hidden=true;$('[data-mood-unsaved]').hidden=true;
      const op=pending();if(restore)restoreDraft(draftFor(sid,date)||(op?.tab_id===tabId?op.draft:null));
      status(op?'上次操作结果尚未确认。原请求已保留，请重新读取核对，不会自动重发。':dirty?'未保存的草稿还在这里，确认后才会记录。':entry?'这是你确认的记录，可以调整或删除。':'没有记录；初始位置尚未选定，由你决定两条维度。');drawCalendar();updatePoint();
    }
    function requestChange(action){if(busy||loading)return;if(pending()){status('请先重新读取并核对上次操作，原草稿仍保留。');return;}if(!dirty)return action();pendingChange=action;$('[data-mood-unsaved]').hidden=false;}
    function pendingValid(op){return op && !op.unreadable && ['put','delete'].includes(op.kind) && typeof op.id==='string' && dateValid(op.date) && op.session_id===sid && op.draft;}
    function removePending(op){const saved=read(op.key);if(saved?.id!==op.id)throw Error('待核对请求已变化');drop(op.key);}
    async function load(){
      if(!active()||busy||loading||!supported())return;const ticket=generation,session=sid;loading=true;updatePoint();status('正在读取心情记录…');
      try{let ledger=pending();if(isLedger(ledger)&&ledgerSupported()){ledger=await hashedOperation(ledger);const receipt=await api('/api/mood-operations/'+encodeURIComponent(ledger.id)+'?session_id='+encodeURIComponent(session));if(!valid(ticket,session))return;if(!receiptValid(receipt,ledger,{query:true}))throw Error('请求回执不完整');saveReceipt(ledger,receipt);}
        const response=await api('/api/moods?session_id='+encodeURIComponent(session));if(!valid(ticket,session))return;
        if(!Array.isArray(response?.moods)||response.moods.some(item=>!entryValid(item))||new Set(response.moods.map(item=>item.date)).size!==response.moods.length)throw Error('记录格式不完整');
        records=response.moods;loading=false;loaded=true;const op=pending(),draft=dirty?snapshot():draftFor(session,currentDay);const latest=records.find(item=>item.date===currentDay)||null;
        if(pendingValid(op) && (!isLedger(op)||(ledgerSupported()&&terminal(op)&&op.receipt?.state==='applied'&&(op.kind==='delete'||latest?.updated_at===op.receipt.result_updated_at))) && ((op.kind==='put'&&sameEntry(latest,op.body,op.date))||(op.kind==='delete'&&!latest))){const foreignDraft=op.tab_id!==tabId?draft:null;
          if(op.tab_id===tabId)clearDraft(session,currentDay);removePending(op);selectDate(currentDay,{restore:false});
          if(foreignDraft){restoreDraft(foreignDraft);updatePoint();status('已核对另一窗口的当前记录；本窗口草稿与原版本保留，尚未提交。');}
          else if(isLedger(op)&&op.kind==='put'&&op.draft.sourceDirty){$('[data-mood-source]').value=op.draft.source||'';sourceDirty=true;dirty=true;checkpoint();status('已记录。参考文字未保存，仍作为草稿留在这里。');}
          else status(op.kind==='put'?'已核对：当前记录与你提交的内容一致。':'已核对：这一天当前没有记录。');return;}
        selectDate(currentDay);if(draft)restoreDraft(draft);
        if(op){reviewed=true;latestReview=latest;status(isLedger(op)?!ledgerSupported()?'当前服务不支持核对这份请求。原请求与草稿保留，请连接支持请求账本的服务。':op.receipt?.state==='applied'?'这次请求曾执行，当前记录已不同。草稿保留；查看当前记录后，再明确采用该版本继续编辑。':op.receipt?.state==='conflict'?'这次请求有版本冲突，没有覆盖。草稿保留；可明确采用刚读取的版本继续编辑。':op.receipt?.state==='cancelled'?'这次请求已取消，未执行；草稿保留，可明确采用当前版本继续编辑。':'还未查到已执行回执；这不代表请求不会晚到。原请求与草稿保留，不会自动重发。':'已重新读取，尚不能确认原操作。你的草稿保留；请核对下方当前记录，再决定是否采用该版本继续编辑。');$('[data-mood-current]').textContent=latest?`当前记录：感受 ${latest.x}，精力 ${latest.y}；${latest.note||'没有附言'}`:isLedger(op)&&terminal(op)?'当前记录：这一天尚无记录。':'当前记录：这一天尚无记录；原操作是否晚到仍未确认。';$('[data-mood-current]').hidden=false;}
        updatePoint();
      }catch(_){if(valid(ticket,session)){loading=false;loaded=false;updatePoint();status('暂时无法读取心情记录。草稿保留；为避免覆盖，当前不会提交。');}}
    }
    function persistOperation(kind,body){
      if(!globalThis.crypto?.randomUUID)throw Error('当前环境无法安全保留操作编号，请先复制文字。');
      const id=crypto.randomUUID(),op={id,kind,session_id:sid,surface,tab_id:tabId,date:currentDay,body,draft:snapshot(),state:'started',at:Date.now()},key=pendingPrefix+id;put(key,op);return {...op,key};
    }
    async function mutateLedger(kind){
      if(!active()||busy||loading||!loaded||!ledgerSupported()||pending()||kind==='put'&&(!xChosen||!yChosen))return;
      if(!checkpoint())return;const ticket=generation,session=sid,date=currentDay;busy=true;updatePoint();
      let op,persisted=false;
      try{if(!crypto?.randomUUID)throw Error('当前环境无法保留请求编号');const id=crypto.randomUUID(),body=kind==='put'?{session_id:session,x,y,note:$('[data-mood-note]').value,confirmed:true,expected_updated_at:versionAtEdit}:{session_id:session,expected_updated_at:versionAtEdit},inner=kind==='put'?{kind:'save',date,expected_updated_at:versionAtEdit,x:body.x,y:body.y,note:body.note}:{kind:'delete',date,expected_updated_at:versionAtEdit};
        op={id,transport:'mood-ledger-v1',kind,session_id:session,surface,tab_id:tabId,date,body,draft:snapshot(),operation_json:JSON.stringify(inner),operation_sha256:null,cancelRequested:false,state:'started',at:Date.now()};op.key=pendingPrefix+id;put(op.key,op);persisted=true;op=await hashedOperation(op);
        if(!valid(ticket,session))return;await sendLedgerOperation(op,'apply');
      }catch(error){if(op){try{const saved=read(op.key);if(saved?.id===op.id)put(op.key,{...saved,state:'unknown'});}catch(_){}}if(valid(ticket,session))status(persisted?'尚未取得完整回执，原请求和草稿保留。请核对后再决定。':'没有提交；暂时无法保留本机请求，请先复制文字。');}
      finally{if(valid(ticket,session)){busy=false;updatePoint();}}
    }
    async function sendLedgerOperation(op,action){
      const session=op.session_id,ticket=generation;let endpoint='/api/mood-operations',body;
      op=await hashedOperation(op);const saved=read(op.key);if(saved?.id!==op.id||saved.operation_json!==op.operation_json)throw Error('本机请求已变化');
      if(action==='apply'){if(saved.cancelRequested===true||terminal(saved))throw Error('这次请求不会重新提交');body={session_id:session,request_id:op.id,operation_json:op.operation_json,confirmed:true};}
      else{op={...saved,key:op.key,cancelRequested:true};put(op.key,op);endpoint+='/'+encodeURIComponent(op.id)+'/cancel';body={session_id:session,operation_sha256:op.operation_sha256,kind:op.kind==='put'?'save':'delete',confirmed:true};}
      if(!valid(ticket,session)||!ledgerSupported())return;status(action==='apply'?'正在用已保留的请求提交…':'正在封住尚未执行的请求…');
      try{const receipt=await api(endpoint,{method:'POST',body:JSON.stringify(body)});if(!receiptValid(receipt,op))throw Error('请求回执不完整');saveReceipt(op,receipt);if(!valid(ticket,session))return;busy=false;await load();}
      catch(error){try{const latest=read(op.key);if(latest?.id===op.id)put(op.key,{...latest,state:'unknown'});}catch(_){}if(valid(ticket,session))status(error.status===409?'请求身份校验冲突，尚不能确认结果。保留原请求，请继续核对，不会另建请求。':'未取得完整回执，原请求和草稿保留。不会自动重发。');}
    }
    async function retryLedger(action){
      let op=pending();if(!active()||busy||loading||!ledgerSupported()||!ledgerValid(op)||terminal(op)||action==='apply'&&op.cancelRequested)return;const ticket=generation,session=sid;busy=true;updatePoint();
      try{if(action==='cancel'){const saved=read(op.key);if(saved?.id!==op.id||saved.operation_json!==op.operation_json)throw Error('本机请求已变化');op={...saved,key:op.key,cancelRequested:true};put(op.key,op);}await sendLedgerOperation(op,action);}catch(_){if(valid(ticket,session))status('无法核对本机请求，原内容与标识仍保留。');}finally{if(valid(ticket,session)){busy=false;updatePoint();}}
    }
    async function mutate(kind){
      if(ledgerSupported())return mutateLedger(kind);
      if(!active()||busy||loading||!loaded||!supported()||pending()||kind==='put'&&(!xChosen||!yChosen))return;
      if(!checkpoint())return;const ticket=generation,session=sid,date=currentDay;
      const body=kind==='put'?{session_id:session,x,y,note:$('[data-mood-note]').value,confirmed:true,expected_updated_at:versionAtEdit}:{session_id:session,expected_updated_at:versionAtEdit};
      let op;try{op=persistOperation(kind,body);}catch(error){status(error.message);return;}busy=true;updatePoint();status(kind==='put'?'正在记录…':'正在删除…');
      try{const path='/api/moods/'+encodeURIComponent(date);const result=kind==='put'?await api(path,{method:'PUT',body:JSON.stringify(body)}):await api(path+'?session_id='+encodeURIComponent(session)+'&expected_updated_at='+encodeURIComponent(body.expected_updated_at||''),{method:'DELETE'});
        if(kind==='put'?!sameEntry(result,body,date)||result.updated_at===body.expected_updated_at:result?.deleted!==true)throw Error('操作回执不完整');
        const cached=draftFor(session,date);if(!cached||sameDraft(cached,op.draft))clearDraft(session,date);removePending(op);
        if(!valid(ticket,session))return;busy=false;records=records.filter(item=>item.date!==date);if(kind==='put')records.push(result);const reference=$('[data-mood-source]').value,keepReference=sourceDirty;selectDate(date,{restore:false});if(kind==='put'&&keepReference){$('[data-mood-source]').value=reference;sourceDirty=true;dirty=true;checkpoint();}status(kind==='delete'?'已删除这一天的记录。':keepReference?'已记录。参考文字未保存，仍作为草稿留在这里。':'已记录，之后可以调整或删除。');
      }catch(error){
        try{if([400,422].includes(error.status))removePending(op);else if(read(op.key)?.id===op.id)put(op.key,{...op,state:error.status===409?'conflict':'unknown'});}catch(_){}
        if(valid(ticket,session)){busy=false;reviewed=false;updatePoint();status(error.status===409?'其他窗口已更改这一天。草稿和原版本保留，请重新读取核对；不会自动覆盖。':[400,422].includes(error.status)?'这次没有记录，草稿保留，请核对输入。':'操作结果尚未确认。原请求和草稿已保留，请重新读取核对；不会自动重发。');}
      }finally{if(valid(ticket,session)){busy=false;updatePoint();}}
    }
    function mount(element){
      if(!element)return;checkpoint();host=element;sid=getSessionId();generation++;busy=false;loading=false;loaded=false;capabilities=null;records=[];dirty=false;sourceDirty=false;reviewed=false;pendingChange=null;
      try{const candidates=[...scan(pendingRoot,sid),...scan(draftPrefix,sid)].filter(item=>dateValid(item.date)).sort((a,b)=>(b.at||0)-(a.at||0));currentDay=candidates[0]?.date||day(new Date());}catch(_){currentDay=day(new Date());}month=currentDay.slice(0,7);
      host.innerHTML=`<section class="mood-card"><div class="mood-intro"><div><h3 data-mood-title></h3><p data-mood-context-note></p></div><button type="button" class="mood-open" data-mood-open aria-expanded="false" disabled></button></div><div data-mood-panel hidden>
        <div class="mood-unsaved" data-mood-unsaved hidden><span>还有未保存的内容，要继续吗？</span><button type="button" data-mood-discard>放弃这份草稿并继续</button><button type="button" data-mood-keep>继续编辑</button></div>
        <div class="mood-operation" data-mood-operation hidden><p data-mood-operation-info></p><details><summary>查看这次提交的原内容</summary><p data-mood-operation-original></p></details><button type="button" data-mood-operation-check>核对这次请求</button><button type="button" data-mood-operation-retry>用原请求重试</button><button type="button" data-mood-operation-cancel>取消未执行的请求</button></div><details class="mood-drafts" data-mood-drafts><summary data-mood-drafts-title></summary><p data-mood-drafts-info></p><div data-mood-drafts-list></div><button type="button" data-mood-drafts-refresh>刷新本机草稿列表</button></details><button type="button" data-mood-reload>重新读取并核对</button><p data-mood-current hidden></p><button type="button" data-mood-use-version hidden>保留草稿，采用已读取版本</button><div class="mood-calendar-head"><button type="button" data-mood-prev aria-label="上个月">‹</button><b data-mood-month></b><button type="button" data-mood-next aria-label="下个月">›</button></div><div class="mood-calendar" data-mood-calendar aria-label="心情日历"></div>
        <div class="mood-date-title"><span>这一天的自我记录</span><b data-mood-date-label></b></div><div class="mood-map-wrap"><div class="mood-axis top">精力较高</div><div class="mood-axis left">不愉快</div><div class="mood-axis right">愉快</div><div class="mood-axis bottom">精力较低</div><div class="mood-map" data-mood-map role="img" aria-label="心情平面：横轴为感受，纵轴为精力。可点按，或使用下方两条滑杆。"><span class="mood-point" data-mood-point hidden></span></div></div><p class="mood-state" data-mood-state aria-live="polite"></p>
        <div class="mood-sliders"><label><span data-mood-label-x></span><input type="range" data-mood-x min="-1" max="1" step="0.05" value="0"></label><label><span data-mood-label-y></span><input type="range" data-mood-y min="-1" max="1" step="0.05" value="0"></label></div><label class="mood-note-label"><span data-mood-note-label></span><textarea data-mood-note maxlength="1000" rows="2" placeholder="想留下一句，也可以留空。"></textarea></label>
        <details class="mood-help"><summary>用我写的话，生成一处参考</summary><p>仅支持少量明确的自述，无法确定时不猜。不会读取聊天或设备数据；参考需你选择并确认。</p><textarea data-mood-source maxlength="1000" rows="2" aria-label="这次主动提供的参考文字"></textarea><button type="button" data-mood-analyze>生成参考位置</button><div data-mood-suggestion hidden></div></details>
        <p class="mood-fine">记录在本机服务，草稿在当前设备保留，尚未加密。这里不是情绪测量；Rokid、手表、脑电暂不参与推断。</p><div class="mood-actions"><button type="button" class="mood-save" data-mood-save disabled></button><button type="button" data-mood-context disabled></button><button type="button" data-mood-delete hidden>删除这一天</button><button type="button" data-mood-delete-confirm hidden>确认删除</button></div><p>带到聊天只会追加到输入框；发送后模型才会收到，不会因此保存长期记忆。</p><p class="mood-status" data-mood-status role="status"></p></div></section>`;
      for(const [selector,key,fallback] of [['title','mood.title','今天，感觉怎么样？'],['open','mood.open','记录心情'],['save','mood.save','确认并记录'],['label-x','mood.valence','感受：不愉快 — 愉快'],['label-y','mood.energy','精力：低 — 高'],['note-label','mood.note','想说的话 · 选填'],['context-note','mood.context','只留作自己的记录；不会自动加入聊天或长期记忆。'],['context','mood.to_chat','带到聊天，由我发送'],['drafts-title','mood.drafts.open','找回其他页面的草稿'],['operation-check','mood.recovery.check','核对这次请求'],['operation-retry','mood.recovery.retry','用原请求重试']])$('[data-mood-'+selector+']').textContent=copy(key,fallback);
      $('[data-mood-x]').setAttribute('aria-label',copy('mood.valence','感受：不愉快 — 愉快'));$('[data-mood-y]').setAttribute('aria-label',copy('mood.energy','精力：低 — 高'));
      $('[data-mood-open]').onclick=()=>{if(!supported())return;const panel=$('[data-mood-panel]');panel.hidden=!panel.hidden;$('[data-mood-open]').setAttribute('aria-expanded',String(!panel.hidden));if(!panel.hidden&&!loaded)void load();};
      $('[data-mood-operation-check]').onclick=()=>load();$('[data-mood-operation-retry]').onclick=()=>retryLedger('apply');$('[data-mood-operation-cancel]').onclick=()=>retryLedger('cancel');
      $('[data-mood-drafts-refresh]').onclick=()=>{if(active())renderDrafts();};
      $('[data-mood-reload]').onclick=()=>{if(pending()){void load();return;}requestChange(()=>{checkpoint();void load();});};
      $('[data-mood-discard]').onclick=()=>{const action=pendingChange;pendingChange=null;try{clearDraft(sid,currentDay);}catch(_){status('暂时无法移除本机草稿，文字保留。');return;}dirty=false;sourceDirty=false;$('[data-mood-unsaved]').hidden=true;if(action)action();};
      $('[data-mood-keep]').onclick=()=>{pendingChange=null;$('[data-mood-unsaved]').hidden=true;};
      $('[data-mood-use-version]').onclick=()=>{const op=pending();if(!pendingValid(op)||!reviewed||busy||loading||(isLedger(op)?!ledgerSupported()||!terminal(op):(op.kind==='put'&&op.body.expected_updated_at==null&&op.state!=='conflict'&&latestReview===null)))return;try{removePending(op);}catch(_){status('暂时无法更新本机待核对标识，原请求保留。');return;}versionAtEdit=latestReview?.updated_at??null;dirty=true;reviewed=false;$('[data-mood-current]').hidden=true;checkpoint();updatePoint();status('已采用刚读取的版本，你的草稿仍在；需再次明确确认才会提交。');};
      function edited(source=false){if(!active()||loading||busy||pending())return;dirty=true;if(source){sourceDirty=true;$('[data-mood-suggestion]').hidden=true;}checkpoint();}
      $('[data-mood-note]').oninput=()=>edited();$('[data-mood-source]').oninput=()=>edited(true);
      $('[data-mood-prev]').onclick=()=>{if(busy||loading||pending())return;const [yr,mo]=month.split('-').map(Number);month=day(new Date(yr,mo-2,1)).slice(0,7);drawCalendar();};$('[data-mood-next]').onclick=()=>{if(busy||loading||pending())return;const [yr,mo]=month.split('-').map(Number);month=day(new Date(yr,mo,1)).slice(0,7);drawCalendar();};
      const map=$('[data-mood-map]');let dragging=false;function move(event){const rect=map.getBoundingClientRect();if(!rect.width||!rect.height)return;({x,y}=point(event.clientX,event.clientY,rect));xChosen=yChosen=true;edited();updatePoint();}
      map.onpointerdown=event=>{if(busy||loading||pending()||!loaded)return;dragging=true;map.setPointerCapture?.(event.pointerId);move(event);};map.onpointermove=event=>{if(dragging&&!busy&&!loading&&!pending())move(event);};map.onpointerup=()=>{dragging=false;};map.onpointercancel=()=>{dragging=false;};
      for(const axis of ['x','y'])$('[data-mood-'+axis+']').oninput=event=>{if(busy||loading||pending()||!loaded)return;if(axis==='x'){x=clamp(event.target.value);xChosen=true;}else{y=clamp(event.target.value);yChosen=true;}edited();updatePoint();};
      $('[data-mood-save]').onclick=()=>mutate('put');$('[data-mood-delete]').onclick=()=>{$('[data-mood-delete-confirm]').hidden=false;};$('[data-mood-delete-confirm]').onclick=()=>requestChange(()=>mutate('delete'));
      $('[data-mood-context]').onclick=()=>{if(!active()||busy||loading||pending()||!loaded||!xChosen||!yChosen||typeof onContext!=='function')return;const text=`我在 ${currentDay} 的自我记录：感受${axisText(x,'偏不愉快','偏愉快')}，精力${axisText(y,'偏低','偏高')}。`+($('[data-mood-note]').value?'\n想说的话：'+$('[data-mood-note]').value:'');try{onContext(text);status('已带到聊天输入框，由你决定是否发送。');}catch(_){status('暂时无法带到输入框，记录和草稿仍在。');}};
      $('[data-mood-analyze]').onclick=async()=>{if(!active()||busy||loading||pending()||!loaded||!suggestions())return;const text=$('[data-mood-source]').value.trim();if(!text){status('先写一句此刻的感受。');return;}busy=true;updatePoint();const ticket=generation,session=sid,date=currentDay;$('[data-mood-suggestion]').hidden=true;try{const result=await api('/api/mood-suggestions',{method:'POST',body:JSON.stringify({session_id:session,text,consent:true})});if(!valid(ticket,session)||currentDay!==date)return;busy=false;if($('[data-mood-source]').value.trim()!==text)throw Error('参考文字已变化');const suggestion=result?.suggestion;if(suggestion!=null&&((suggestion.x!==null&&!coordinate(suggestion.x))||(suggestion.y!==null&&!coordinate(suggestion.y))||!Array.isArray(suggestion.evidence)||suggestion.evidence.length!==1||suggestion.evidence.some(value=>value!==text)||typeof suggestion.explanation!=='string'))throw Error('参考回执不完整');const box=$('[data-mood-suggestion]');box.replaceChildren();box.hidden=false;const intro=document.createElement('p');intro.textContent=suggestion?suggestion.explanation+' 只是可调整的参考，并非测量结果。':'无法确定参考位置，请自己选择。';box.append(intro);if(suggestion){const evidence=document.createElement('p');evidence.textContent='依据你写的：'+suggestion.evidence.join('；');box.append(evidence);const apply=document.createElement('button');apply.type='button';apply.textContent='采用参考，再由我调整';apply.onclick=()=>{if(busy||loading||pending())return;if(suggestion.x!==null){x=suggestion.x;xChosen=true;}if(suggestion.y!==null){y=suggestion.y;yChosen=true;}edited();updatePoint();status('参考尚未记录，请自行补全并确认。');};box.append(apply);}status('参考是否采用，由你决定。');}catch(error){if(valid(ticket,session)){busy=false;status(error.message==='参考文字已变化'?'参考文字已变化，请重新生成。':'暂时无法生成参考，你仍可以自己选择。');}}finally{if(valid(ticket,session)){busy=false;updatePoint();}}};
      const ticket=generation,session=sid;selectDate(currentDay);status('正在核对心情记录能力…');void api('/api/capabilities').then(value=>{if(!valid(ticket,session))return;capabilities=value;updatePoint();status(supported()?'想记录时再打开，由你选择。':'当前服务暂不支持心情记录，聊天照常。');}).catch(()=>{if(valid(ticket,session))status('暂时无法核对心情记录能力，当前不会读取或写入。');});
    }
    function canRefresh(){return !host || !host.isConnected || (!busy && !loading && !dirty && !pendingChange && !pending());}
    function acceptSnapshot(data){
      if(!host || !host.isConnected)return true;
      if(!canRefresh() || !active() || !Array.isArray(data?.moods) || data.moods.some(item=>!entryValid(item)) || new Set(data.moods.map(item=>item.date)).size!==data.moods.length)return false;
      records=data.moods;
      if(loaded)selectDate(currentDay);else drawCalendar();
      return true;
    }
    function stop(){checkpoint();generation++;host=null;sid=null;}
    function clearSession(session){
      for(const item of [...scan('xinji_mood_draft_v',session),...scan(pendingRoot,session)])drop(item.key);
      for(const key of [...drafts.keys()])if(key.startsWith(encodeURIComponent(session)+':'))drafts.delete(key);
      if(sid===session){dirty=false;generation++;host=null;sid=null;}
    }
    window.addEventListener?.('pagehide',()=>{checkpoint();generation++;});
    window.addEventListener?.('pageshow',event=>{if(event.persisted&&host?.isConnected)mount(host);});
    return {mount,stop,clearSession,canRefresh,acceptSnapshot};
  }
  return {create,clamp,point,day,axisText,moodTint,entryValid,sameEntry};
})();
