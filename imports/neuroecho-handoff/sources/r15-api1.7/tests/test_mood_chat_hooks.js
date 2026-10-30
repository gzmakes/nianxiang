// Actual app callbacks, no HTTP or model/submit functions supplied to the VM.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
for(const mobile of [false,true])test((mobile?'H5':'Web/Desktop')+': journal context preserves the existing composer and only saves a draft',()=>{
 const source=fs.readFileSync(mobile?'web/m.js':'web/app.js','utf8'),name=mobile?'putMobileMoodIntoChat':'putMoodIntoChat',start=source.indexOf('  function '+name+'('),end=source.indexOf('\n  state.followupReminder',start);assert.ok(start>=0&&end>start);
 const input={value:'还没说完的原草稿 ',focus(){this.focused=true}},state={session:{id:'canonical'}},events=[];
 const context=vm.createContext({state,els:{input},$:()=>input,window:{XinjiComposerDraft:{save:()=>events.push('composer-draft')}},keepChatDraft:()=>events.push('chat-draft'),keepMobileChatDraft:()=>events.push('chat-draft'),setDesignPanel:()=>events.push('close'),closeSheet:()=>events.push('close'),toast:()=>events.push('notice')});
 vm.runInContext(source.slice(start,end)+'\nthis.put='+name+';',context);context.put('本人明确带入的一句话');context.put('本人明确带入的一句话');
 assert.equal(input.value,'还没说完的原草稿 \n\n本人明确带入的一句话');assert.equal(input.focused,true);assert.equal(state.session.id,'canonical');assert.deepEqual(events.slice(0,4),['composer-draft','chat-draft','close','notice']);
 state.session=null;context.put('不应追加');assert.ok(!input.value.includes('不应追加'));
});
