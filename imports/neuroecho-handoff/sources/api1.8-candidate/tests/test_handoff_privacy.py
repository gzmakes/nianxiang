"""Exercise the real handoff packager with disposable TLS material, no user files."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/package_handoff.py'


def seed(tmp_path):
    root = tmp_path / 'source'
    required = ['server/main.py', 'server/paired_access.py', 'server/paired_app.py', 'server/conversation_changes.py',
                'scripts/run_paired_service.py', 'web/index.html', 'web/paired-devices.js',
                'web/paired-devices.css', 'requirements.txt', 'design.md', 'shared/api/openapi.json',
                'scripts/check_consistency.py', 'native/ios/Echo.xcodeproj/project.pbxproj',
                'native/ios/Echo.xcodeproj/xcshareddata/xcschemes/Echo.xcscheme',
                'native/android/gradlew', 'native/android/gradle/wrapper/gradle-wrapper.jar',
                'native/android/app/src/main/AndroidManifest.xml']
    for relative in required:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('synthetic source; never executed\n')
    shutil.copyfile(SCRIPT, root / 'scripts/package_handoff.py')
    (root / 'shared/release.json').write_text(json.dumps({'release_id':'synthetic-test'}))
    return root


def run(root, output):
    return subprocess.run([sys.executable, str(root / 'scripts/package_handoff.py'),
                           '--output-dir', str(output)], capture_output=True, text=True)


def test_tls_keys_database_and_environment_never_enter_any_handoff(tmp_path):
    root = seed(tmp_path)
    sentinel = '-----BEGIN ' + 'PRIVATE KEY-----\nDISPOSABLE TEST VALUE\n'
    for name in ['tls.key', 'tls.pem', 'identity.p12', 'identity.pfx', 'local.crt',
                 'data.db', 'model-settings.json', 'auth.json', '.env']:
        (root / name).write_text(sentinel)
    output = tmp_path / 'delivery'
    result = run(root, output)
    assert result.returncode == 0, result.stderr
    archives = list(output.glob('*.zip'))
    assert len(archives) == 3
    for archive in archives:
        with zipfile.ZipFile(archive) as zipped:
            for name in zipped.namelist():
                assert sentinel.encode() not in zipped.read(name)
            assert any(name.endswith('/server/paired_app.py') for name in zipped.namelist())


def test_disguised_private_key_stops_packaging_before_any_archive(tmp_path):
    root = seed(tmp_path)
    value = '-----BEGIN ' + 'PRIVATE KEY-----\nDISPOSABLE TEST VALUE\n'
    (root / 'unexpected.json').write_text(value)
    output = tmp_path / 'delivery'
    result = run(root, output)
    assert result.returncode != 0
    assert 'Potential secret' in result.stderr
    assert 'DISPOSABLE TEST VALUE' not in result.stdout + result.stderr
    assert not list(output.glob('*.zip'))
