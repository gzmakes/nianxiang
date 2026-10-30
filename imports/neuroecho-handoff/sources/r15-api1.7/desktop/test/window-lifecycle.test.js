const {test}=require('node:test');
const assert=require('node:assert/strict');
const {revealWindow}=require('../window-lifecycle');
function windowState(minimized=false,destroyed=false){
  const calls=[];
  return {calls,isDestroyed:()=>destroyed,isMinimized:()=>minimized,restore:()=>calls.push('restore'),show:()=>calls.push('show'),focus:()=>calls.push('focus')};
}
test('reopening a minimized window restores it before showing and focusing',()=>{
  const w=windowState(true);assert.equal(revealWindow(w),true);assert.deepEqual(w.calls,['restore','show','focus']);
});
test('reopening a hidden window brings it to the foreground',()=>{
  const w=windowState();assert.equal(revealWindow(w),true);assert.deepEqual(w.calls,['show','focus']);
});
test('late readiness callbacks cannot show a destroyed window',()=>{
  const w=windowState(false,true);assert.equal(revealWindow(w),false);assert.deepEqual(w.calls,[]);assert.equal(revealWindow(null),false);
});
