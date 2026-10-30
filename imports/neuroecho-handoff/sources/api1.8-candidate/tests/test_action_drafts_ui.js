// Saved draft accessibility and copying with synthetic text only.
const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const helper=fs.readFileSync('web/action-cards.js','utf8');
function helperContext(clipboard) {
  const ctx=vm.createContext({window:{},navigator:{clipboard}});
  vm.runInContext(helper,ctx);
  return ctx.window.XinjiActionCards;
}
function draftContainer() {
  const field={focused:false,selected:false,focus(){this.focused=true},select(){this.selected=true}},note={textContent:''};
  const card={querySelector:selector=>selector==='textarea'?field:note};
  const button={dataset:{copyDraft:'0'},disabled:false,closest:()=>card};
  return {field,note,button,container:{querySelectorAll:()=>[button]}};
}

test('drafts display full saved text escaped and clearly show not sent',()=>{
  const cards=helperContext({});
  const text='第一行\n</textarea><img src=x onerror=alert(1)>\n'+('完整正文'.repeat(200));
  const html=cards.html([{kind:'message',title:'<草稿>',detail:text,status:'committed',real:0}]);
  assert.match(html,/草稿已保存 · 未发送/);
  assert.match(html,/textarea readonly/);
  assert.match(html,/&lt;\/textarea&gt;&lt;img/);
  assert.doesNotMatch(html,/<img src/);
  assert.ok(html.includes('完整正文'.repeat(200)));
  assert.match(html,/复制全文/);
  assert.doesNotMatch(html,/已发送/);
});

test('copy uses the exact saved full draft, including newlines',async()=>{
  const body='完整草稿\n第二行\n'+('a'.repeat(1400)), copied=[];
  const cards=helperContext({writeText:async text=>copied.push(text)}), fixture=draftContainer();
  cards.bind(fixture.container,[{kind:'message',detail:body}]);
  await fixture.button.onclick();
  assert.deepEqual(copied,[body]);
  assert.match(fixture.note.textContent,/已复制.*全文/);
  assert.equal(fixture.button.disabled,false);
});

test('copy failure selects the readable text and gives manual copy guidance',async()=>{
  const cards=helperContext({writeText:async()=>{throw Error('permission denied')}}), fixture=draftContainer();
  cards.bind(fixture.container,[{kind:'message',detail:'草稿'}]);
  await fixture.button.onclick();
  assert.equal(fixture.field.focused,true);assert.equal(fixture.field.selected,true);
  assert.match(fixture.note.textContent,/正文已选中.*复制/);
  assert.equal(fixture.button.disabled,false);
});

test('unsupported clipboard also leaves selected text available',async()=>{
  const cards=helperContext(undefined), fixture=draftContainer();
  cards.bind(fixture.container,[{kind:'message',detail:'草稿'}]);await fixture.button.onclick();
  assert.equal(fixture.field.selected,true);
});

for(const [variant,path,begin,end,fn,selector] of [
  ['desktop','web/app.js','  async function loadTaskActions(', '  async function loadData()', 'loadTaskActions','#task-actions'],
  ['mobile','web/m.js','  async function loadMobileTaskActions()', '  async function saveBookmark()', 'loadMobileTaskActions','#m-task-actions']
]) {
  const src=fs.readFileSync(path,'utf8'),code=src.slice(src.indexOf(begin),src.indexOf(end,src.indexOf(begin)));
  test(`${variant} reopens actions and drafts from saved session`,async()=>{
    const el={innerHTML:''},sheet={_xinjiEpoch:1},acts=[{kind:'message',title:'测试',detail:'可拿走的草稿',status:'committed',real:0}],bound=[];
    const cards=helperContext({});
    const ctx=vm.createContext({sourceUiEpoch:0,$:id=>id===selector?el:id==='#m-sheet'?sheet:null,state:{session:{id:'test'}},api:async()=>({actions:acts}),window:{XinjiActionCards:{html:cards.html,bind:(...args)=>bound.push(args)}},esc:x=>x,encodeURIComponent});
    vm.runInContext(code+`\nthis.run=${fn};`,ctx);await ctx.run();
    assert.match(el.innerHTML,/可拿走的草稿/);assert.equal(bound[0][0],el);assert.equal(bound[0][1],acts);
  });
  test(`${variant} ignores a late response after switching conversation`,async()=>{
    const el={innerHTML:'其他会话'},sheet={_xinjiEpoch:1},state={session:{id:'old'}};
    const ctx=vm.createContext({sourceUiEpoch:0,$:id=>id===selector?el:id==='#m-sheet'?sheet:null,state,api:async()=>{state.session={id:'new'};return{actions:[{kind:'message',detail:'旧内容'}]}},window:{XinjiActionCards:{html(){throw Error('must not render')}}},esc:x=>x,encodeURIComponent});
    vm.runInContext(code+`\nthis.run=${fn};`,ctx);await ctx.run();assert.equal(el.innerHTML,'其他会话');
  });
}

test('mobile task sheet has a saved-action list and both surfaces load the helper',()=>{
  assert.match(fs.readFileSync('web/m.js','utf8'),/id="m-task-actions"/);
  for(const path of ['web/index.html','web/m.html'])assert.match(fs.readFileSync(path,'utf8'),/\/static\/action-cards\.js/);
});
