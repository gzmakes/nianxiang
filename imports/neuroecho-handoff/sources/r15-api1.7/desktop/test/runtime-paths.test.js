const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {backendPaths,backendDataPath}=require('../runtime-paths');
test('portable Mac uses embedded interpreter and isolated app data without venv',()=>{
  assert.deepEqual(backendPaths({root:'/Moved/Echo.app/project',platform:'darwin',dataDir:'/profile',exists:()=>true}),
    {python:'/Moved/Echo.app/project/python/bin/python3.13',bootstrap:'/Moved/Echo.app/project/desktop_bootstrap.py',dataDir:'/profile/backend'});
});
test('developer Mac retains its existing venv and no bootstrap',()=>{
  assert.deepEqual(backendPaths({root:'/source',platform:'darwin',dataDir:'/profile',exists:()=>false}),{python:'/source/.venv/bin/python'});
});
test('Windows portable and developer resolution remain unchanged',()=>{
  assert.deepEqual(backendPaths({root:'/source',platform:'win32',dataDir:'/profile',exists:()=>true}),{python:'/source/python/python.exe'});
  assert.deepEqual(backendPaths({root:'/source',platform:'win32',dataDir:'/profile',exists:()=>false}),{python:'/source/.venv/Scripts/python.exe'});
});
test('explicit interpreter override keeps portable bootstrap data isolation',()=>{
  const paths=backendPaths({root:'/source',platform:'darwin',pythonOverride:'/explicit/python',dataDir:'/profile',exists:()=>true});
  assert.equal(paths.python,'/explicit/python');assert.equal(paths.dataDir,'/profile/backend');assert.ok(paths.bootstrap);
});

function developer(t) {
  const folder=fs.mkdtempSync(path.join(os.tmpdir(),'echo-developer-paths-'));
  t.after(()=>fs.rmSync(folder,{recursive:true,force:true}));
  const root=path.join(folder,'source'),data=path.join(folder,'private-data');
  fs.mkdirSync(path.join(root,'scripts'),{recursive:true});fs.mkdirSync(data,{mode:0o700});
  fs.writeFileSync(path.join(root,'scripts','run_paired_service.py'),'# synthetic runner');
  return {folder,root,data};
}
test('explicit developer Python preserves venv symlink spelling and selects the external-data runner',t=>{
  const {root,data}=developer(t),python=path.join(root,'.venv','bin','python');
  const result=backendPaths({root,platform:'darwin',pythonOverride:python,backendDataDir:data,dataDir:'/desktop-profile'});
  assert.deepEqual(result,{python,runner:path.join(root,'scripts','run_paired_service.py'),dataDir:fs.realpathSync(data)});
  assert.equal(result.bootstrap,undefined);
});
test('explicit developer profile rejects source/App data, public permissions, symlink and relative paths',t=>{
  const {folder,root,data}=developer(t),inside=path.join(root,'data'),inApp=path.join(folder,'Other.app','data'),link=path.join(folder,'alias');
  fs.mkdirSync(inside,{mode:0o700});fs.mkdirSync(inApp,{recursive:true,mode:0o700});fs.symlinkSync(data,link,'dir');
  for(const candidate of ['relative',inside,inApp,link,path.join(folder,'missing')])assert.throws(()=>backendDataPath(root,candidate));
  fs.chmodSync(data,0o755);assert.throws(()=>backendDataPath(root,data),/私有目录/);
  assert.equal(fs.statSync(data).mode&0o777,0o755,'validation never changes permissions');
});
test('a missing runner fails closed rather than selecting the source database',t=>{
  const {root,data}=developer(t);fs.unlinkSync(path.join(root,'scripts','run_paired_service.py'));
  assert.throws(()=>backendPaths({root,platform:'darwin',backendDataDir:data,dataDir:'/profile'}),/没有回退/);
});
test('external-data developer option cannot silently override portable Mac or Windows behavior',()=>{
  for(const platform of ['darwin','win32'])assert.throws(()=>backendPaths({root:'/source',platform,backendDataDir:'/private',dataDir:'/profile',exists:()=>true}),/仅用于 macOS 本机开发壳/);
});
