const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('web/followups.js', 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const defaults = {enabled:false,configured:false,revision:0,time_zone:'UTC',quiet_start:'22:00',quiet_end:'08:00',cooldown_minutes:60,daily_limit:3,pause_until:null};
const item = {id:'f1',session_id:'one',due_at:'2026-10-30T12:00:00Z',status:'pending',due:true,paused:false,quiet:false,available:true,content:'私密内容'};
function harness({permission='default', desktop=false, settings={...defaults}, apiOverride, requestedPermission='granted',notificationSupported=true}={}) {
  const calls=[], notices=[], events={}, session=new Map(), elements=new Map(); let requested=0, sid='one', timer;
  function node() { return {value:'',hidden:false,disabled:false,textContent:'',isConnected:true,children:[],
    append(...a){this.children.push(...a)},replaceChildren(...a){this.children=a},setAttribute(){},focus(){},remove(){},addEventListener(k,f){this[k]=f},querySelectorAll(){return []}}; }
  const host=node(); host.querySelector=k=>{if(!elements.has(k))elements.set(k,node());return elements.get(k)};
  function Notification(title, options) { notices.push({title,options}); this.close=()=>{}; }
  Notification.permission=permission; Notification.requestPermission=async()=>{requested++;Notification.permission=requestedPermission;return requestedPermission};
  const document={hidden:false,body:{append(){}},createElement:node,addEventListener:(k,f)=>events[k]=f,removeEventListener:k=>delete events[k]};
  const window={addEventListener:(k,f)=>events[k]=f,removeEventListener:k=>delete events[k]}; if(desktop)window.xinjiDesktop={};
  const context={window,document,Notification,sessionStorage:{getItem:k=>session.get(k),setItem:(k,v)=>session.set(k,v)},navigator:{},
    setInterval:fn=>(timer=fn),clearInterval:()=>{timer=null}, Set,Map,Date,JSON,Object,Number,Array,Intl,encodeURIComponent};
  if(!notificationSupported)delete context.Notification;
  context.globalThis=context; vm.runInNewContext(fs.readFileSync('web/contact-contract.js','utf8'),context); vm.runInNewContext(source,context);
  const api=async(path,options)=>{calls.push({path,options});if(path==='/api/capabilities')return {features:{companion_boundaries:true,bounded_followup_contact:true,unified_contact_claim:true}};if(apiOverride)return apiOverride(path,options);
    if(path.startsWith('/api/followup-notification-settings')) {if(options){const body=JSON.parse(options.body);if(body.expected_revision!==settings.revision){const error=Error('conflict');error.status=409;throw error} const {expected_revision, ...rest}=body;settings={...settings,...rest,configured:true,revision:settings.revision+1}}return {...settings};}
    if(path.startsWith('/api/followups?'))return {followups:[item]};
    if(path.endsWith('/claim'))return {claimed:true,claim_id:'c1'};
    if(path.endsWith('/recheck'))return {allowed:true};
    if(path.endsWith('/finish'))return {state:JSON.parse(options.body).state};
    throw Error('Unexpected URL '+path);
  };
  const widget=window.XinjiFollowups.create({api,getSessionId:()=>sid}); widget.mount(host);const advanced=host.querySelector('.notification-settings');advanced.open=true;advanced.ontoggle();
  return {window,document,events,notices,Notification,widget,host,api,calls,requested:()=>requested,setSid:v=>sid=v,timer:()=>timer};
}
const settingsWrites=h=>h.calls.filter(x=>x.path==='/api/followup-notification-settings' && x.options?.method==='PUT');

test('settings start off, show local timezone and only request permission after user click',async()=>{
 const h=harness();await flush();assert.equal(h.requested(),0);assert.equal(h.notices.length,0);
 assert.equal(h.host.querySelector('[data-f-n-zone]').value,Intl.DateTimeFormat().resolvedOptions().timeZone);
 assert.equal(h.host.querySelector('[data-f-n-start]').value,'22:00');
 h.host.querySelector('[data-f-n-zone]').value='Asia/Shanghai'; await h.host.querySelector('[data-f-notification]').onclick();
 assert.equal(h.requested(),1);const body=JSON.parse(settingsWrites(h)[0].options.body);assert.equal(body.enabled,true);assert.equal(body.time_zone,'Asia/Shanghai');assert.equal(body.quiet_start,'22:00');assert.equal(body.pause_until,null); h.widget.stop();
});
test('existing configured timezone and pause are retained when changing bounds',async()=>{
 const pause='2099-01-01T00:00:00Z',h=harness({permission:'granted',settings:{...defaults,configured:true,time_zone:'UTC',pause_until:pause}});await flush();
 assert.equal(h.host.querySelector('[data-f-n-zone]').value,'UTC');h.host.querySelector('[data-f-n-limit]').value='1';
 await h.host.querySelector('[data-f-n-save]').onclick();const body=JSON.parse(settingsWrites(h)[0].options.body);
 assert.equal(body.pause_until,pause);assert.equal(body.daily_limit,1);assert.equal(body.time_zone,'UTC');h.widget.stop();
});
test('permission denial or error never enables setting, and denied permission can still disable policy',async()=>{
 const h=harness({requestedPermission:'denied'});await flush();await h.host.querySelector('[data-f-notification]').onclick();
 assert.equal(h.requested(),1);assert.equal(settingsWrites(h).length,0);assert.match(h.host.querySelector('[data-f-n-feedback]').textContent,/未获得/);h.widget.stop();
 const h2=harness({permission:'denied',settings:{...defaults,configured:true,enabled:true}});await flush();await h2.host.querySelector('[data-f-notification]').onclick();
 assert.equal(JSON.parse(settingsWrites(h2)[0].options.body).enabled,false);assert.equal(h2.requested(),0);h2.widget.stop();
});
test('pause and resume use service-side setting without changing notification enablement',async()=>{
 const h=harness({permission:'granted',settings:{...defaults,configured:true,enabled:true}});await flush();
 await h.host.querySelector('[data-f-n-pause]').onclick();let body=JSON.parse(settingsWrites(h)[0].options.body);assert.equal(body.enabled,true);assert.ok(Date.parse(body.pause_until)>Date.now());
 await h.host.querySelector('[data-f-n-pause]').onclick();body=JSON.parse(settingsWrites(h)[1].options.body);assert.equal(body.pause_until,null);h.widget.stop();
});
test('a failed permission request is explained and does not change the service switch',async()=>{
 const h=harness();await flush();h.Notification.requestPermission=async()=>{throw Error('permission failed')};
 await h.host.querySelector('[data-f-notification]').onclick();assert.equal(settingsWrites(h).length,0);
 assert.match(h.host.querySelector('[data-f-n-feedback]').textContent,/权限请求失败/);h.widget.stop();
});
test('two windows conflict on editing boundaries without overwriting user input or server values',async()=>{
 let settings={...defaults,configured:true,revision:4,enabled:false,time_zone:'Asia/Shanghai',quiet_start:'22:00',quiet_end:'08:00'}, puts=0;
 const api=async(path,opt)=>{
  if(path.startsWith('/api/followups?'))return {followups:[]};
  if(path.startsWith('/api/followup-notification-settings')){
   if(!opt)return {...settings};puts++;const body=JSON.parse(opt.body);
   if(body.expected_revision!==settings.revision){const error=Error('conflict');error.status=409;throw error}
   const {expected_revision,...update}=body;settings={...settings,...update,revision:settings.revision+1};return {...settings};
  }throw Error('unexpected');
 };
 const a=harness({permission:'granted',apiOverride:api}),b=harness({permission:'granted',apiOverride:api});await flush();
 b.host.querySelector('[data-f-n-zone]').value='Europe/London';b.host.querySelector('[data-f-n-start]').value='23:00';await b.host.querySelector('[data-f-n-save]').onclick();
 a.host.querySelector('[data-f-n-limit]').value='1';await a.host.querySelector('[data-f-n-save]').onclick();
 assert.equal(settings.time_zone,'Europe/London');assert.equal(settings.quiet_start,'23:00');assert.equal(settings.daily_limit,3);
 assert.equal(a.host.querySelector('[data-f-n-limit]').value,'1');assert.match(a.host.querySelector('[data-f-n-feedback]').textContent,/其他窗口已更改设置/);assert.equal(puts,2);
 a.widget.stop();b.widget.stop();
});

test('stale window cannot toggle notification and overwrite other window timezone or quiet hours',async()=>{
 let settings={...defaults,configured:true,revision:9,enabled:true,time_zone:'UTC'}, puts=0;
 const api=async(path,opt)=>{
  if(path.startsWith('/api/followups?'))return {followups:[]};
  if(path.startsWith('/api/followup-notification-settings')){
   if(!opt)return {...settings};puts++;const body=JSON.parse(opt.body);
   if(body.expected_revision!==settings.revision){const error=Error('conflict');error.status=409;throw error}
   const {expected_revision,...update}=body;settings={...settings,...update,revision:settings.revision+1};return {...settings};
  }throw Error('unexpected');
 };
 const a=harness({permission:'granted',apiOverride:api}),b=harness({permission:'granted',apiOverride:api});await flush();
 b.host.querySelector('[data-f-n-zone]').value='Asia/Shanghai';b.host.querySelector('[data-f-n-end]').value='09:00';await b.host.querySelector('[data-f-n-save]').onclick();
 await a.host.querySelector('[data-f-notification]').onclick();assert.equal(settings.enabled,true);assert.equal(settings.time_zone,'Asia/Shanghai');assert.equal(settings.quiet_end,'09:00');
 assert.equal(puts,2);assert.match(a.host.querySelector('[data-f-n-feedback]').textContent,/其他窗口已更改设置/);
 await a.host.querySelector('[data-f-n-reload]').onclick();assert.equal(a.host.querySelector('[data-f-n-zone]').value,'Asia/Shanghai');
 await a.host.querySelector('[data-f-notification]').onclick();assert.equal(settings.enabled,false);assert.equal(settings.time_zone,'Asia/Shanghai');assert.equal(settings.quiet_end,'09:00');
 a.widget.stop();b.widget.stop();
});

test('settings copy explains shared scope, running requirement and OS notification limits',async()=>{
 const h=harness();await flush();const copy=h.host.innerHTML;assert.match(copy,/桌面版和浏览器/);assert.match(copy,/正在运行/);assert.match(copy,/系统权限或勿扰/);h.widget.stop();
});

test('H5 without Notification can read and save shared quiet/frequency rules without system permission',async()=>{
 const h=harness({notificationSupported:false});await flush();assert.ok(h.calls.some(c=>c.path.startsWith('/api/followup-notification-settings?')));assert.equal(h.host.querySelector('[data-f-notification]').disabled,true);assert.equal(h.host.querySelector('[data-f-boundaries]').hidden,false);assert.match(h.host.querySelector('[data-f-notification-status]').textContent,/仍可设置应用内轻问/);assert.match(h.host.querySelector('[data-f-n-feedback]').textContent,/待确认的本地默认值/);
 h.host.querySelector('[data-f-n-start]').value='21:00';h.host.querySelector('[data-f-n-limit]').value='1';await h.host.querySelector('[data-f-n-save]').onclick();const body=JSON.parse(settingsWrites(h)[0].options.body);assert.equal(body.enabled,false);assert.equal(body.quiet_start,'21:00');assert.equal(body.daily_limit,1);assert.equal(h.requested(),0);assert.equal(h.notices.length,0);assert.match(h.host.innerHTML,/间隔和次数也作用于应用内轻问/);await h.host.querySelector('[data-f-n-pause]').onclick();assert.ok(Date.parse(JSON.parse(settingsWrites(h)[1].options.body).pause_until)>Date.now());assert.match(h.host.querySelector('[data-f-n-feedback]').textContent,/主动提示已暂停/);h.widget.stop();
});

test('a 200 setting receipt with wrong revision or requested policy remains unconfirmed',async()=>{
 for(const patch of [{enabled:false},{revision:0},{time_zone:'Other/zone'},{daily_limit:2}]){const h=harness({permission:'granted',apiOverride:async(path,opt)=>{if(path.startsWith('/api/followups?'))return {followups:[]};if(!opt)return {...defaults,configured:true};const {expected_revision,...body}=JSON.parse(opt.body);return {...body,configured:true,revision:expected_revision+1,...patch};}});await flush();await h.host.querySelector('[data-f-notification]').onclick();assert.equal(settingsWrites(h).length,1);assert.match(h.host.querySelector('[data-f-n-feedback]').textContent,/结果未确认/);assert.doesNotMatch(h.host.querySelector('[data-f-n-feedback]').textContent,/^已开启/);h.widget.stop();}
});
