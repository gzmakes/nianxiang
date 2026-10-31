const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/app.js','utf8');
const start=source.indexOf('  let appsCatalogRequest = 0;'),end=source.indexOf('  async function loadTaskActions(',start);
function fixture(account,snapshots=[]){
 const cardButtons=[],manage={},grid={_html:'',set innerHTML(value){this._html=value;cardButtons.length=0;for(const match of value.matchAll(/data-app-source="([^"]+)" data-app-name="([^"]+)" data-app-idle-action="([^"]+)" data-app-idle-status="([^"]+)"/g)){const status={textContent:''};cardButtons.push({dataset:{appSource:match[1],appName:match[2],appIdleAction:match[3],appIdleStatus:match[4]},status,setAttribute(k,v){this[k]=v},closest(){return{querySelector:()=>status}}});}},get innerHTML(){return this._html;},querySelectorAll(){return cardButtons;}};
 const state={session:{id:'s'},tab:'apps',context:{sources:snapshots},feishuAccount:null},events=[];
 const $=selector=>selector==='#apps-grid'?grid:selector==='#apps-manage-sources'?manage:null;
 const sources=[{id:'feishu',icon:'F',name:'飞书',status:'ready'},{id:'local_files',icon:'L',name:'本地文件',status:'ready'}];
 const ctx=vm.createContext({state,$,api:async()=>({sources}),readFeishuAccountState:async()=>{state.feishuAccount=account},connectedSources:()=>state.context.sources,esc:s=>String(s),switchTab:x=>events.push(x),openCompanionSource:x=>events.push(x),prepareSourceDialog(){},openRealSource(){}});
 vm.runInContext(source.slice(start,end)+'\nthis.loadAppsCatalog=loadAppsCatalog; this.syncAppsSourceControls=syncAppsSourceControls;',ctx);
 return {ctx,grid,manage,state,buttons:cardButtons,events};
}
test('saved snapshots get a check and accurate label, hide file names, and retain source management and selection',async()=>{
 const f=fixture(null,[{connector_id:'local_files',label:'private file',stale:false}]);await f.ctx.loadAppsCatalog();
 assert.doesNotMatch(f.grid.innerHTML,/private file|data-source-remove/);const b=f.buttons[1];assert.equal(b.textContent,'✓');assert.equal(b.status.textContent,'已保存资料快照');assert.match(b['aria-label'],/已保存资料快照/);
 f.manage.onclick();assert.deepEqual(f.events,['data']);await b.onclick();assert.deepEqual(f.events,['data','local']);
 f.state.context.sources[0].stale=true;f.ctx.syncAppsSourceControls();assert.equal(b.textContent,'连接');assert.equal(b.status.textContent,'可选择');
 f.state.context.sources=[];f.ctx.syncAppsSourceControls();assert.equal(b.textContent,'连接');
});
test('account check reflects verified enablement and can update asynchronously; snapshots remain distinct',async()=>{
 const f=fixture({enabled:true,ready:true});await f.ctx.loadAppsCatalog();let b=f.buttons[0];assert.equal(b.textContent,'✓');assert.match(b['aria-label'],/管理连接/);assert.match(b.status.textContent,/搜索曾通过验证/);await b.onclick();assert.deepEqual(f.events,['feishu']);
 for(const [account,label] of [[{enabled:true,ready:false},'管理'],[{enabled:true},'管理'],[{enabled:false,ready:true},'连接'],[null,'连接']]){f.state.feishuAccount=account;f.ctx.syncAppsSourceControls();assert.equal(b.textContent,label);assert.notEqual(b.status.textContent,'已启用 · 搜索曾通过验证');}
 f.state.context.sources=[{connector_id:'feishu',stale:false}];f.ctx.syncAppsSourceControls();assert.equal(b.textContent,'✓');assert.equal(b.status.textContent,'已保存资料快照');assert.match(b['aria-label'],/快照/);
 f.state.feishuAccount={enabled:true,ready:false};f.ctx.syncAppsSourceControls();assert.match(b.status.textContent,/账号需核对/);
 f.state.feishuAccount={enabled:true,ready:true};f.ctx.syncAppsSourceControls();assert.equal(b.textContent,'✓');assert.match(b.status.textContent,/搜索曾通过验证/);
});
