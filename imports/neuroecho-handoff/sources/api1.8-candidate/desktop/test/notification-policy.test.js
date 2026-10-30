const test = require('node:test');
const assert = require('node:assert/strict');
const {HOUR, DAY, NOTICE, quiet, mayNotify, createFollowupNotifier, legacyNotificationResult} = require('../notification-policy');

const fixed = Date.parse('2026-10-30T04:00:00.000Z'); // 12:00 in Shanghai
const configured = {revision:0,enabled:true, time_zone:'Asia/Shanghai', quiet_start:'22:00', quiet_end:'08:00', pause_until:null};
const due = {id:'fup_test', session_id:'ses_test', status:'pending', available:true, due:true,
  paused:false, quiet:false, allow_contact:true,contact_eligible:true,contact_reason:null,boundary_revision:0,contact_expires_at:new Date(fixed+3600000).toISOString(), due_at:'2026-10-30T03:00:00+00:00', content:'不应出现在系统通知的敏感内容'};

function harness({settings=configured, item=due, claim={claimed:true,claim_id:'claim_test'}, allowed=true,
  prefs={pausedUntil:null,notificationAttempts:[]}, now=()=>fixed, save=()=>true, supported=()=>true,
  onRequest=()=>{}, showError=false, isForeground=()=>false, caps={features:{companion_boundaries:true,bounded_followup_contact:true,unified_contact_claim:true}}, boundary={revision:0,suppression_revision:0,mode:'active',until:null,time_zone:'Asia/Shanghai'},checkPatch={}}={}) {
  const calls = [], shown = [], closed=[]; let lastClaim;
  const request = async (url, opts={}) => {
    calls.push({url, method:opts.method || 'GET', body:opts.body && JSON.parse(opts.body)});
    await onRequest(url, opts);
    let data;
    if (url.endsWith('/api/capabilities')) data=caps;
    else if(url.includes('/api/companion-boundary?'))data=boundary;
    else if (url.endsWith('/api/conversation')) data={session:{id:'ses_test'}};
    else if (url.includes('/api/followup-notification-settings?')) data=settings;
    else if (url.includes('/api/followups?')) data={followups:Array.isArray(item)?item:[item]};
    else if (url.endsWith('/claim')) {const raw=typeof claim === 'function' ? claim(url) : claim;data={followup_id:decodeURIComponent(url.match(/followups\/([^/]+)/)[1]),occurrence_at:due.due_at,channel:'system',expires_at:new Date(fixed+60000).toISOString(),...raw};lastClaim=data;}
    else if (url.endsWith('/recheck')) data={...lastClaim,allowed,...checkPatch};
    else if (url.endsWith('/finish')) data={ok:true};
    else throw Error('unexpected URL');
    return {ok:true,json:async()=>data};
  };
  const notifier = createFollowupNotifier({origin:()=>'http://127.0.0.1:18787',getPrefs:()=>prefs,
    savePrefs:save,request,supported,now,isForeground,close:()=>closed.push(true),show:value=>{shown.push(value);if(showError)throw Error('unknown');}});
  return {notifier,calls,shown,prefs,closed};
}

test('quiet hours use configured time zone and fail closed for invalid settings',()=>{
  assert.equal(quiet(configured,new Date('2026-10-30T14:00:00Z')),true);
  assert.equal(quiet(configured,new Date('2026-10-30T23:59:00Z')),true);
  assert.equal(quiet(configured,new Date('2026-10-31T00:00:00Z')),false);
  assert.equal(quiet({...configured,time_zone:'Invalid/zone'},new Date(fixed)),true);
  assert.equal(quiet({...configured,quiet_end:'22:00'},new Date(fixed)),true);
});

test('notification requires explicit enable, no pause and bounded attempts',()=>{
  assert.equal(mayNotify({},undefined,fixed),false);
  assert.equal(mayNotify({}, {...configured,enabled:false},fixed),false);
  assert.equal(mayNotify({pausedUntil:new Date(fixed+1).toISOString()},configured,fixed),false);
  assert.equal(mayNotify({notificationAttempts:[fixed-HOUR+1]},configured,fixed),false);
  assert.equal(mayNotify({notificationAttempts:[fixed-HOUR-1,fixed-2*HOUR,fixed-3*HOUR]},configured,fixed),false);
  assert.equal(mayNotify({notificationAttempts:[fixed-DAY-1]},configured,fixed),true);
});

test('default off performs no followup claim or OS call',async()=>{
  const h=harness({settings:{...configured,enabled:false}});
  assert.equal(await h.notifier.tick(),false);
  assert.equal(h.shown.length,0);
  assert.equal(h.calls.length,4);
  assert.equal(h.calls.some(x=>x.url.endsWith('/claim')),false);
});

test('confirmed and atomically claimed followup invokes a generic OS notice once',async()=>{
  const h=harness();
  assert.equal(await h.notifier.tick(),true);
  assert.deepEqual(h.shown,[NOTICE]);
  assert.equal(JSON.stringify(h.shown).includes(due.content),false);
  assert.deepEqual(h.calls.filter(x=>x.method==='POST').map(x=>x.url.split('/').pop()),['claim','recheck','finish']);
  assert.deepEqual(h.calls.find(x=>x.url.endsWith('/claim')).body,{session_id:'ses_test',occurrence_at:due.due_at,channel:'system'});
  assert.deepEqual(h.calls.find(x=>x.url.endsWith('/finish')).body,{session_id:'ses_test',state:'submitted'});
  assert.equal(await h.notifier.tick(),false); // local cooldown
  assert.equal(h.shown.length,1);
});

test('only available, same-conversation and unpaused occurrences can be claimed',async()=>{
  for (const item of [{...due,session_id:'other'}, {...due,paused:true}, {...due,quiet:true},
                      {...due,available:false}, {...due,status:'cancelled'}]) {
    const h=harness({item});
    assert.equal(await h.notifier.tick(),false);
    assert.equal(h.calls.some(x=>x.url.endsWith('/claim')),false);
  }
});

test('claim, recheck, a local pause and persistence failures all fail closed',async()=>{
  const rejected=harness({claim:{claimed:false,reason:'duplicate'}});
  assert.equal(await rejected.notifier.tick(),false);
  assert.equal(rejected.shown.length,0);
  const cancelled=harness({allowed:false});
  assert.equal(await cancelled.notifier.tick(),false);
  assert.equal(cancelled.shown.length,0);
  const failedSave=harness({save:()=>false});
  assert.equal(await failedSave.notifier.tick(),false);
  assert.equal(failedSave.shown.length,0);
  const prefs={pausedUntil:null,notificationAttempts:[]};
  const paused=harness({prefs,onRequest:async url=>{if(url.endsWith('/recheck'))prefs.pausedUntil=new Date(fixed+60000).toISOString();}});
  assert.equal(await paused.notifier.tick(),false);
  assert.equal(paused.shown.length,0);
});

test('lost responses and unknown platform outcomes are not retried or marked failed',async()=>{
  const unknown=harness({onRequest:async url=>{if(url.endsWith('/claim'))throw Error('lost response');}});
  assert.equal(await unknown.notifier.tick(),false);
  assert.equal(unknown.shown.length,0);
  const failure=harness({showError:true});
  assert.equal(await failure.notifier.tick(),false);
  assert.equal(failure.calls.some(x=>x.url.endsWith('/finish')),false);
});

test('concurrent ticks do not compete and old title-bearing entry point is disabled',async()=>{
  let release;
  const block=new Promise(resolve=>{release=resolve;});
  const h=harness({onRequest:async url=>{if(url.endsWith('/claim'))await block;}});
  const first=h.notifier.tick();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(await h.notifier.tick(),false);
  release();assert.equal(await first,true);
  assert.equal(h.shown.length,1);
  assert.equal(legacyNotificationResult().ok,false);
});

test('previously claimed occurrences do not block a later confirmed followup',async()=>{
  const h=harness({item:[due,{...due,id:'fup_new'}],
    claim:url=>url.includes('fup_test') ? {claimed:false,reason:'already_claimed'} : {claimed:true,claim_id:'claim_new'}});
  assert.equal(await h.notifier.tick(),false);
  assert.equal(await h.notifier.tick(),true);
  assert.equal(h.calls.filter(x=>x.url.endsWith('/claim')).length,2);
  assert.equal(h.shown.length,1);
});

test('focused main window avoids duplicate interruption, including a change during recheck',async()=>{
  const focused=harness({isForeground:()=>true});
  assert.equal(await focused.notifier.tick(),false);
  assert.equal(focused.calls.length,0);
  let foreground=false;
  const switching=harness({isForeground:()=>foreground,onRequest:async url=>{if(url.endsWith('/recheck'))foreground=true;}});
  assert.equal(await switching.notifier.tick(),false);
  assert.equal(switching.shown.length,0);
});

test('false and unknown claims occupy a durable attempt across ticks and process recreation',async()=>{
 for(const options of [{claim:{claimed:false,reason:'topic_window_claimed'}},{onRequest:async url=>{if(url.endsWith('/claim'))throw Error('lost after possible claim')}}]){const prefs={notificationAttempts:[]};const h=harness({...options,prefs});await h.notifier.tick();await h.notifier.tick();assert.equal(h.calls.filter(x=>x.url.endsWith('/claim')).length,1);assert.equal(prefs.contactAttempts.length,1);const next=harness({prefs});await next.notifier.tick();assert.equal(next.calls.some(x=>x.url.endsWith('/claim')),false);assert.equal(next.shown.length,0);}
});
test('missing capability, legacy consent and an expired window never POST or invoke OS',async()=>{
 for(const options of [{caps:{features:{unified_contact_claim:true}}},{item:{...due,allow_contact:false}},{item:{...due,contact_expires_at:new Date(fixed).toISOString()}}]){const h=harness(options);await h.notifier.tick();assert.equal(h.calls.some(x=>x.method==='POST'),false);assert.equal(h.shown.length,0);}
});
test('strict recheck receipt identity and expiry prevent a platform call',async()=>{
 for(const checkPatch of [{claim_id:'another'},{followup_id:'other'},{channel:'in_app'},{occurrence_at:'bad'},{expires_at:new Date(fixed).toISOString()}]){const h=harness({checkPatch});assert.equal(await h.notifier.tick(),false);assert.equal(h.shown.length,0);await h.notifier.tick();assert.equal(h.calls.filter(x=>x.url.endsWith('/claim')).length,1);}
});
test('boundary and notification revision changes close local presentations, not passive tasks',async()=>{
 for(const kind of ['boundary','settings']){const boundary={revision:0,suppression_revision:0,mode:'active',until:null,time_zone:'UTC'},settings={...configured,revision:0};const h=harness({boundary,settings});assert.equal(await h.notifier.tick(),true);if(kind==='boundary')boundary.revision=1;else settings.revision=1;assert.equal(await h.notifier.tick(),false);assert.ok(h.closed.length>0);assert.equal(h.calls.filter(x=>x.url.endsWith('/claim')).length,1);}
});
test('local control invalidation during a late recheck prevents OS invocation',async()=>{
 let h;h=harness({onRequest:async url=>{if(url.endsWith('/recheck'))h.notifier.invalidate()}});assert.equal(await h.notifier.tick(),false);assert.equal(h.shown.length,0);
});
