/* Shared contact checks. desktop/contact-contract.js must stay byte-identical. */
(function(root){
  const features = value => value?.features || {};
  const supported = value => ['companion_boundaries','bounded_followup_contact','unified_contact_claim'].every(k => features(value)[k] === true);
  const instant = value => typeof value === 'string' ? Date.parse(value) : NaN;
  const sameTime = (a,b) => Number.isFinite(instant(a)) && instant(a) === instant(b);
  const id = value => typeof value === 'string' && value.length > 0 && value.length <= 128;
  const identity = item => JSON.stringify([item?.session_id,item?.id,item?.due_at]);
  function eligible(item,sid,now=Date.now()) {
    return id(item?.id) && item.session_id === sid && item.status === 'pending' && item.allow_contact === true && item.contact_eligible === true && item.available === true && item.due === true && item.paused === false && item.quiet === false && item.contact_reason === null && Number.isSafeInteger(item.boundary_revision) && item.boundary_revision >= 0 &&
      Number.isFinite(instant(item.due_at)) && instant(item.due_at) <= now && instant(item.contact_expires_at) > now;
  }
  function claimMatches(value,item,channel,now=Date.now()) {
    return value?.claimed === true && id(value.claim_id) && value.channel === channel && value.followup_id === item.id &&
      sameTime(value.occurrence_at,item.due_at) && instant(value.expires_at) > now && instant(value.expires_at) <= instant(item.contact_expires_at);
  }
  function recheckMatches(value,claim,item,channel,now=Date.now()) {
    return value?.allowed === true && value.claim_id === claim.claim_id && value.followup_id === item.id && value.channel === channel &&
      sameTime(value.occurrence_at,item.due_at) && instant(value.expires_at) > now && instant(value.expires_at) <= instant(claim.expires_at);
  }
  function timeZone(){try{return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';}catch(_){return 'UTC';}}
  function validBoundary(value){return Number.isSafeInteger(value?.revision) && value.revision >= 0 && Number.isSafeInteger(value.suppression_revision) && ['active','paused','until'].includes(value.mode) && typeof value.time_zone === 'string' && (value.mode !== 'until' || Number.isFinite(instant(value.until)));}
  const api={supported,eligible,identity,claimMatches,recheckMatches,timeZone,validBoundary};
  if(typeof module==='object' && module.exports)module.exports=api;else root.XinjiContactContract=api;
})(typeof window==='object'?window:globalThis);
