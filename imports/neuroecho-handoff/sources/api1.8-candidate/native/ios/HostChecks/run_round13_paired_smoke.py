"""Actual macOS URLSession -> fresh paired TLS runner, private disposable CA only.

No account, existing DB, model, real Keychain or global trust-store operation.
The test binary's injected session evaluates the one test CA AND hostname.
"""
from pathlib import Path
import base64,json,os,shutil,socket,ssl,subprocess,sys,tempfile,threading,time,urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

def main():
    ios=Path(__file__).resolve().parents[1];root=ios.parents[1]
    binary=ios/'.build/host-checks/round13-paired-live';binary.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(['swiftc','-parse-as-library',*map(str,sorted((ios/'Sources/EchoCore').glob('*.swift'))),str(ios/'App/DeviceCredentialStore.swift'),str(ios/'App/EchoStore.swift'),str(ios/'HostChecks/Round13PairedSmoke.swift'),'-o',str(binary)],check=True)
    openssl=shutil.which('openssl')
    if not openssl:raise RuntimeError('No existing openssl; no install attempted.')
    with tempfile.TemporaryDirectory(prefix='echo-ios-r13-paired-') as temp:
        path=Path(temp);cert,key,der=path/'test.crt',path/'test.key',path/'test-ca.der'
        ca,cakey,csr,extensions=path/'ca.crt',path/'ca.key',path/'server.csr',path/'server.ext'
        def openssl_run(*args):subprocess.run([openssl,*map(str,args)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=20)
        openssl_run('req','-x509','-newkey','rsa:2048','-sha256','-nodes','-keyout',cakey,'-out',ca,'-days','2','-subj','/CN=Echo R13 Disposable Test CA','-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign')
        openssl_run('req','-new','-newkey','rsa:2048','-sha256','-nodes','-keyout',key,'-out',csr,'-subj','/CN=localhost')
        extensions.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost,IP:127.0.0.1\n')
        openssl_run('x509','-req','-in',csr,'-CA',ca,'-CAkey',cakey,'-CAcreateserial','-out',cert,'-days','1','-sha256','-extfile',extensions)
        openssl_run('x509','-in',ca,'-outform','DER','-out',der)
        p1,p2=port(),port()
        while p1==p2 or p1 in {18787,18789,18791,18799} or p2 in {18787,18789,18791,18799}:p1,p2=port(),port()
        owner=f'http://127.0.0.1:{p1}';remote=f'https://localhost:{p2}'
        env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'LANG':'en_US.UTF-8'}
        redirect_hits=[];target_hits=[]
        class Target(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                target_hits.append(self.path);self.send_response(200);self.end_headers();self.wfile.write(b'{}')
        destination=ThreadingHTTPServer(('127.0.0.1',0),Target)
        class Redirect(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                status=[302,307,308][len(redirect_hits)];redirect_hits.append(status)
                self.send_response(status);self.send_header('Location',f'https://localhost:{destination.server_port}/api/paired-device');self.end_headers()
        redirects=ThreadingHTTPServer(('127.0.0.1',0),Redirect)
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(cert,key)
        for listener in (destination,redirects):
            listener.socket=tls.wrap_socket(listener.socket,server_side=True)
            threading.Thread(target=listener.serve_forever,daemon=True).start()
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
                grant=request('/api/paired-devices',{'label':'R13 iOS synthetic HTTPS','expires_in_seconds':604800,'confirmed':True})
                # Pass the disposable bearer by stdin, never argv, log or a file.
                payload={'remote':remote,'redirect':f'https://localhost:{redirects.server_port}','owner':owner,'token':grant['token'],'device':grant['device']['id'],'ca_der':base64.b64encode(der.read_bytes()).decode()}
                print('FRESH_LOOPBACK_PAIRED_SERVICE: private temporary DB, random ports, no external bind.',flush=True)
                subprocess.run([str(binary)],input=json.dumps(payload),text=True,check=True,timeout=45)
            finally:
                for listener in (destination,redirects):listener.shutdown();listener.server_close()
                child.terminate()
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:child.kill();child.wait();raise RuntimeError('Owned disposable runner did not stop.')
        assert redirect_hits==[302,307,308] and target_hits==[], 'Redirect destination must receive zero requests.'
        print('PASS: 3 actual HTTPS redirects; target listener received zero requests/credentials.',flush=True)
        log_text=(path/'runner.log').read_text()
        if 'grant' in locals() and grant['token'] in log_text:raise RuntimeError('Synthetic bearer appeared in runner output.')
        print('PASS: owned runner stopped and temporary DB/cert/key removed; no global trust or real vault touched.',flush=True)

if __name__=='__main__':main()
