"""Actual Swift client/Store to disposable backend, with bounded response-fault middleware.
Never uses a preview DB, credentials, chat model or notification endpoint.
"""
from pathlib import Path
from hashlib import sha256
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time


def main():
    ios=Path(__file__).resolve().parents[1]
    root=ios.parents[1]
    seal_path=root.parent/'round11-backend-seal.json'
    seal=json.loads(seal_path.read_text())
    for relative,expected in seal['server_source_hashes'].items():
        assert sha256((root/relative).read_bytes()).hexdigest() == expected, relative+' drifted after backend seal'
    print('BACKEND_SEAL_VERIFIED:',seal['sealed_at'],sha256(seal_path.read_bytes()).hexdigest(),len(seal['server_source_hashes']),'server files',flush=True)
    sys.path.insert(0,str(root))
    binary=ios/'.build/host-checks/round11-ledger-live'
    binary.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(['swiftc','-parse-as-library',*map(str,sorted((ios/'Sources/EchoCore').glob('*.swift'))),str(ios/'App/SharedDesign.generated.swift'),str(ios/'App/MoodStore.swift'),str(ios/'HostChecks/Round11MoodLedgerSmoke.swift'),'-o',str(binary)],check=True)
    import uvicorn
    from fastapi.responses import JSONResponse
    from server import core
    with tempfile.TemporaryDirectory(prefix='echo-ios-r11-ledger-',dir=binary.parent) as task_dir:
        core.DB_PATH=str(Path(task_dir)/'synthetic.db')
        from server.main import app
        allowed={'/api/capabilities','/api/conversation','/api/companion-boundary','/api/followups','/api/moods','/api/mood-operations'}
        calls=[];faulted=set();markers={};applies={};cancels={}
        @app.middleware('http')
        async def synthetic_only(request,call_next):
            path=request.url.path;method=request.method
            assert path in allowed or (path.startswith('/api/mood-operations/') and path.count('/') in {3,4}),path
            assert method == 'GET' or path == '/api/mood-operations' or path.endswith('/cancel'),(method,path)
            calls.append((method,path))
            body=None;request_id=None;note=''
            if method == 'POST':
                body=await request.json()
                if path == '/api/mood-operations':
                    request_id=body['request_id'];note=json.loads(body['operation_json']).get('note','')
                    markers[request_id]=note
                    applies.setdefault(request_id,[]).append(body['operation_json'])
                    if note.startswith(('[IOS_R11_DROP_BEFORE]','[IOS_R11_CANCEL_BEFORE]')) and ('apply',request_id) not in faulted:
                        faulted.add(('apply',request_id));return JSONResponse({'detail':'synthetic pre-dispatch response fault'},503)
                else:
                    request_id=path.split('/')[-2];note=markers.get(request_id,'')
                    assert set(body) == {'session_id','operation_sha256','kind','confirmed'}
                    cancels.setdefault(request_id,[]).append((body['operation_sha256'],body['kind']))
                    if note.startswith('[IOS_R11_CANCEL_BEFORE]') and ('cancel',request_id) not in faulted:
                        faulted.add(('cancel',request_id));return JSONResponse({'detail':'synthetic cancel pre-dispatch response fault'},503)
            response=await call_next(request)
            if method == 'POST' and path == '/api/mood-operations' and note.startswith('[IOS_R11_DROP_AFTER]') and ('after',request_id) not in faulted:
                assert response.status_code == 200
                faulted.add(('after',request_id));return JSONResponse({'detail':'synthetic lost committed response'},503)
            return response
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen(64)
            port=listener.getsockname()[1]
            assert port not in {18787,18789,18791}
            server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
            worker=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);worker.start()
            for _ in range(100):
                if server.started:break
                if not worker.is_alive():raise RuntimeError('Fresh server failed')
                time.sleep(.05)
            else:raise RuntimeError('Fresh server startup timeout')
            print('FRESH_SYNTHETIC_SERVICE:',f'http://127.0.0.1:{port}','temporary DB, deterministic test-only HTTP503 injection',flush=True)
            try:subprocess.run([str(binary),'--fresh-synthetic-service',f'http://127.0.0.1:{port}'],check=True)
            finally:
                server.should_exit=True;worker.join(timeout=5)
                assert not worker.is_alive(),'Fresh service did not stop'
        assert len(faulted) == 4
        for rid,raws in applies.items():
            if markers[rid].startswith('[IOS_R11_DROP_AFTER]'):assert len(raws) == 1
            if markers[rid].startswith('[IOS_R11_DROP_BEFORE]'):assert len(raws) == 2 and raws[0] == raws[1]
            if markers[rid].startswith('[IOS_R11_CANCEL_BEFORE]'):
                # second apply is a deliberate late raw request AFTER confirmed tombstone, never Store retry
                assert len(raws) == 2 and raws[0] == raws[1]
                assert len(cancels[rid]) == 2 and cancels[rid][0] == cancels[rid][1]
        print('PASS: audited',len(calls),'actual HTTP requests, 4 deterministic response faults; exact retry payloads and metadata-only cancel; no chat/model/source/account/device/contact endpoint. Fresh service stopped.',flush=True)


if __name__ == '__main__':main()
