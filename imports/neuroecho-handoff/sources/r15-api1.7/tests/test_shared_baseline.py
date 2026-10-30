"""Prove drift gates fail on altered sources/resources without using real data."""
import json, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class SharedBaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        for directory in ('shared','scripts'):shutil.copytree(ROOT/directory,self.root/directory,ignore=shutil.ignore_patterns('__pycache__'))
        (self.root/'server').mkdir();shutil.copy2(ROOT/'server/main.py',self.root/'server/main.py');shutil.copy2(ROOT/'design.md',self.root/'design.md')
    def tearDown(self):self.temp.cleanup()
    def run_check(self,*args):return subprocess.run([sys.executable,str(self.root/'scripts/check_consistency.py'),*args],text=True,capture_output=True)
    def copy_clients(self):
        for directory in ('web','native/ios/App','native/ios/Echo.xcodeproj','native/android/app/src/main/java'):
            shutil.copytree(ROOT/directory,self.root/directory,ignore=shutil.ignore_patterns('__pycache__','xcuserdata','.DS_Store'))
        for relative in ('native/ios/sync_shared.py','native/android/scripts/sync_shared.py'):
            target=self.root/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/relative,target)
    def run_sync(self,*args):return subprocess.run([sys.executable,str(self.root/'scripts/sync_clients.py'),*args],text=True,capture_output=True)
    def test_current_baseline_reports_unfinished_platform_gates(self):
        r=self.run_check();self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('OPEN GATE',r.stdout)
    def test_removed_server_route_fails(self):
        p=self.root/'server/main.py';p.write_text(p.read_text().replace('@app.get("/api/conversation",','@app.get("/api/conversation-renamed",'))
        self.assertNotEqual(self.run_check().returncode,0)
    def test_edited_generated_native_resource_fails(self):
        p=self.root/'shared/generated/EchoSharedReference.swift';p.write_text(p.read_text()+'// unmanaged edit\n')
        self.assertNotEqual(self.run_check().returncode,0)
    def test_missing_success_responses_cannot_pass_strict_gate(self):
        baseline=self.run_check('--require-response-models');self.assertEqual(baseline.returncode,0,baseline.stdout+baseline.stderr)
        path=self.root/'shared/api/openapi.json';schema=json.loads(path.read_text())
        schema['paths']['/api/conversation']['get']['responses']['200']['content']['application/json']['schema']={}
        path.write_text(json.dumps(schema))
        r=self.run_check('--require-response-models');self.assertNotEqual(r.returncode,0);self.assertIn('RESPONSE_CONTRACT_NOT_READY',r.stderr)
    def test_present_clients_pass_runtime_gate_and_exact_copy_check(self):
        self.copy_clients()
        result=self.run_sync('--check');self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        result=self.run_check('--require-response-models','--require-runtime-adoption')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertIn('static gate',result.stdout)
    def test_changed_shared_copy_is_generated_and_synced_by_one_command(self):
        self.copy_clients()
        path=self.root/'shared/product/copy.zh-CN.json';data=json.loads(path.read_text());data['strings']['nav.today']='合成新导航';path.write_text(json.dumps(data))
        tokens=self.root/'shared/design/tokens.json';data=json.loads(tokens.read_text());data['colors']['ink']='#111122';data['defaults']['lightIntensity']=0.8;tokens.write_text(json.dumps(data))
        spec=self.root/'design.md';spec.write_text(spec.read_text()+'\nSynthetic reviewed test color: #111122\n')
        result=self.run_sync('--check');self.assertNotEqual(result.returncode,0)
        result=self.run_sync();self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        for relative in ('web/generated-shared.js','native/ios/App/SharedDesign.generated.swift','native/android/app/src/main/java/cn/xinji/echo/shared/EchoSharedReference.kt'):
            self.assertIn('合成新导航',(self.root/relative).read_text())
            self.assertIn('#111122',(self.root/relative).read_text())
            self.assertIn('0.8',(self.root/relative).read_text())
        self.assertIn('#111122',(self.root/'web/generated-design.css').read_text())
        result=self.run_check('--require-runtime-adoption');self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def test_changed_runtime_snapshot_cannot_pass_strict_gate(self):
        self.copy_clients()
        for relative in ('web/generated-shared.js','native/ios/App/SharedDesign.generated.swift','native/android/app/src/main/java/cn/xinji/echo/shared/EchoSharedReference.kt'):
            with self.subTest(platform=relative):
                path=self.root/relative;original=path.read_bytes();path.write_bytes(original+b'// drift\n')
                result=self.run_sync('--check');self.assertNotEqual(result.returncode,0)
                result=self.run_check('--require-runtime-adoption');self.assertNotEqual(result.returncode,0);self.assertIn('RUNTIME_ADOPTION_NOT_READY',result.stderr)
                path.write_bytes(original)
    def test_commented_out_or_external_runtime_import_does_not_count(self):
        self.copy_clients();path=self.root/'web/index.html';original=path.read_text()
        for altered in (re.sub(r'(<script[^>]+src="/static/generated-shared\.js[^>]*></script>)',r'<!--\1-->',original),original.replace('/static/generated-shared.js','https://example.invalid/generated-shared.js')):
            path.write_text(altered)
            result=self.run_check('--require-runtime-adoption');self.assertNotEqual(result.returncode,0);self.assertIn('must import generated-shared.js',result.stderr)
    def test_one_hardcoded_ios_preference_is_rejected_even_when_other_bindings_remain(self):
        self.copy_clients();path=self.root/'native/ios/App/SettingsView.swift';path.write_text(path.read_text().replace('private var strength = EchoSharedReference.defaultLightIntensity','private var strength = 0.7'))
        result=self.run_check('--require-runtime-adoption');self.assertNotEqual(result.returncode,0);self.assertIn('Every iOS stored lightStrength binding',result.stderr)
    def test_hardcoded_android_preferences_or_comment_markers_are_rejected(self):
        self.copy_clients();path=self.root/'native/android/app/src/main/java/cn/xinji/echo/EchoViewModel.kt'
        path.write_text(path.read_text().replace('getFloat("light_intensity", Shared.DEFAULT_LIGHT_INTENSITY)','getFloat("light_intensity", .7f)')+'\n// getFloat("light_intensity", Shared.DEFAULT_LIGHT_INTENSITY)\n')
        result=self.run_check('--require-runtime-adoption');self.assertNotEqual(result.returncode,0);self.assertIn('Android stored preference',result.stderr)
    def test_standalone_missing_another_native_platform_is_skipped(self):
        self.copy_clients();shutil.rmtree(self.root/'native/android')
        result=self.run_sync('--check');self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertIn('SKIP: android',result.stdout)
        result=self.run_check('--require-runtime-adoption');self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def test_strict_gate_cannot_claim_adoption_with_no_clients(self):
        result=self.run_check('--require-runtime-adoption');self.assertNotEqual(result.returncode,0);self.assertIn('No runtime client is present',result.stderr)
    def test_companion_controls_cannot_silently_revert_to_platform_copy(self):
        self.copy_clients()
        candidates = {
            'android': (self.root/'native/android/app/src/main/java/cn/xinji/echo/MainActivity.kt', 'Shared.COPY_COMPANION_BOUNDARY_TODAY'),
            'ios': (next(path for path in (self.root/'native/ios/App').glob('*.swift') if 'EchoSharedReference.copy_companion_boundary_today' in path.read_text()), 'EchoSharedReference.copy_companion_boundary_today'),
        }
        for platform,(path, token) in candidates.items():
            original=path.read_text()
            path.write_text(original.replace(token, '"合成手写标题"')+'\n// '+token+'\n')
            result=self.run_check('--require-runtime-adoption')
            self.assertNotEqual(result.returncode,0,platform)
            self.assertIn(platform.capitalize() if platform=='android' else 'iOS',result.stderr)
            path.write_text(original)
    def test_shared_companion_copy_value_propagates_without_rewriting_platform_ui(self):
        self.copy_clients()
        path=self.root/'shared/product/copy.zh-CN.json'
        data=json.loads(path.read_text());data['strings']['companion.boundary.today']='合成边界标题';path.write_text(json.dumps(data))
        self.assertNotEqual(self.run_sync('--check').returncode,0)
        result=self.run_sync();self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        for relative in ('web/generated-shared.js','native/ios/App/SharedDesign.generated.swift','native/android/app/src/main/java/cn/xinji/echo/shared/EchoSharedReference.kt'):
            self.assertIn('合成边界标题',(self.root/relative).read_text())
        result=self.run_check('--require-runtime-adoption')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
if __name__=='__main__':unittest.main()
