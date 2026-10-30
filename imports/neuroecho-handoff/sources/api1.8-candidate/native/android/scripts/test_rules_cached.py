#!/usr/bin/env python3
"""Compile actual native rules/parser and run JUnit from verified cached public JARs.
No Android SDK, network access, global environment changes or Gradle download.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

project = Path(__file__).resolve().parents[1]
if len(sys.argv) != 3:
    raise SystemExit("Usage: python3 scripts/test_rules_cached.py /jdk17/home /verified/maven/cache")
jdk, cache = map(Path, sys.argv[1:])
manifest = json.loads((project / 'scripts/jvm-dependencies.sha256.json').read_text())
for filename, checksum in manifest.items():
    artifact = cache / filename
    if not artifact.is_file() or hashlib.sha256(artifact.read_bytes()).hexdigest() != checksum:
        raise SystemExit('MISSING_OR_CHANGED_PUBLIC_JAR: ' + filename)
jars = [cache / name for name in manifest]
classpath = ':'.join(str(cache / name) for name in ('kotlin-stdlib-2.1.20.jar', 'annotations-13.0.jar', 'junit-4.13.2.jar', 'hamcrest-core-1.3.jar', 'json-20240303.jar', 'kotlinx-coroutines-core-jvm-1.8.0.jar'))
sources = [project / name for name in ('app/src/main/java/cn/xinji/echo/ChangeUpdates.kt', 'app/src/main/java/cn/xinji/echo/Connection.kt', 'app/src/main/java/cn/xinji/echo/Rules.kt', 'app/src/main/java/cn/xinji/echo/SourcePreview.kt', 'app/src/main/java/cn/xinji/echo/Api.kt', 'app/src/main/java/cn/xinji/echo/ProductRules.kt', 'app/src/main/java/cn/xinji/echo/SourceRevocationRules.kt', 'app/src/main/java/cn/xinji/echo/FollowupRules.kt', 'app/src/main/java/cn/xinji/echo/CompanionBoundary.kt', 'app/src/main/java/cn/xinji/echo/MoodRules.kt', 'app/src/main/java/cn/xinji/echo/MoodOperation.kt', 'app/src/main/java/cn/xinji/echo/ReadAloud.kt', 'app/src/main/java/cn/xinji/echo/shared/EchoSharedReference.kt', 'app/src/test/java/cn/xinji/echo/ChangeUpdatesTest.kt', 'app/src/test/java/cn/xinji/echo/ConnectionTest.kt', 'app/src/test/java/cn/xinji/echo/RulesTest.kt', 'app/src/test/java/cn/xinji/echo/SourcePreviewTest.kt', 'app/src/test/java/cn/xinji/echo/ApiMetadataTest.kt', 'app/src/test/java/cn/xinji/echo/ProductRulesTest.kt', 'app/src/test/java/cn/xinji/echo/SourceRevocationTest.kt', 'app/src/test/java/cn/xinji/echo/FollowupRulesTest.kt', 'app/src/test/java/cn/xinji/echo/CompanionBoundaryTest.kt', 'app/src/test/java/cn/xinji/echo/MoodRulesTest.kt', 'app/src/test/java/cn/xinji/echo/MoodOperationTest.kt', 'app/src/test/java/cn/xinji/echo/ReadAloudTest.kt', 'app/src/test/java/cn/xinji/echo/ApiContractTest.kt')]
output = project / 'rules-jvm/build/direct'
output.mkdir(parents=True, exist_ok=True)
log = []
def run(command):
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log.append(result.stdout)
    print(result.stdout, end='')
    if result.returncode:
        (project / 'verification-jvm.log').write_text('\n'.join(log))
        raise SystemExit(result.returncode)
run([str(jdk / 'bin/java'), '-version'])
run([str(jdk / 'bin/java'), '-cp', ':'.join(map(str, jars)), 'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler', '-no-stdlib', '-no-reflect', '-jvm-target', '17', '-jdk-home', str(jdk), '-classpath', classpath, '-d', str(output), *map(str, sources)])
log.append('Kotlin 2.1.20 compilation: exit 0')
log.append('Actual source SHA256:\n' + '\n'.join(str(path.relative_to(project)) + ' ' + hashlib.sha256(path.read_bytes()).hexdigest() for path in sources))
run([str(jdk / 'bin/java'), '-cp', str(output) + ':' + classpath, 'org.junit.runner.JUnitCore', 'cn.xinji.echo.ChangeUpdatesTest', 'cn.xinji.echo.ConnectionTest', 'cn.xinji.echo.RulesTest', 'cn.xinji.echo.SourcePreviewTest', 'cn.xinji.echo.ApiMetadataTest', 'cn.xinji.echo.ProductRulesTest', 'cn.xinji.echo.SourceRevocationTest', 'cn.xinji.echo.FollowupRulesTest', 'cn.xinji.echo.CompanionBoundaryTest', 'cn.xinji.echo.MoodRulesTest', 'cn.xinji.echo.MoodOperationTest', 'cn.xinji.echo.ReadAloudTest', 'cn.xinji.echo.ApiContractTest'])
(project / 'verification-jvm.log').write_text('\n'.join(log))
