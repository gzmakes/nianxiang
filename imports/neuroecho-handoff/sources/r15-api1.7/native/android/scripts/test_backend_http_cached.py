#!/usr/bin/env python3
"""Run actual Kotlin HTTP code against this monorepo's isolated real backend.

Requires an existing Python environment with FastAPI/uvicorn, the verified public
JAR cache and JDK. It uses a temporary SQLite database and loopback socket; no
model calls, CLI source reads, account grants, SDK install or user data access.
"""
from pathlib import Path
import hashlib, json, socket, subprocess, sys, tempfile, threading, time

project = Path(__file__).resolve().parents[1]
backend = project.parents[1]
if len(sys.argv) != 3:
    raise SystemExit('Usage: test_backend_http_cached.py /jdk17/home /verified/maven/cache')
if not (backend / 'server/main.py').is_file():
    raise SystemExit('BACKEND_SMOKE_NOT_RUN: use the full source package containing server/.')
jdk, cache = map(Path, sys.argv[1:])
manifest = json.loads((project / 'scripts/jvm-dependencies.sha256.json').read_text())
for name, expected in manifest.items():
    if hashlib.sha256((cache / name).read_bytes()).hexdigest() != expected:
        raise SystemExit('CHANGED_PUBLIC_JAR: ' + name)
jars = ':'.join(str(cache / name) for name in manifest)
classes = project / 'rules-jvm/build/direct'
if not classes.is_dir():
    raise SystemExit('BACKEND_SMOKE_NOT_RUN: run test_rules_cached.py first to compile actual app Core sources.')
output = project / 'rules-jvm/build/backend-smoke'
output.mkdir(parents=True, exist_ok=True)
subprocess.run([str(jdk / 'bin/java'), '-cp', jars, 'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler', '-no-stdlib', '-no-reflect', '-jvm-target', '17', '-jdk-home', str(jdk), '-classpath', str(classes) + ':' + jars, '-d', str(output), str(project / 'scripts/BackendHttpSmoke.kt')], check=True)
sys.path.insert(0, str(backend))
import uvicorn
from server import core

with tempfile.TemporaryDirectory(prefix='echo-android-http-') as scratch:
    core.DB_PATH = Path(scratch) / 'synthetic.db'
    from server.main import app
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(32)
    address = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='on'))
    worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(.05)
        if not server.started:
            raise SystemExit('Isolated backend did not start; no client tests run.')
        # Seed only this temporary database with deterministic assistant delivery.
        # No model/CLI/TTS calls and no user data. Old ID must not stop latest.
        sid = core.conversation_id()
        core.add_message(sid, 'user', '合成普通原话：今天有点累，但想把项目做好。')
        old = core.add_message(sid, 'assistant', '合成旧首段\n\n合成旧后段')
        latest = core.add_message(sid, 'assistant', '合成新首段\n\n合成新后段')
        conn = core.get_db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            core.chat_delivery.register(conn, sid, old['id'], old['text'], at=time.time() - 3600)
            core.chat_delivery.register(conn, sid, latest['id'], latest['text'], at=time.time() + 3600)
            conn.commit()
        finally:
            conn.close()
        tested_sources = [project / 'scripts/BackendHttpSmoke.kt', project / 'scripts/test_backend_http_cached.py'] + [backend / ('server/' + name) for name in ('main.py', 'core.py', 'chat_delivery.py', 'api_contract.py', 'followups.py', 'proactive_policy.py', 'companion_boundary.py', 'source_context.py', 'agent_runtime.py', 'moods.py', 'mood_operations.py')]
        tested_sources += [p for p in (project / 'app/src/main/java').rglob('*.kt')]
        before = {str(path.relative_to(backend)): hashlib.sha256(path.read_bytes()).hexdigest() for path in tested_sources}
        result = subprocess.run([str(jdk / 'bin/java'), '-cp', str(output) + ':' + str(classes) + ':' + jars, 'cn.xinji.echo.BackendHttpSmokeKt', address, old['id'], latest['id']], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        after = {str(path.relative_to(backend)): hashlib.sha256(path.read_bytes()).hexdigest() for path in tested_sources}
        if before != after:
            raise SystemExit('BACKEND_CHANGED_DURING_SMOKE: rerun after server is sealed.')
        evidence = result.stdout + '\nActual source SHA256:\n' + '\n'.join(name + ' ' + value for name, value in before.items()) + '\n'
        print(evidence, end='')
        (project / 'verification-backend-http.log').write_text(evidence)
        if result.returncode:
            raise SystemExit(result.returncode)
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()
