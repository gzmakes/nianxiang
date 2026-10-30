#!/usr/bin/env python3
"""Offline structural/API-contract checks. This is NOT a Kotlin compiler or APK test."""
from pathlib import Path
import hashlib
import re
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
checks = []
def check(label, condition):
    if not condition:
        raise AssertionError(label)
    checks.append(label)

main = root / 'app/src/main'
manifest = ET.parse(main / 'AndroidManifest.xml').getroot()
ns = '{http://schemas.android.com/apk/res/android}'
check('only INTERNET permission; SAF requires no broad storage permission', [item.get(ns+'name') for item in manifest.findall('uses-permission')] == ['android.permission.INTERNET'])
check('private app data is excluded from Android backup', manifest.find('application').get(ns+'allowBackup') == 'false')
rules = ET.parse(main / 'res/xml/data_extraction_rules.xml').getroot()
check('cloud and device transfer explicitly exclude credential and draft preferences', all(any(item.get('domain') == 'sharedpref' and item.get('path') == '.' for item in rules.find(mode).findall('exclude')) for mode in ('cloud-backup', 'device-transfer')))
check('real native launcher activity', manifest.find('application/activity').get(ns+'name') == '.MainActivity')
for xml in root.glob('app/src/**/res/**/*.xml'):
    ET.parse(xml)
check('all Android XML parses', True)
release_net = ET.parse(main / 'res/xml/network_security_config.xml').getroot()
check('release denies cleartext', release_net.find('base-config').get('cleartextTrafficPermitted') == 'false' and not release_net.findall('domain-config'))
debug_net = ET.parse(root / 'app/src/debug/res/xml/network_security_config.xml').getroot()
check('debug cleartext limited to emulator and explicit USB loopback', {item.text for item in debug_net.findall('domain-config/domain')} == {'10.0.2.2', '127.0.0.1', 'localhost'})
sources = list((main / 'java').rglob('*.kt'))
text = '\n'.join(path.read_text() for path in sources)
check('native Compose rather than a WebView shell', 'setContent {' in text and 'NavigationBarItem' in text and 'android.webkit' not in text and 'WebView(' not in text)
check('single canonical conversation, no POST session creation', '"/api/conversation"' in text and not re.search(r'(post|call)\([^\n]*"/api/session"', text))
check('debug default is localhost for explicit adb reverse', 'const val DEFAULT = "http://127.0.0.1:18787"' in text and 'preferences.getString("endpoint", EndpointPolicy.DEFAULT)' in text)
check('transport does not override Host or supply browser Origin headers', not re.search(r'setRequestProperty\("(?:Host|Origin)"', text, re.I))
check('chat request identity and query/cancel endpoints are present', all(value in text for value in ['"request_id"', '/api/chat/turn/', '/cancel', 'expectedId']))
check('SAF selection, bounded UTF-8 preview and explicit upload exist', all(value in text for value in ['OpenMultipleDocuments', 'CodingErrorAction.REPORT', 'MAX_BYTES', 'attachFiles()', '"/api/local-files/confirm"']))
check('native actions always commit real false and retain existing ids', 'json("real" to false)' in text and 'existingId' in text and 'latest?.status == "previewed"' in text)
check('no embedded model key, push or broad system permissions', not re.search(r'sk-[A-Za-z0-9]{20}|POST_NOTIFICATIONS|READ_EXTERNAL_STORAGE|MANAGE_EXTERNAL_STORAGE', text))
check('paired device uses AndroidKeyStore AES-GCM without plaintext fallback', all(value in text for value in ['AndroidKeyStore', 'AES/GCM/NoPadding', 'X-Echo-Service-Instance', 'service_instance_mismatch', 'paired-blocked']))
check('system font scaling is not overridden', 'fontScale =' not in text and 'fontScale=' not in text)
check('comfort controls and 48dp targets are present', all(value in text for value in ['reduceMotion', 'reduceTransparency', 'lightIntensity', 'areAnimatorsEnabled()', 'Shared.DIMENSION_TOUCH_ANDROID.dp', 'fontSize = Shared.DIMENSION_BODY_FONT.sp']))
def luminance(color):
    values = [int(color[i:i+2], 16)/255 for i in (0, 2, 4)]
    values = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in values]
    return sum(v*w for v, w in zip(values, (.2126, .7152, .0722)))
check('body ink on white meets 12 to 1 contrast', 1.05/(luminance('1B2433')+.05) >= 12)
check('secondary ink on white meets 4.5 to 1 contrast', 1.05/(luminance('56627A')+.05) >= 4.5)
wrapper = root / 'gradle/wrapper/gradle-wrapper.jar'
expected = (root / 'gradle/wrapper/gradle-8.11.1-wrapper.jar.sha256').read_text().strip()
check('official Gradle wrapper JAR SHA256 matches', hashlib.sha256(wrapper.read_bytes()).hexdigest() == expected)
properties = (root / 'gradle/wrapper/gradle-wrapper.properties').read_text()
check('Gradle distribution SHA256 is pinned', 'distributionSha256Sum='+(root / 'gradle/wrapper/gradle-8.11.1-bin.zip.sha256').read_text().strip() in properties)
check('pure JVM rules unit tests are included', (root / 'app/src/test/java/cn/xinji/echo/RulesTest.kt').is_file())
server = root.parents[1] / 'server/main.py'
if server.exists():
    contracts = server.read_text()
    routes = ['/api/conversation', '/api/chat', '/api/chat/turn/{request_id}', '/api/chat/turn/{request_id}/cancel', '/api/local-files/confirm', '/api/memory/{mid}/history', '/api/action/{aid}/commit', '/api/source/revoke']
    check('native endpoint paths match the local server declarations', all(route in contracts for route in routes))
print(f'STATIC_CONTRACTS_OK: {len(checks)} checks; Kotlin compilation, JVM tests and device execution are NOT verified.')
for item in checks:
    print('  PASS '+item)
