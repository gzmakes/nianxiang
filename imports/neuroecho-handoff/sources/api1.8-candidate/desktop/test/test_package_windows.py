"""Local security/layout regressions; no runtime download or Windows execution."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SPEC = importlib.util.spec_from_file_location('echo_windows_packager', Path(__file__).resolve().parents[1]/'package-windows.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class PackageWindowsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_zip(self, path, entries):
        with zipfile.ZipFile(path, 'w') as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
        return path

    def test_rejects_zip_traversal_windows_drives_reserved_names_and_ads(self):
        for name in ('../secret', '/outside', 'C:/outside', 'folder\\outside', 'file:ads', 'a/../../b', 'CON.txt', 'folder/LPT1', 'trailing./file', 'space /file'):
            with self.subTest(name=name):
                path = self.make_zip(self.root/'bad.zip',{name:'unsafe'})
                with self.assertRaises(builder.PackagingError): builder.inspect_zip(path)

    def test_rejects_symlinks_and_case_collisions(self):
        path = self.root/'link.zip'
        with zipfile.ZipFile(path,'w') as archive:
            item = zipfile.ZipInfo('link'); item.create_system = 3; item.external_attr = 0o120777 << 16
            archive.writestr(item,'../../outside')
        with self.assertRaises(builder.PackagingError): builder.inspect_zip(path)
        self.make_zip(path,{'MODULE.py':'a','module.py':'b'})
        with self.assertRaises(builder.PackagingError): builder.inspect_zip(path)

    def test_wrong_runtime_hash_and_missing_required_file_fail(self):
        path = self.make_zip(self.root/'runtime.zip',{'python.exe':'fake'})
        with self.assertRaises(builder.PackagingError): builder.verify_hash(path,'0'*64)
        self.assertEqual(builder.verify_hash(path,builder.sha256(path)),builder.sha256(path))
        with self.assertRaises(builder.PackagingError): builder.inspect_zip(path,['python313.dll'])

    def test_provenance_digest_is_checked_without_claiming_signature_verification(self):
        path = self.root/'provenance.json'
        data = {'messageSignature':{'messageDigest':{'algorithm':'SHA2_256','digest':base64.b64encode(bytes.fromhex(builder.PYTHON_SHA256)).decode()}}}
        path.write_text(json.dumps(data)); builder.verify_python_provenance(path)
        data['messageSignature']['messageDigest']['digest'] = base64.b64encode(bytes(32)).decode()
        path.write_text(json.dumps(data))
        with self.assertRaises(builder.PackagingError): builder.verify_python_provenance(path)

    def test_clean_copy_omits_private_config_database_and_dependency_caches(self):
        source, target = self.root/'source', self.root/'target'
        for name in ('main.py','public.json','data.db','model-settings.json','auth.json','.env','__pycache__/main.py','node_modules/mod.py','.venv/site.py'):
            path = source/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text('synthetic')
        builder.copy_clean_tree(source,target,{'.py','.json','.db'})
        self.assertEqual({str(path.relative_to(target)) for path in target.rglob('*') if path.is_file()},{'main.py','public.json'})

    def make_wheel(self, folder, tag='py3-none-any'):
        folder.mkdir(exist_ok=True)
        return self.make_zip(folder/'synthetic-1.0-py3-none-any.whl',{
            'synthetic/__init__.py':'', 'synthetic-1.0.dist-info/METADATA':'Metadata-Version: 2.1\nName: synthetic\nVersion: 1.0\n',
            'synthetic-1.0.dist-info/WHEEL':'Wheel-Version: 1.0\nTag: '+tag+'\n'})

    def test_wheels_must_match_hashed_lock_and_windows_or_universal_tags(self):
        folder = self.root/'wheels'; wheel = self.make_wheel(folder)
        lock = self.root/'locked.txt'; lock.write_text('synthetic==1.0 \\\n    --hash=sha256:'+builder.sha256(wheel)+'\n')
        self.assertEqual(builder.verify_wheelhouse(folder,lock)[0]['name'],'synthetic')
        self.make_wheel(folder,'cp313-cp313-macosx_11_0_arm64')
        lock.write_text('synthetic==1.0 --hash=sha256:'+builder.sha256(wheel)+'\n')
        with self.assertRaises(builder.PackagingError): builder.verify_wheelhouse(folder,lock)
        lock.write_text('synthetic==1.0 --hash=sha256:'+'0'*64+'\n')
        with self.assertRaises(builder.PackagingError): builder.verify_wheelhouse(folder,lock)

    def test_lock_rejects_url_or_index_configuration(self):
        path = self.root/'lock.txt'
        for content in ('--index-url https://example.invalid\n','synthetic @ https://example.invalid/s.whl\n','-r private.txt\n'):
            path.write_text(content+'--hash=sha256:'+'0'*64)
            with self.assertRaises(builder.PackagingError): builder.validate_lock(path)

    def test_uv_is_offline_cross_target_hashed_and_ignores_ambient_indexes(self):
        args = SimpleNamespace(uv='uv',wheels_dir=self.root/'wheels',requirements_lock=self.root/'lock')
        with patch.dict(builder.os.environ,{'UV_INDEX_URL':'https://synthetic-secret.invalid','PIP_INDEX_URL':'https://synthetic-secret.invalid'}), patch.object(builder.subprocess,'run') as run:
            run.return_value = SimpleNamespace(returncode=0,stdout='resolved locally')
            builder.uv_install(args,self.root/'target',dry_run=True)
            command = run.call_args.args[0]
            for option in ('--offline','--no-index','--require-hashes','--no-config','--no-python-downloads','--dry-run'):
                self.assertIn(option,command)
            self.assertEqual(command[command.index('--python-platform')+1],'x86_64-pc-windows-msvc')
            self.assertNotIn('UV_INDEX_URL',run.call_args.kwargs['env'])
            self.assertNotIn('PIP_INDEX_URL',run.call_args.kwargs['env'])

    def test_portable_layout_and_manifest_exclude_private_data_and_never_overwrite(self):
        project = self.root/'project'; desktop = project/'desktop'; desktop.mkdir(parents=True)
        for name,content in {'desktop/package.json':json.dumps({'devDependencies':{'electron':builder.ELECTRON_VERSION}}),
                             'desktop/main.js':'// synthetic', 'desktop/paired_service_bootstrap.py':'# reviewed synthetic helper', 'scripts/run_paired_service.py':'# reviewed synthetic runner', 'server/main.py':'# synthetic', 'server/data.db':'PRIVATE',
                             'server/model-settings.json':'PRIVATE', 'web/index.html':'synthetic', 'shared/release.json':'{}',
                             'SOUL.md':'synthetic','requirements.txt':'synthetic==1.0','design.md':'synthetic'}.items():
            path=project/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(content)
        electron=self.make_zip(self.root/'electron.zip',{'electron.exe':'synthetic runtime','LICENSE':'license','LICENSES.chromium.html':'licenses','resources/default_app.asar':'default'})
        python=self.make_zip(self.root/'python.zip',{'python.exe':'synthetic','python313.dll':'synthetic','python313.zip':'synthetic','python313._pth':'.\n#import site\n','LICENSE.txt':'license'})
        wheels=self.root/'wheels'; wheel=self.make_wheel(wheels)
        lock=self.root/'lock.txt'; lock.write_text('synthetic==1.0 --hash=sha256:'+builder.sha256(wheel)+'\n')
        provenance=self.root/'python.sigstore'; python_hash=builder.sha256(python)
        provenance.write_text(json.dumps({'messageSignature':{'messageDigest':{'algorithm':'SHA2_256','digest':base64.b64encode(bytes.fromhex(python_hash)).decode()}}}))
        output=self.root/'portable'; zipped=self.root/'portable.zip'
        argv=['--project-root',str(project),'--electron-zip',str(electron),'--python-zip',str(python),
              '--python-provenance',str(provenance),'--requirements-lock',str(lock),'--wheels-dir',str(wheels),'--output',str(output),'--zip-output',str(zipped)]
        def fake_install(args,target,**kwargs):
            target.mkdir(parents=True,exist_ok=True); (target/'synthetic.py').write_text('# synthetic'); return 'synthetic install'
        with patch.object(builder,'ELECTRON_SHA256',builder.sha256(electron)), patch.object(builder,'PYTHON_SHA256',python_hash), patch.object(builder,'uv_install',side_effect=fake_install):
            self.assertEqual(builder.main(argv),0)
            self.assertTrue((output/'Echo.exe').is_file())
            self.assertEqual(json.loads((output/'resources/app/project-root.json').read_text()),{'relativeRoot':'../project'})
            self.assertIn('Lib/site-packages',(output/'resources/project/python/python313._pth').read_text())
            self.assertIn('import site',(output/'resources/project/python/python313._pth').read_text())
            self.assertFalse((output/'resources/project/server/data.db').exists())
            self.assertEqual((output/'resources/project/scripts/run_paired_service.py').read_text(),'# reviewed synthetic runner')
            self.assertEqual((output/'resources/project/paired_service_bootstrap.py').read_text(),'# reviewed synthetic helper')
            self.assertFalse((output/'resources/project/server/model-settings.json').exists())
            manifest=json.loads((output/'BUILD-MANIFEST.json').read_text()); self.assertEqual(manifest['windows_runtime_validation'],'NOT_RUN')
            before=(output/'Echo.exe').read_bytes()
            with self.assertRaises(SystemExit): builder.main(argv)
            self.assertEqual((output/'Echo.exe').read_bytes(),before)
        with zipfile.ZipFile(zipped) as archive:
            self.assertIn('portable/resources/project/server/main.py',archive.namelist())
            self.assertFalse(any('data.db' in name or 'model-settings.json' in name for name in archive.namelist()))


if __name__ == '__main__':
    unittest.main()
