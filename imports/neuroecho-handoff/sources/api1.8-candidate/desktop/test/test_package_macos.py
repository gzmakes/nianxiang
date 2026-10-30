"""Archive/layout/isolation regressions; synthetic fixtures, no GUI or network."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import stat
import shutil
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

SPEC=importlib.util.spec_from_file_location('macos_builder',Path(__file__).resolve().parents[1]/'package-macos.py')
builder=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(builder)
BOOT=importlib.util.spec_from_file_location('portable_bootstrap',Path(__file__).resolve().parents[1]/'portable_backend.py')
bootstrap=importlib.util.module_from_spec(BOOT);BOOT.loader.exec_module(bootstrap)


class PackageMacTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def zip(self,name,entries):
        p=self.root/name
        with zipfile.ZipFile(p,'w') as z:
            for n,data,mode in entries:
                i=zipfile.ZipInfo(n);i.create_system=3;i.external_attr=mode<<16;z.writestr(i,data)
        return p
    def tar(self,name,entries):
        p=self.root/name
        with tarfile.open(p,'w:gz') as tar:
            for n,data,kind in entries:
                i=tarfile.TarInfo(n);i.mode=0o755 if kind=='exec' else 0o644
                if kind=='link':i.type=tarfile.SYMTYPE;i.linkname=data;tar.addfile(i)
                elif kind=='hard':i.type=tarfile.LNKTYPE;i.linkname=data;tar.addfile(i)
                else:
                    b=data.encode();i.size=len(b);tar.addfile(i,io.BytesIO(b))
        return p
    def test_tar_rejects_traversal_escape_hardlink_and_wrong_root(self):
        for n,data,kind in [('../outside','x','file'),('/outside','x','file'),('python/link','../../outside','link'),('python/link','/outside','link'),('python/link','python/file','hard'),('unexpected/file','x','file')]:
            with self.subTest(n=n,data=data):
                p=self.tar('bad.tar.gz',[(n,data,kind)])
                with self.assertRaises(builder.PackagingError):builder.extract_runtime(p,self.root/'extract',kind='tar')
    def test_tar_preserves_internal_symlink_and_execute_bit(self):
        p=self.tar('ok.tar.gz',[('python/bin/python3.13','synthetic','exec'),('python/bin/python3','python3.13','link')])
        out=self.root/'tar';builder.extract_runtime(p,out,kind='tar')
        self.assertTrue(os.access(out/'python/bin/python3',os.X_OK));self.assertTrue((out/'python/bin/python3').is_symlink())
    def test_zip_preserves_framework_symlink_but_rejects_escape_and_case_collision(self):
        p=self.zip('ok.zip',[('Electron.app/Contents/real','x',0o100755),('Electron.app/Contents/link','real',0o120777)])
        builder.extract_runtime(p,self.root/'zip',kind='zip');self.assertTrue((self.root/'zip/Electron.app/Contents/link').is_symlink())
        for entries in [[('Electron.app/link','../../outside',0o120777)],[('Electron.app/A','x',0o100644),('Electron.app/a','x',0o100644)]]:
            p=self.zip('bad.zip',entries)
            with self.assertRaises(builder.PackagingError):builder.extract_runtime(p,self.root/'bad',kind='zip')
    def test_python_provenance_requires_exact_name_hash_and_official_origin(self):
        p=self.root/'provenance.json';a={'name':builder.PYTHON_ASSET,'digest':'sha256:'+builder.PYTHON_SHA256,'browser_download_url':'https://github.com/astral-sh/python-build-standalone/releases/download/20261026/'+builder.PYTHON_ASSET}
        full={'name':builder.PYTHON_FULL_ASSET,'digest':'sha256:'+builder.PYTHON_FULL_SHA256,'browser_download_url':'https://github.com/astral-sh/python-build-standalone/releases/download/20261026/'+builder.PYTHON_FULL_ASSET}
        data={'source':builder.PYTHON_RELEASE,'asset':a,'full_asset':full};p.write_text(json.dumps(data));builder.verify_provenance(p)
        for field,value in [('name','other.tar.gz'),('digest','sha256:'+'0'*64),('browser_download_url','https://example.invalid/runtime')]:
            modified=json.loads(json.dumps(data));modified['asset'][field]=value;p.write_text(json.dumps(modified))
            with self.assertRaises(builder.PackagingError):builder.verify_provenance(p)
    def test_wheels_are_hash_locked_and_reject_windows_and_intel_only(self):
        wheels=self.root/'wheels';wheels.mkdir();p=wheels/'synthetic.whl';lock=self.root/'lock'
        for tag,valid in [('py3-none-any',True),('cp313-cp313-macosx_11_0_arm64',True),('cp313-cp313-macosx_10_13_universal2',True),('cp313-cp313-win_amd64',False),('cp313-cp313-macosx_10_13_x86_64',False)]:
            with zipfile.ZipFile(p,'w') as z:
                z.writestr('s.dist-info/METADATA','Name: synthetic\nVersion: 1\n');z.writestr('s.dist-info/WHEEL','Tag: '+tag+'\n')
            lock.write_text('synthetic==1 --hash=sha256:'+hashlib.sha256(p.read_bytes()).hexdigest())
            if valid:self.assertEqual(len(builder.verify_wheels(wheels,lock)),1)
            else:
                with self.assertRaises(builder.PackagingError):builder.verify_wheels(wheels,lock)
        lock.write_text('synthetic==1 --hash=sha256:'+'0'*64)
        with self.assertRaises(builder.PackagingError):builder.verify_wheels(wheels,lock)
    def test_dependency_install_is_offline_no_index_and_ignores_ambient_credentials(self):
        args=SimpleNamespace(uv='uv',wheels_dir=self.root/'wheels',requirements_lock=self.root/'lock')
        with patch.dict(os.environ,{'PIP_INDEX_URL':'https://synthetic.invalid','UV_INDEX_URL':'https://synthetic.invalid'}),patch.object(builder.subprocess,'run') as run:
            run.return_value=SimpleNamespace(returncode=0,stdout='ok');builder.install_dependencies(args,self.root/'deps',dry_run=True)
            command=run.call_args.args[0]
            for flag in ('--offline','--no-index','--require-hashes','--no-config','--no-python-downloads','--dry-run'):self.assertIn(flag,command)
            self.assertEqual(command[command.index('--python-platform')+1],'aarch64-apple-darwin')
            self.assertNotIn('PIP_INDEX_URL',run.call_args.kwargs['env']);self.assertNotIn('UV_INDEX_URL',run.call_args.kwargs['env'])
    def test_full_runtime_licenses_match_interpreter_and_every_metadata_notice(self):
        metadata={'python_version':builder.PYTHON_VERSION,'target_triple':'aarch64-apple-darwin','python_tag':'cp313',
                  'python_exe':'install/bin/python3.13','license_path':'licenses/LICENSE.cpython.txt',
                  'build_info':{'extension':{'license_paths':['licenses/LICENSE.libffi.txt']}}}
        entries=[('python/PYTHON.json',json.dumps(metadata),'file'),('python/install/bin/python3.13','same runtime','exec'),
                 ('python/licenses/LICENSE.cpython.txt','CPython license','file'),('python/licenses/LICENSE.libffi.txt','libffi license','file')]
        full=self.tar('full.tar.gz',entries);runtime=self.root/'runtime';(runtime/'bin').mkdir(parents=True);(runtime/'bin/python3.13').write_text('same runtime')
        result=builder.extract_licenses(full,runtime);self.assertEqual(result['copied_license_files'],2)
        self.assertTrue((runtime/'licenses/LICENSE.libffi.txt').is_file())
        missing=self.tar('missing.tar.gz',entries[:-1]);other=self.root/'other';(other/'bin').mkdir(parents=True);(other/'bin/python3.13').write_text('same runtime')
        with self.assertRaises(builder.PackagingError):builder.extract_licenses(missing,other)
        changed=self.root/'changed';(changed/'bin').mkdir(parents=True);(changed/'bin/python3.13').write_text('different runtime')
        with self.assertRaises(builder.PackagingError):builder.extract_licenses(full,changed)
    def test_bootstrap_only_changes_selected_profile_paths_and_forbids_bundle_data(self):
        project=self.root/'project';project.mkdir();core=SimpleNamespace(DB_PATH='original');settings=SimpleNamespace(PATH='original')
        fake=SimpleNamespace(core=core,model_settings=settings);old_path=sys.path[:]
        try:
            with patch.dict(sys.modules,{'server':fake}):
                db,config=bootstrap.configure(project,self.root/'isolated-profile')
                self.assertEqual(db,str(self.root/'isolated-profile/data.db'));self.assertEqual(config,str(self.root/'isolated-profile/model-settings.json'))
                self.assertFalse(Path(db).exists());self.assertFalse(Path(config).exists())
                with self.assertRaises(ValueError):bootstrap.configure(project,project/'private-data')
        finally:sys.path[:]=old_path
    def test_new_output_guard_fails_without_reading_runtime_or_overwriting(self):
        project=self.root/'project';project.mkdir();out=self.root/'Existing.app';out.mkdir();(out/'keep').write_text('user')
        argv=[]
        for name,value in [('project-root',project),('electron-zip',self.root/'none'),('python-tar',self.root/'none'),('python-full-tar',self.root/'none'),('python-provenance',self.root/'none'),('requirements-lock',self.root/'none'),('wheels-dir',self.root/'none'),('output',out)]:argv.extend(['--'+name,str(value)])
        with self.assertRaises(SystemExit):builder.main(argv)
        self.assertEqual((out/'keep').read_text(),'user')
    def test_command_line_helper_import_leaves_frozen_source_tree_unchanged(self):
        folder=self.root/'frozen-source';folder.mkdir();desktop=Path(__file__).resolve().parents[1]
        for name in ('package-macos.py','package-windows.py'):shutil.copyfile(desktop/name,folder/name)
        before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
        env={k:v for k,v in os.environ.items() if not k.upper().startswith('PYTHON')}
        result=subprocess.run([sys.executable,str(folder/'package-macos.py'),'--help'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.assertEqual(result.returncode,0)
        self.assertEqual({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()},before)
        self.assertEqual({p.name for p in folder.iterdir()},set(before))


if __name__=='__main__':unittest.main()
