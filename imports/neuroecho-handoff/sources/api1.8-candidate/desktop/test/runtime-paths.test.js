const test=require('node:test'),assert=require('node:assert/strict');
const {backendPaths}=require('../runtime-paths');
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
