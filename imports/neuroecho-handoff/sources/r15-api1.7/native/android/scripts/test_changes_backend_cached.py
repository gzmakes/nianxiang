#!/usr/bin/env python3
"""Native Kotlin to real paired ASGI, isolated synthetic DB, normal HTTPS trust.
Only a fresh test CA in its child JVM; production TLS code is unchanged.
"""
from pathlib import Path
import hashlib,json,socket,subprocess,sys,tempfile,threading,time,urllib.request
sys.dont_write_bytecode=True
project=Path(__file__).resolve().parents[1];backend=project.parents[1]
jdk,cache=map(Path,sys.argv[1:]);manifest=json.loads((project/'scripts/jvm-dependencies.sha256.json').read_text())
for name,sha in manifest.items():assert hashlib.sha256((cache/name).read_bytes()).hexdigest()==sha
jars=':'.join(str(cache/name) for name in manifest);classes=project/'rules-jvm/build/direct';output=project/'rules-jvm/build/change-backend';output.mkdir(parents=True,exist_ok=True)
subprocess.run([str(jdk/'bin/java'),'-cp',jars,'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-jvm-target','17','-jdk-home',str(jdk),'-classpath',str(classes)+':'+jars,'-d',str(output),str(project/'scripts/ChangeBackendSmoke.kt')],check=True)
sys.path.insert(0,str(backend));import uvicorn
from server import core
from server.paired_app import create_remote_app

def listen():
    s=socket.socket();s.bind(('127.0.0.1',0));s.listen(32);return s

def wait(server,worker):
    until=time.monotonic()+10
    while not server.started and worker.is_alive() and time.monotonic()<until:time.sleep(.02)
    assert server.started,'isolated server did not start'

def local_json(origin,path,body):
    request=urllib.request.Request(origin+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(request,timeout=10) as response:return json.load(response)

with tempfile.TemporaryDirectory(prefix='echo-android-paired-') as tmp:
    tmp=Path(tmp);core.DB_PATH=tmp/'synthetic.db'
    from server.main import app
    owner_socket=listen();tls_socket=listen();owner_origin='http://127.0.0.1:'+str(owner_socket.getsockname()[1]);origin='https://localhost:'+str(tls_socket.getsockname()[1])
    key=tmp/'synthetic-key.pem';cert=tmp/'synthetic-cert.pem';trust=tmp/'synthetic-trust.p12'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost','-days','1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run([str(jdk/'bin/keytool'),'-importcert','-noprompt','-alias','synthetic-local-ca','-file',str(cert),'-keystore',str(trust),'-storetype','PKCS12','-storepass','synthetic-only'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    owner=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='on'));owner_worker=threading.Thread(target=owner.run,kwargs={'sockets':[owner_socket]},daemon=True);owner_worker.start();wait(owner,owner_worker)
    remote=create_remote_app(app,lambda:core.DB_PATH,allowed_origins={origin})
    tls=uvicorn.Server(uvicorn.Config(remote,log_level='error',lifespan='off',ssl_certfile=str(cert),ssl_keyfile=str(key)));tls_worker=threading.Thread(target=tls.run,kwargs={'sockets':[tls_socket]},daemon=True);tls_worker.start();wait(tls,tls_worker)
    sources=list((backend/'server').glob('*.py'))+[p for p in (project/'app/src/main/java').rglob('*.kt')]+[project/'scripts/ChangeBackendSmoke.kt',Path(__file__)]
    before={str(p.relative_to(backend)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources};log=[]
    try:
        grant=local_json(owner_origin,'/api/paired-devices',{'label':'synthetic-android','expires_in_seconds':86400,'confirmed':True})
        second=local_json(owner_origin,'/api/paired-devices',{'label':'synthetic-other-device','expires_in_seconds':86400,'confirmed':True})
        command=[str(jdk/'bin/java'),'-Djavax.net.ssl.trustStore='+str(trust),'-Djavax.net.ssl.trustStorePassword=synthetic-only','-cp',str(output)+':'+str(classes)+':'+jars,'cn.xinji.echo.ChangeBackendSmokeKt',origin,grant['token'],second['token'],owner_origin]
        result=subprocess.run(command,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90)
        log.append(result.stdout);print(result.stdout,end='')
        assert before=={str(p.relative_to(backend)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},'SOURCE_CHANGED_DURING_TEST'
        evidence='\n'.join(log)+'\nActual source SHA256:\n'+'\n'.join(k+' '+v for k,v in before.items())+'\n';(project/'verification-changes-backend-ROUND14.log').write_text(evidence)
        if result.returncode:raise SystemExit(result.returncode)
    finally:
        tls.should_exit=True;tls_worker.join(10);tls_socket.close();owner.should_exit=True;owner_worker.join(10);owner_socket.close()
