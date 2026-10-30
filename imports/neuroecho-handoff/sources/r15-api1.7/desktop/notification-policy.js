const Contact = require('./contact-contract');
// Desktop notifications are opt-in. Nothing here claims that the user saw one.
const HOUR = 60 * 60 * 1000;
const DAY = 24 * HOUR;
const MINUTE = 60 * 1000;
const NOTICE = Object.freeze({title:'回响 · 有一条你留下的跟进', body:'方便的时候，打开回响看看。', silent:true});
const legacyNotificationResult = () => ({ok:false, reason:'请在今天页面设置并确认跟进提醒。'});

function quiet(settings, now = new Date()) {
  try {
    const {time_zone:zone, quiet_start:start, quiet_end:end} = settings || {};
    if (!zone || !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(start) ||
        !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(end) || start === end) return true;
    const parts = new Intl.DateTimeFormat('en-GB', {timeZone:zone, hour:'2-digit', minute:'2-digit', hourCycle:'h23'}).formatToParts(now);
    const local = `${parts.find(x => x.type === 'hour').value}:${parts.find(x => x.type === 'minute').value}`;
    return start < end ? start <= local && local < end : local >= start || local < end;
  } catch (_) { return true; } // Invalid time zone or settings: fail closed.
}

function attemptsWithinDay(prefs, now) {
  return (Array.isArray(prefs?.notificationAttempts) ? prefs.notificationAttempts : [])
    .filter(value => Number.isFinite(value) && value <= now && value > now - DAY);
}

function mayNotify(prefs, settings, now = Date.now()) {
  if (settings?.enabled !== true) return false;
  if (Date.parse(prefs.pausedUntil || '') > now || Date.parse(settings.pause_until || '') > now || quiet(settings, new Date(now))) return false;
  const attempts = attemptsWithinDay(prefs, now);
  return attempts.length < 3 && !attempts.some(value => value > now - HOUR);
}

function recordAttempt(prefs, settings, now, save) {
  if (!mayNotify(prefs, settings, now)) return false;
  prefs.notificationAttempts = [...attemptsWithinDay(prefs, now), now];
  // A failed write must not allow an untracked notification.
  return save() === true;
}

function validItem(item, sid) {
  return item && item.session_id === sid && item.status === 'pending' &&
    item.available === true && item.due === true && item.paused === false &&
    item.quiet === false && typeof item.id === 'string' && item.id.length <= 128 &&
    typeof item.due_at === 'string' && item.due_at.length <= 64;
}

// Dependencies are injected so tests never create actual OS notifications or real data.
function createFollowupNotifier({origin, getPrefs, savePrefs, request, show, supported, close = () => {}, isForeground = () => false, now = Date.now}) {
  let busy=false,epoch=0,lastContext=null,lastSettings=null;
  const can=settings=>supported()&&!isForeground()&&Number.isSafeInteger(settings?.revision)&&settings.revision>=0&&mayNotify(getPrefs(),settings,now());
  async function json(url,options={}){const response=await request(url,{...options,signal:AbortSignal.timeout(4000)});if(!response.ok)throw Error('notification request failed');return response.json();}
  function invalidate(){epoch++;}
  function remember(item){
    const prefs=getPrefs(),key=Contact.identity(item),prior=Array.isArray(prefs.contactAttempts)?prefs.contactAttempts:[];
    if(prior.includes(key))return false;
    prefs.contactAttempts=[...prior,key];return savePrefs()===true;
  }
  async function tick(){
    if(busy)return false;
    if(!supported()||isForeground()){close();return false;}
    busy=true;const ticket=epoch;const current=()=>ticket===epoch&&!isForeground();
    try{
      const caps=await json(`${origin()}/api/capabilities`);if(!current())return false;if(!Contact.supported(caps)){close();return false;}
      const conversation=await json(`${origin()}/api/conversation`),sid=conversation?.session?.id;
      if(typeof sid!=='string'||!sid||sid.length>128||!current())return false;
      const boundary=await json(`${origin()}/api/companion-boundary?session_id=${encodeURIComponent(sid)}`);
      if(!current()||!Contact.validBoundary(boundary))return false;
      const context=JSON.stringify([sid,boundary.revision]);
      if(lastContext!==null&&lastContext!==context){lastContext=context;close();return false;}lastContext=context;
      if(boundary.mode!=='active'){close();return false;}
      const settings=await json(`${origin()}/api/followup-notification-settings?session_id=${encodeURIComponent(sid)}`);
      const settingsKey=JSON.stringify([settings?.revision,settings?.enabled,settings?.pause_until]);
      if(lastSettings!==null&&lastSettings!==settingsKey){lastSettings=settingsKey;close();return false;}lastSettings=settingsKey;
      if(!current()||!can(settings)){close();return false;}
      const data=await json(`${origin()}/api/followups?session_id=${encodeURIComponent(sid)}`);
      if(!current()||!can(settings)||!Array.isArray(data?.followups))return false;
      const prior=Array.isArray(getPrefs().contactAttempts)?getPrefs().contactAttempts:[];
      const item=data.followups.find(item=>Contact.eligible(item,sid,now())&&item.boundary_revision===boundary.revision&&!prior.includes(Contact.identity(item)));
      if(!item||!remember(item))return false;
      const post=(url,body)=>json(`${origin()}${url}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const claim=await post(`/api/followups/${encodeURIComponent(item.id)}/contact/claim`,{session_id:sid,occurrence_at:item.due_at,channel:'system'});
      if(!current()||!can(settings)||!Contact.claimMatches(claim,item,'system',now()))return false;
      const check=await post(`/api/followup-contacts/${encodeURIComponent(claim.claim_id)}/recheck`,{session_id:sid});
      if(!current()||!can(settings)||!Contact.recheckMatches(check,claim,item,'system',now())||!Contact.eligible(item,sid,now()))return false;
      if(!recordAttempt(getPrefs(),settings,now(),savePrefs))return false;
      try{show(NOTICE,{expiresAt:item.contact_expires_at});}catch(_){return false;}
      void post(`/api/followup-contacts/${encodeURIComponent(claim.claim_id)}/finish`,{session_id:sid,state:'submitted'}).catch(()=>{});
      return true; // Invocation only; never evidence that the user saw it.
    }catch(_){close();return false;}finally{busy=false;}
  }
  return {tick,invalidate};
}

module.exports = {HOUR, DAY, MINUTE, NOTICE, quiet, mayNotify, recordAttempt, validItem, createFollowupNotifier, legacyNotificationResult};
