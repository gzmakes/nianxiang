"""Two actual Swift clients -> disposable paired TLS backend, never user data.
Only a test URLSession trusts this CA, with SSL hostname evaluation retained.
"""
from pathlib import Path
import base64,hashlib,json,os,shutil,socket,subprocess,sys,tempfile,time,urllib.request

def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

def main():
    ios=Path(__file__).resolve().parents[1];root=ios.parents[1]
    seal_path=root.parent/'round14-backend-seal.json'
    seal=json.loads(seal_path.read_text())
    def verify_server():
        for name,digest in seal['files'].items():
            if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:raise RuntimeError('Backend source drift: '+name)
    verify_server()
    print('FINAL_BACKEND_SEAL_SHA256:',hashlib.sha256(seal_path.read_bytes()).hexdigest(),flush=True)
    binary=ios/'.build/host-checks/round14-changes-live';binary.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(['swiftc','-parse-as-library',*map(str,sorted((ios/'Sources/EchoCore').glob('*.swift'))),str(ios/'App/DeviceCredentialStore.swift'),str(ios/'App/EchoStore.swift'),str(ios/'HostChecks/Round14ChangesSmoke.swift'),'-o',str(binary)],check=True)
    openssl=shutil.which('openssl')
    if not openssl:raise RuntimeError('No existing openssl; no installation attempted.')
    with tempfile.TemporaryDirectory(prefix='echo-ios-r14-changes-') as temp:
        path=Path(temp);cert,key,ca,cakey,csr,der,extensions=[path/x for x in ['server.crt','server.key','ca.crt','ca.key','server.csr','ca.der','server.ext']]
        def openssl_run(*args):subprocess.run([openssl,*map(str,args)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=20)
        openssl_run('req','-x509','-newkey','rsa:2048','-sha256','-nodes','-keyout',cakey,'-out',ca,'-days','2','-subj','/CN=Echo R14 Disposable Test CA','-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign')
        openssl_run('req','-new','-newkey','rsa:2048','-sha256','-nodes','-keyout',key,'-out',csr,'-subj','/CN=localhost')
        extensions.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost,IP:127.0.0.1\n')
        openssl_run('x509','-req','-in',csr,'-CA',ca,'-CAkey',cakey,'-CAcreateserial','-out',cert,'-days','1','-sha256','-extfile',extensions)
        openssl_run('x509','-in',ca,'-outform','DER','-out',der)
        p1,p2=port(),port()
        while p1==p2 or {p1,p2}&{18787,18789,18791,18799,18807,18809}:p1,p2=port(),port()
        owner=f'http://127.0.0.1:{p1}';remote=f'https://localhost:{p2}'
        env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'LANG':'en_US.UTF-8'}
        with (path/'runner.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(root/'scripts/run_paired_service.py'),'--data-dir',str(path/'private'),'--local-port',str(p1),'--enable-paired-tls','--paired-host','127.0.0.1','--paired-port',str(p2),'--tls-certfile',str(cert),'--tls-keyfile',str(key)],env=env,stdout=log,stderr=subprocess.STDOUT)
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def request(route,body=None):
                req=urllib.request.Request(owner+route,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
                with opener.open(req,timeout=2) as response:return json.load(response)
            try:
                until=time.monotonic()+15
                while True:
                    try:
                        if request('/api/health')['ok']:break
                    except (OSError,KeyError):pass
                    if child.poll() is not None or time.monotonic()>until:raise RuntimeError('Owned loopback runner failed to become ready.')
                    time.sleep(.05)
                a=request('/api/paired-devices',{'label':'R14 iOS synthetic A','expires_in_seconds':604800,'confirmed':True})
                b=request('/api/paired-devices',{'label':'R14 iOS synthetic B','expires_in_seconds':604800,'confirmed':True})
                payload={'remote':remote,'owner':owner,'token_a':a['token'],'token_b':b['token'],'ca_der':base64.b64encode(der.read_bytes()).decode()}
                print('FRESH_R14_PAIRED_SERVICE: two temporary devices, random loopback ports/private DB; no existing preview or model configuration.',flush=True)
                subprocess.run([str(binary)],input=json.dumps(payload),text=True,check=True,timeout=75)
            finally:
                child.terminate()
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:child.kill();child.wait();raise RuntimeError('Owned disposable runner did not stop.')
        log_text=(path/'runner.log').read_text()
        if any(grant['token'] in log_text for grant in (a,b)):raise RuntimeError('Synthetic bearer appeared in runner output.')
        verify_server()
        print('PASS: backend sealed hashes unchanged before/after; owned runner stopped and all temporary DB/CA/key material removed; no user vault/global trust/account/model touched.',flush=True)

if __name__=='__main__':main()
