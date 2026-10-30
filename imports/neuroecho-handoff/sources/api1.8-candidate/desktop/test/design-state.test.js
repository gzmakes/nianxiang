const test=require('node:test'),assert=require('node:assert/strict');
const {validCommand,normalizeState,effectiveState,stateLabel,tomorrowAtNine}=require('../desktop-state');
test('launcher allows only navigation or bounded draft; it never grants a send or execute command',()=>{
 assert.equal(validCommand({action:'send',text:'x'}),null);assert.equal(validCommand({action:'execute',text:'x'}),null);
 assert.equal(validCommand({action:'draft',text:' '.repeat(2)}),null);assert.equal(validCommand({action:'draft',text:'a'.repeat(4001)}),null);
 assert.deepEqual(validCommand({action:'draft',text:' hi ',url:'file:///private'}),{action:'draft',text:'hi'});
 assert.deepEqual(validCommand({action:'tasks',text:'ignored'}),{action:'tasks'});
});
test('pause lasts to the next local day at nine and automatically expires',()=>{
 const now=new Date(2026,9,29,23,50);const until=tomorrowAtNine(now),date=new Date(until);
 assert.equal(date.getDate(),30);assert.equal(date.getHours(),9);
 assert.equal(effectiveState('responding',until,now.valueOf()),'quiet');
 assert.equal(effectiveState('responding',until,date.valueOf()+1),'responding');
 assert.match(stateLabel('responding',until,now.valueOf()),/暂停/);
});
test('untrusted status cannot create an arbitrary state label or icon path',()=>{assert.equal(normalizeState('../../secret'),'quiet');assert.equal(effectiveState('../../secret',null),'quiet');});
