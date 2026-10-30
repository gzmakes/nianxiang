#!/usr/bin/env python3
"""Parse all Kotlin/KTS with the already verified Kotlin compiler cache.
This checks syntax only, not Android API resolution or APK compilation.
"""
from pathlib import Path
import hashlib, json, subprocess, sys

project = Path(__file__).resolve().parents[1]
if len(sys.argv) != 3:
    raise SystemExit('Usage: check_kotlin_cached.py /jdk17/home /verified/maven/cache')
jdk, cache = map(Path, sys.argv[1:])
manifest = json.loads((project / 'scripts/jvm-dependencies.sha256.json').read_text())
for name, expected in manifest.items():
    if hashlib.sha256((cache / name).read_bytes()).hexdigest() != expected:
        raise SystemExit('CHANGED_PUBLIC_JAR: ' + name)
classpath = ':'.join(str(cache / name) for name in manifest)
output = project / 'rules-jvm/build/syntax'
output.mkdir(parents=True, exist_ok=True)
subprocess.run([str(jdk / 'bin/javac'), '-classpath', classpath, '-d', str(output), str(project / 'scripts/KotlinSyntaxCheck.java')], check=True)
files = [path for pattern in ('*.kt', '*.kts') for path in project.rglob(pattern) if 'build' not in path.relative_to(project).parts and '.gradle' not in path.relative_to(project).parts]
subprocess.run([str(jdk / 'bin/java'), '-classpath', str(output) + ':' + classpath, 'KotlinSyntaxCheck', *map(str, files)], check=True)
