// Natural requests only open a preview. Saving always needs a separate user click.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const helper=fs.readFileSync('web/action-cards.js','utf8'),c=vm.createContext({window:{}});vm.runInContext(helper,c);const cards=c.window.XinjiActionCards;
function candidate(request,text='完整合成草稿'){return cards.chatDraft([{role:'user',text:request},{role:'assistant',text}],1)}
for(const request of ['帮我写一封邮件给同事，说明明天晚到','帮我回复这条消息：今晚有空','请起草一条短信，告诉对方时间变了','请你帮我回一下这封邮件'])test('explicit draft request: '+request,()=>assert.ok(candidate(request)));
for(const request of ['不要帮我写邮件','如果明天有空，你能帮我写邮件吗','他说“帮我写邮件”，我有点烦','“帮我回复这条消息”是什么意思','帮我写代码处理邮件','帮我写邮件时会保存吗','帮我写邮件只是个假设','我只是想说说收到的邮件','帮我梳理一下心情','帮我写邮件，不要起草，先讨论','帮我写邮件\n不用了','帮我写邮件\n算了，我只想聊聊'])test('ordinary, hypothetical or negated request has no action: '+request,()=>assert.equal(candidate(request),null));
test('full reply is retained and neighboring user supplements are joined',()=>{const text='亲爱的同事：\n'+('完整草稿'.repeat(150));const proposal=cards.chatDraft([{role:'user',text:'帮我写一封邮件'},{role:'user',text:'语气温和一些'},{role:'assistant',text}],2);assert.equal(proposal.text,text)});
test('model outage does not produce a draft action',()=>assert.equal(candidate('帮我写一封邮件','模型暂时不可用，这次先用简单回复。我在听。'),null));
function clip(src,a,b){const i=src.indexOf(a),j=src.indexOf(b,i);assert.ok(i>=0&&j>i);return src.slice(i,j)}
function element(){const hidden=new Set();return{value:'',textContent:'',disabled:false,innerHTML:'',classList:{add:x=>hidden.add(x),remove:x=>hidden.delete(x),toggle:(x,on)=>on?hidden.add(x):hidden.delete(x),contains:x=>hidden.has(x)},focus(){},lastChild:{textContent:''},querySelectorAll:()=>[]}}
for(const mobile of [false,true]){
 const label=mobile?'mobile':'desktop',prefix=mobile?'m-':'',src=fs.readFileSync(mobile?'web/m.js':'web/app.js','utf8');
 const variable=mobile?'mobileAction':'pendingAction',open=mobile?'openMobileAction':'openAction',confirm=mobile?'confirmMobileAction':'confirmAction';
 function setup(api=async path=>path==='/api/action'?{id:'a'}:{status:'committed',real:0}){
  const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)},calls=[],state={session:{id:'s',source_label:'Gmail'},context:null};
  const ctx=vm.createContext({$,state,api:async(...args)=>{calls.push(args);return api(...args)},toast(){},touchLastSeen(){},loadAudit(){},loadTaskActions(){},loadToday(){},Date});
  const code=clip(src,'  let '+variable+' = null;',mobile?'  function renderInsights()':'  function actionStatusLabel(');
  vm.runInContext(code+`\nthis.open=${open};this.confirm=${confirm};this.current=()=>${variable};`,ctx);
  return{ctx,state,calls,$};
 }
 test(`${label}: viewing a full draft creates no action, confirmation saves edited text locally`,async()=>{
  const env=setup(),body='完整回复\n'+('abc'.repeat(180));env.ctx.open('message',null,{title:'邮件草稿',text:body});
  assert.equal(env.$('#'+prefix+'action-message').value,body);assert.equal(env.calls.length,0);
  env.$('#'+prefix+'action-message').value=body+'\n用户修改';await env.ctx.confirm();await env.ctx.confirm();
  assert.equal(env.calls.length,2);const request=JSON.parse(env.calls[0][1].body);assert.equal(request.session_id,'s');assert.equal(request.detail,body+'\n用户修改');assert.equal(JSON.parse(env.calls[1][1].body).real,false);
 });
 test(`${label}: switching conversation blocks saving a preview for the wrong session`,async()=>{
  const env=setup();env.ctx.open('message',null,{title:'草稿',text:'完整文字'});env.state.session={id:'other'};await env.ctx.confirm();assert.equal(env.calls.length,0);assert.match(env.$('#'+prefix+'action-result').textContent,/对话状态已变化|对话已变化/);
 });
 test(`${label}: a cleared or overlong draft is retained for correction instead of silently restoring/truncating`,async()=>{
  const env=setup();env.ctx.open('message',null,{title:'草稿',text:'原文'});env.$('#'+prefix+'action-message').value='';await env.ctx.confirm();assert.equal(env.calls.length,0);assert.match(env.$('#'+prefix+'action-result').textContent,/填写/);
  const long='全'.repeat(2001);env.$('#'+prefix+'action-message').value=long;await env.ctx.confirm();assert.equal(env.calls.length,0);assert.equal(env.$('#'+prefix+'action-message').value,long);assert.match(env.$('#'+prefix+'action-result').textContent,/完整保留.*2000/);
 });
 test(`${label}: repeated confirmation while saving creates only one action`,async()=>{
  let release;const waiting=new Promise(r=>release=r),env=setup(async path=>path==='/api/action'?waiting:{status:'committed',real:0});env.ctx.open('message',null,{title:'草稿',text:'正文'});
  const first=env.ctx.confirm();await env.ctx.confirm();assert.equal(env.calls.length,1);release({id:'a'});await first;assert.equal(env.calls.length,2);
 });
 test(`${label}: an uncertain local draft save points to local tasks and blocks blind duplicate saving`,async()=>{
  const env=setup(async()=>{throw Error('response lost')});env.ctx.open('message',null,{title:'草稿',text:'完整正文'});await env.ctx.confirm();await env.ctx.confirm();
  assert.equal(env.calls.length,1);assert.equal(env.$('#'+prefix+'action-message').value,'完整正文');
  assert.match(env.$('#'+prefix+'action-result').textContent,/草稿保存结果未确认.*任务页核对.*暂勿重复保存/);
  assert.equal(env.$('#'+prefix+'action-confirm').disabled,true);
 });
 test(`${label}: a late save response does not close a newer preview`,async()=>{
  let release;const waiting=new Promise(r=>release=r),env=setup(async path=>path==='/api/action'?waiting:{status:'committed',real:0});env.ctx.open('message',null,{title:'旧草稿',text:'旧正文'});const first=env.ctx.confirm();env.ctx.open('message',null,{title:'新草稿',text:'新正文'});release({id:'a'});await first;assert.equal(env.ctx.current().detail,'新正文');assert.equal(env.$('#'+prefix+'action-message').value,'新正文');assert.equal(env.$(mobile?'#m-action':'#action-modal').classList.contains('is-hidden'),false);
 });
 test(`${label}: rendered conversation action only opens a same-session editable preview`,()=>{
  const nodes=new Map(),button={dataset:{chatDraft:'1'}},box=element();box.querySelectorAll=s=>s==='[data-chat-draft]'?[button]:[];
  const $=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)};nodes.set('#m-messages',box);
  const body='完整的模型回复',state={session:{id:'s',mode:'empty'},messages:[{id:'u',role:'user',text:'帮我写一封邮件'},{id:'a',role:'assistant',text:body}],memories:[]},opened=[];
  const ctx=vm.createContext({$,state,window:{XinjiVoice:{pruneClips(){}},XinjiActionCards:cards},memoryProposal:{sync(){}},chatScroll:{render:fn=>fn()},els:{messages:box},esc:x=>x,renderMessageText:x=>x,renderMemeText:x=>x,Date,openAction:(...args)=>opened.push(args),openMobileAction:(...args)=>opened.push(args)});
  const code=clip(src,'  function renderMessages(',mobile?'  let mAuthTimer':'  function memByKind(');vm.runInContext('let renderedChatSession=null,renderedAssistantId=null;'+code+'\nthis.render=renderMessages;',ctx);ctx.render();assert.match(box.innerHTML,/查看并保存为消息草稿/);button.onclick();assert.equal(opened[0][0],'message');assert.equal(opened[0][2].text,body);state.session={id:'other'};button.onclick();assert.equal(opened.length,1);
 });
}
