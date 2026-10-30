"""Runner TLS/lease regressions: loopback only, private temporary certificates."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import time
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

from server import core,main
from server.runtime_lock import DatabaseLease

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/run_paired_service.py'
SPEC=importlib.util.spec_from_file_location('paired_runner',SCRIPT)
runner=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(runner)


@pytest.mark.parametrize('host',['0.0.0.0','::','8.8.8.8','192.168.1.10'])
def test_runner_never_implicitly_binds_network_interfaces(tmp_path,host):
    with pytest.raises(SystemExit):runner.arguments(['--data-dir',str(tmp_path/'private'),'--enable-paired-tls','--paired-host',host])


def test_runner_rejects_existing_broad_data_dir_without_changing_permissions(tmp_path):
    data=tmp_path/'wide';data.mkdir(mode=0o755);before=data.stat().st_mode
    args=runner.arguments(['--data-dir',str(data)])
    with pytest.raises(ValueError):asyncio.run(runner.serve(args))
    assert data.stat().st_mode==before and not list(data.iterdir())


def test_outer_lease_retained_until_delayed_tls_drain(tmp_path,monkeypatch):
    import uvicorn
    evidence=[]
    class FakeServer:
        def __init__(self,config):self.config=config;self.started=False;self.should_exit=False
        async def serve(self):
            assert self.config.lifespan=='off'
            self.started=True
            if self.config.ssl_certfile:
                while not self.should_exit:await asyncio.sleep(.01)
                # The local listener has already returned; simulate pending TLS work.
                with pytest.raises(RuntimeError):
                    with DatabaseLease(core.DB_PATH):pass
                await asyncio.sleep(.02);evidence.append('lease held while TLS drains')
            else:await asyncio.sleep(.06)
    monkeypatch.setattr(uvicorn,'Server',FakeServer)
    args=SimpleNamespace(data_dir=tmp_path/'private',local_port=19001,enable_paired_tls=True,paired_host='127.0.0.1',paired_port=19002,tls_certfile=tmp_path/'synthetic.crt',tls_keyfile=tmp_path/'synthetic.key')
    asyncio.run(runner.serve(args))
    assert evidence==['lease held while TLS drains']
    with DatabaseLease(core.DB_PATH):pass


def _port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


def test_real_loopback_tls_runner_uses_normal_certificate_validation_and_one_lease(tmp_path):
    openssl=shutil.which('openssl')
    if not openssl:pytest.skip('No local openssl; no installation attempted.')
    cert,key=tmp_path/'ca.crt',tmp_path/'private.key'
    subprocess.run([openssl,'req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=15)
    p1,p2=_port(),_port()
    while p1==p2:p2=_port()
    data=tmp_path/'profile'
    env={k:v for k,v in os.environ.items() if not k.upper().startswith(('XINJI_','PYTHON')) and k!='VIRTUAL_ENV'}
    log=(tmp_path/'runner.log').open('w')
    child=subprocess.Popen([sys.executable,str(SCRIPT),'--data-dir',str(data),'--local-port',str(p1),'--enable-paired-tls','--paired-host','127.0.0.1','--paired-port',str(p2),'--tls-certfile',str(cert),'--tls-keyfile',str(key)],env=env,stdout=log,stderr=subprocess.STDOUT)
    def request(url,body=None,headers=None,context=None):
        req=urllib.request.Request(url,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json',**(headers or {})})
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context))
            with opener.open(req,timeout=2) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as error:return error.code,json.load(error)
    try:
        until=time.monotonic()+15
        while True:
            try:
                if request(f'http://127.0.0.1:{p1}/api/health')[0]==200:break
            except OSError:pass
            assert child.poll() is None and time.monotonic()<until
            time.sleep(.05)
        status,grant=request(f'http://127.0.0.1:{p1}/api/paired-devices',{'label':'TLS synthetic','confirmed':True});assert status==201
        context=ssl.create_default_context(cafile=str(cert));assert context.check_hostname and context.verify_mode==ssl.CERT_REQUIRED
        h={'Authorization':'Bearer '+grant['token']};url=f'https://localhost:{p2}'
        until=time.monotonic()+10
        while True:
            try:status,verified=request(url+'/api/paired-device',headers=h,context=context);break
            except OSError:
                assert time.monotonic()<until;time.sleep(.05)
        assert status==200 and verified['service_instance_id']==grant['service_instance_id']
        h['X-Echo-Service-Instance']=grant['service_instance_id']
        assert request(url+'/api/conversation',headers=h,context=context)[1]['session']['id']==grant['conversation_id']
        assert request(url+'/api/settings/model',headers=h,context=context)[0]==403
        with pytest.raises(RuntimeError):
            with DatabaseLease(data/'data.db'):pass
        assert request(f'http://127.0.0.1:{p1}/api/paired-devices/'+grant['device']['id']+'/revoke',{'confirmed':True})[0]==200
        assert request(url+'/api/paired-device',headers=h,context=context)[0]==401
    finally:
        child.terminate()
        try:child.wait(timeout=15)
        except subprocess.TimeoutExpired:child.kill();child.wait();pytest.fail('Owned TLS runner failed to stop gracefully.')
        log.close()
    assert child.returncode==0
    with DatabaseLease(data/'data.db'):pass
    assert grant['token'] not in (tmp_path/'runner.log').read_text()
