"""Run the real Swift client against a fresh disposable local service only.

Invoke with the project's Python environment (FastAPI/uvicorn installed).
No existing service, DB, account, or model is used. Temporary data is discarded.
"""
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time


def main():
    ios = Path(__file__).resolve().parents[1]
    root = ios.parents[1]
    sys.path.insert(0, str(root))
    # Compile before starting the service. No network can occur during compilation.
    binary = ios / '.build/host-checks/round9-live'
    binary.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['swiftc', '-parse-as-library', *map(str, sorted((ios/'Sources/EchoCore').glob('*.swift'))),
                    str(ios/'HostChecks/Round9Smoke.swift'), '-o', str(binary)], check=True)
    import uvicorn
    from server import core
    with tempfile.TemporaryDirectory(prefix='echo-ios-r9-', dir=binary.parent) as task_dir:
        core.DB_PATH = str(Path(task_dir)/'synthetic.db')
        from server.main import app
        allowed = {'/api/capabilities','/api/conversation','/api/followups','/api/companion-boundary'}
        calls = []

        @app.middleware('http')
        async def synthetic_only(request, call_next):
            path = request.url.path
            if path not in allowed and not (path.startswith('/api/followups/') and request.method == 'PATCH' and path.count('/') == 3):
                raise AssertionError('Smoke attempted a disallowed endpoint: '+path)
            calls.append((request.method,path))
            return await call_next(request)

        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0))
            listener.listen(64)
            port=listener.getsockname()[1]
            if port == 18789:
                raise AssertionError('Reserved preview port selected; refuse test.')
            server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
            worker=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True)
            worker.start()
            for _ in range(100):
                if server.started:break
                if not worker.is_alive():raise RuntimeError('Fresh test server failed to start.')
                time.sleep(.05)
            else:raise RuntimeError('Fresh test server did not become ready.')
            print('FRESH_SYNTHETIC_SERVICE:',f'http://127.0.0.1:{port}','temporary DB, removed after smoke.',flush=True)
            try:
                subprocess.run([str(binary),'--fresh-synthetic-service',f'http://127.0.0.1:{port}'],check=True)
            finally:
                server.should_exit=True
                worker.join(timeout=5)
                if worker.is_alive():raise RuntimeError('Disposable service did not stop.')
            assert len([x for x in calls if x == ('PUT','/api/companion-boundary')]) == 3
            assert not any('/contact/' in path or path == '/api/chat' for _,path in calls)
            print('PASS: audited',len(calls),'actual HTTP requests; exactly 3 explicit boundary PUTs, no model/contact/source/device endpoint. Fresh service stopped.',flush=True)


if __name__ == '__main__':main()
