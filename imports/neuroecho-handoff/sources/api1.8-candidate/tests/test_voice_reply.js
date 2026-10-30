const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const code=fs.readFileSync(require('node:path').join(__dirname,'../web/voice-reply.js'),'utf8');
function button(){return{textContent:'',attrs:{},isConnected:true,setAttribute(k,v){this.attrs[k]=v}};}
function setup({voices=[{lang:'zh-CN',localService:true}],unsupported=false}={}){
 const calls=[],events={},revoked=[],players=[],timers=new Map();let timerId=0;const doc={hidden:false,addEventListener:(name,fn)=>events[name]=fn,createElement(){const audio={controls:false,paused:true,style:{},pause(){this.paused=true;calls.push('pause')},load(){},setAttribute(){},removeAttribute(){}};players.push(audio);return audio}};
 const speech={cancel(){calls.push('cancel')},getVoices(){return voices},speak(u){calls.push(u)}};
 const win={setTimeout:(fn,ms)=>{const id=++timerId;timers.set(id,{fn,ms});return id},clearTimeout:id=>timers.delete(id),document:doc,addEventListener:(name,fn)=>events[name]=fn,URL:{revokeObjectURL:url=>revoked.push(url),createObjectURL:()=> 'blob:synthetic'},fetch:async()=>({ok:true,blob:async()=>({size:100}),headers:{get:()=> 'audio/wav'}})};
 if(!unsupported)Object.assign(win,{speechSynthesis:speech,SpeechSynthesisUtterance:function(text){this.text=text}});
 vm.runInNewContext(code,{window:win});const voice=win.XinjiVoice;
 const message=(id,text,extra={})=>({id,role:'assistant',text,...extra});
 const sync=(rows,sid='s')=>voice.pruneClips(sid,rows);
 return{win,voice,calls,doc,events,revoked,players,timers,message,sync};
}
test('no startup speech; explicit read uses visible parts and local Chinese voice',()=>{
 const e=setup(),b=button(),m=e.message('a','hidden original',{bubbles:['你好[表情: original/happy]','今天怎么样？']});e.sync([m]);assert.equal(e.calls.length,0);
 assert.equal(e.voice.playMessage(m.id,e.voice.readText(m),b,'s'),true);const u=e.calls.at(-1);assert.equal(u.text,'你好\n\n今天怎么样？');assert.equal(u.voice.localService,true);assert.equal(b.textContent,'停止朗读');assert.equal(b.attrs['aria-busy'],'true');u.onstart();assert.equal(b.attrs['aria-busy'],'false');
});
test('pending, user and hidden raw text cannot be read even through a stale handler',()=>{
 const e=setup(),b=button(),m=e.message('a','hidden tail',{bubbles:['已显示原话']});e.sync([m,e.message('pending','not shown',{delivery_pending:true}),{id:'u',role:'user',text:'本人原话'}]);
 for(const [id,text] of [['a','hidden tail'],['pending','not shown'],['u','本人原话']])assert.equal(e.voice.playMessage(id,text,b,'s'),false);
 assert.equal(e.calls.length,0);
});
test('remote or unknown service voices never silently receive text',()=>{
 for(const voices of [[{lang:'zh-CN',localService:false}],[{lang:'zh-CN'}],[],[{lang:'en-US',localService:true}]]){
  const e=setup({voices}),b=button();e.sync([e.message('a','你好')]);assert.equal(e.voice.playMessage('a','你好',b,'s'),false);assert.equal(e.calls.filter(v=>typeof v==='object').length,0);assert.match(b.attrs['aria-label'],/本机语音/);
 }
});
test('unavailable engine is a visible failure without a success claim',()=>{
 const e=setup({unsupported:true}),b=button();e.sync([e.message('a','你好')]);assert.equal(e.voice.playMessage('a','你好',b,'s'),false);assert.match(b.textContent,/暂不能/);
});
test('a late local voice list requires another user click, never automatic speech',()=>{
 const voices=[],e=setup({voices}),b=button();e.sync([e.message('a','你好')]);assert.equal(e.voice.playMessage('a','你好',b,'s'),false);voices.push({lang:'zh-CN',localService:true});assert.equal(e.calls.filter(v=>typeof v==='object').length,0);assert.equal(e.voice.playMessage('a','你好',b,'s'),true);
});
test('stop is explicit and stale callbacks cannot finish a newer playback',()=>{
 const e=setup(),a=button(),b=button();e.sync([e.message('a','第一条'),e.message('b','第二条')]);e.voice.playMessage('a','第一条',a,'s');const old=e.calls.at(-1);e.voice.playMessage('b','第二条',b,'s');const fresh=e.calls.at(-1);old.onend();old.onerror();old.onstart();assert.equal(b.attrs['aria-pressed'],'true');fresh.onstart();assert.equal(b.attrs['aria-busy'],'false');
 e.voice.playMessage('b','第二条',b,'s');assert.equal(b.attrs['aria-pressed'],'false');fresh.onend();assert.equal(b.textContent,'朗读');
});
test('same message rerender rebinds the stop control without repeating speech',()=>{
 const e=setup(),b=button();e.sync([e.message('a','你好')]);e.voice.playMessage('a','你好',b,'s');const u=e.calls.at(-1),replacement=button();e.voice.bindMessage('a','你好',replacement,'s');assert.equal(e.calls.filter(v=>typeof v==='object').length,1);u.onstart();assert.equal(replacement.attrs['aria-pressed'],'true');u.onend();assert.equal(replacement.textContent,'朗读');
});
test('content edit, deletion, pending transition and context change stop existing speech',()=>{
 for(const change of [e=>e.sync([e.message('a','已改')]),e=>e.sync([]),e=>e.sync([e.message('a','原文',{delivery_pending:true})]),e=>e.sync([e.message('a','原文')],'other')]){
  const e=setup(),b=button();e.sync([e.message('a','原文')]);e.voice.playMessage('a','原文',b,'s');change(e);assert.equal(b.attrs['aria-pressed'],'false');assert.ok(e.calls.includes('cancel'));
 }
});
test('background/pagehide stops speech, returning never autoplays',()=>{
 const e=setup(),b=button();e.sync([e.message('a','原文')]);e.voice.playMessage('a','原文',b,'s');e.doc.hidden=true;e.events.visibilitychange();assert.equal(b.attrs['aria-pressed'],'false');assert.equal(e.voice.playMessage('a','原文',b,'s'),false);e.doc.hidden=false;e.events.visibilitychange();assert.equal(e.calls.filter(v=>typeof v==='object').length,1);e.voice.playMessage('a','原文',b,'s');e.events.pagehide();assert.equal(b.textContent,'朗读');
});
test('clip capability is explicit, unsupported/unknown services never POST',async()=>{
 const e=setup(),b=button(),container={replaceChildren(){}};e.sync([e.message('a','原文')]);const calls=[];e.win.fetch=async(...args)=>{calls.push(args);throw Error('must not POST')};e.voice.bindClipControl(b);assert.equal(b.hidden,true);await e.voice.configure({api:async()=>({features:{voice_clip_from_assistant_message:false}})});assert.equal(b.hidden,true);assert.equal(await e.voice.makeClip({sessionId:'s',id:'a',text:'原文',button:b,container,isCurrent:()=>true}),false);assert.equal(calls.length,0);
});
test('a user-created WAV never autoplays; hidden or removed audio is paused and revoked',async()=>{
 const e=setup(),b=button(),container={replaceChildren(){}};e.sync([e.message('a','原文')]);await e.voice.configure({api:async()=>({features:{voice_clip_from_assistant_message:true}})});e.voice.bindClipControl(b);assert.equal(b.hidden,false);
 assert.equal(await e.voice.makeClip({sessionId:'s',id:'a',text:'原文',button:b,container,isCurrent:()=>true}),true);const player=e.players[0];assert.equal(player.paused,true);assert.equal(player.autoplay,undefined);player.paused=false;player.onplay();e.doc.hidden=true;e.events.visibilitychange();assert.equal(player.paused,true);e.sync([]);assert.deepEqual(e.revoked,['blob:synthetic']);
});
test('late capability response cannot re-enable a superseded service capability',async()=>{
 const e=setup(),b=button();let release;const old=e.voice.configure({api:()=>new Promise(r=>release=r)});await e.voice.configure({api:async()=>({features:{voice_clip_from_assistant_message:false}})});release({features:{voice_clip_from_assistant_message:true}});await old;e.voice.bindClipControl(b);assert.equal(b.hidden,true);
});

test('WAV generation and cached playback cannot expose hidden text behind visible bubbles',async()=>{
 const e=setup(),b=button(),container={replaceChildren(){}};await e.voice.configure({api:async()=>({features:{voice_clip_from_assistant_message:true}})});
 const m=e.message('a','可见\n\n未显示的后段',{bubbles:['可见']});e.sync([m]);assert.equal(e.voice.clipEligible(m),false);e.voice.bindClipControl(b,e.voice.clipEligible(m));assert.equal(b.hidden,true);let posted=0;e.win.fetch=async()=>{posted++;throw Error('must not send')};assert.equal(await e.voice.makeClip({sessionId:'s',id:'a',text:m.text,button:b,container,isCurrent:()=>true}),false);assert.equal(posted,0);
});

test('missing start/completion callbacks have bounded failure and stale timers cannot stop a new read',()=>{
 const e=setup(),a=button(),b=button();e.sync([e.message('a','原文'),e.message('b','下一条')]);e.voice.playMessage('a','原文',a,'s');const init=Array.from(e.timers.values())[0];assert.equal(init.ms,10000);init.fn();assert.equal(a.attrs['aria-pressed'],'false');assert.match(a.textContent,/暂不能/);
 e.voice.playMessage('a','原文',a,'s');const old=Array.from(e.timers.values())[0];e.voice.playMessage('b','下一条',b,'s');old.fn();assert.equal(b.attrs['aria-pressed'],'true');e.calls.filter(v=>typeof v==='object').at(-1).onstart();const duration=Array.from(e.timers.values())[0];assert.ok(duration.ms>=20000&&duration.ms<=600000);duration.fn();assert.match(b.textContent,/暂不能/);assert.equal(e.timers.size,0);
});

test('changing topic cancels the current read and its watchdog',()=>{
 const e=setup(),b=button();e.sync([e.message('a','原文')]);e.voice.playMessage('a','原文',b,'s');e.events['xinji-topic-change']();assert.equal(b.attrs['aria-pressed'],'false');assert.equal(e.timers.size,0);
});
