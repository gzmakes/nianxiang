#!/usr/bin/env python3
"""Actual Kotlin HTTPS transport with a synthetic local CA trusted only by its JVM.
No custom SSL/hostname verifier in production, real account, SDK or network access.
"""
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import hashlib, json, ssl, subprocess, sys, tempfile, threading
project = Path(__file__).resolve().parents[1]
jdk, cache = map(Path, sys.argv[1:])
manifest = json.loads((project / 'scripts/jvm-dependencies.sha256.json').read_text())
for name, sha in manifest.items():
    assert hashlib.sha256((cache / name).read_bytes()).hexdigest() == sha
jars = ':'.join(str(cache / name) for name in manifest)
classes = project / 'rules-jvm/build/direct'
output = project / 'rules-jvm/build/pairing-transport'
output.mkdir(parents=True, exist_ok=True)
subprocess.run([str(jdk/'bin/java'),'-cp',jars,'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-jvm-target','17','-jdk-home',str(jdk),'-classpath',str(classes)+':'+jars,'-d',str(output),str(project/'scripts/PairingTransportSmoke.kt')],check=True)
started, released = threading.Event(), threading.Event()
stats = {'redirect_hits': 0, 'conversation_hits': 0}
token = 'echo_pair_' + 'A'*43
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        path=self.path; code=200
        if path == '/api/redirected': stats['redirect_hits'] += 1
        if path == '/api/conversation': stats['conversation_hits'] += 1
        if self.headers.get('Authorization') != 'Bearer '+token: code=401;result={'error_code':'paired_authentication_required'}
        elif path != '/api/paired-device' and self.headers.get('X-Echo-Service-Instance') != 'instance-a': code=428;result={'error_code':'service_instance_required'}
        elif path == '/api/paired-device':
            result={'service_instance_id':'instance-a','conversation_id':'canonical','scope':'personal_core','local_actions_allowed':False,'device':{'id':'device-a','label':'synthetic','created_at':'2026-10-29T00:00:00Z','expires_at':'2099-10-30T00:00:00Z','revoked_at':None}}
        elif path == '/api/conversation': result={'identity':'matched'}
        elif path == '/api/forbidden': code=403;result={'error_code':'paired_operation_forbidden'}
        elif path == '/api/expired': code=401;result={'error_code':'paired_authentication_required'}
        elif path == '/api/wrong-instance': code=409;result={'error_code':'service_instance_mismatch'}
        elif path == '/api/other-conflict': code=409;result={'error_code':'mood_conflict'}
        elif path == '/api/stats': result=stats
        elif path == '/api/redirect': code=302;result={}
        elif path == '/api/delayed401':
            started.set();assert released.wait(10);code=401;result={'error_code':'paired_authentication_required'}
        elif path == '/api/wait-started': assert started.wait(10);result={}
        elif path == '/api/release': released.set();result={}
        else: result={}
        data=json.dumps(result).encode();self.send_response(code)
        if code==302:self.send_header('Location','https://localhost:'+str(self.server.server_port)+'/api/redirected')
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
with tempfile.TemporaryDirectory(prefix='synthetic-tls-',dir=project/'rules-jvm/build') as tmp:
    tmp=Path(tmp);key=tmp/'key.pem';cert=tmp/'cert.pem';trust=tmp/'trust.p12'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost','-days','1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run([str(jdk/'bin/keytool'),'-importcert','-noprompt','-alias','synthetic-local-ca','-file',str(cert),'-keystore',str(trust),'-storetype','PKCS12','-storepass','synthetic-only'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(str(cert),str(key));server.socket=context.wrap_socket(server.socket,server_side=True)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    sources=[project/'app/src/main/java/cn/xinji/echo/Api.kt',project/'app/src/main/java/cn/xinji/echo/Connection.kt',project/'scripts/PairingTransportSmoke.kt',Path(__file__)]
    before={str(p.relative_to(project)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    try:
        result=subprocess.run([str(jdk/'bin/java'),'-Djavax.net.ssl.trustStore='+str(trust),'-Djavax.net.ssl.trustStorePassword=synthetic-only','-cp',str(output)+':'+str(classes)+':'+jars,'cn.xinji.echo.PairingTransportSmokeKt','https://localhost:'+str(server.server_port),'https://127.0.0.1:'+str(server.server_port)],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
        assert before=={str(p.relative_to(project)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        evidence=result.stdout+'\nActual source SHA256:\n'+'\n'.join(k+' '+v for k,v in before.items())+'\n';print(evidence);(project/'verification-pairing-transport-ROUND14.log').write_text(evidence)
        if result.returncode:raise SystemExit(result.returncode)
    finally: released.set();server.shutdown();server.server_close();worker.join(5)
