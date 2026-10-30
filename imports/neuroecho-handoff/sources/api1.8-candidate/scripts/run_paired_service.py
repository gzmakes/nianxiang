#!/usr/bin/env python3
"""One owner worker, loopback UI and an optional explicitly configured TLS entrance.

No account, certificate installation, implicit LAN listener or source-tree data.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import ipaddress
import os
from pathlib import Path
import signal
import stat
import sys

sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parents[1]


def arguments(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--local-port',type=int,default=18787)
    parser.add_argument('--enable-paired-tls',action='store_true')
    parser.add_argument('--paired-host',default='127.0.0.1')
    parser.add_argument('--paired-port',type=int,default=18803)
    parser.add_argument('--tls-certfile',type=Path)
    parser.add_argument('--tls-keyfile',type=Path)
    parser.add_argument('--allow-lan-bind',action='store_true',help='Explicit additional approval for a selected private interface; never wildcard/public.')
    args=parser.parse_args(argv)
    if not all(1<=p<=65535 for p in (args.local_port,args.paired_port)) or args.local_port==args.paired_port:
        parser.error('Use distinct valid ports.')
    args.data_dir=args.data_dir.absolute()
    if args.data_dir.is_symlink() or args.data_dir.resolve().is_relative_to(PROJECT):
        parser.error('data-dir must be outside the source tree.')
    try:address=ipaddress.ip_address(args.paired_host)
    except ValueError:parser.error('paired-host must be an explicit IP interface.')
    if args.enable_paired_tls:
        if address.is_unspecified or address.is_multicast or (not address.is_loopback and not (args.allow_lan_bind and address.is_private)):
            parser.error('Only loopback or an additionally approved private interface may bind.')
        if args.tls_certfile is None or args.tls_keyfile is None or not args.tls_certfile.is_file() or not args.tls_keyfile.is_file():
            parser.error('TLS needs explicitly selected certificate/key files; no HTTP fallback.')
    elif args.allow_lan_bind:
        parser.error('LAN approval alone never starts a listener; enable TLS explicitly.')
    return args


async def serve(args):
    if args.data_dir.exists() and (not args.data_dir.is_dir() or (os.name!='nt' and stat.S_IMODE(args.data_dir.stat().st_mode)&0o077)):
        raise ValueError('Existing data-dir is not a private directory; permissions were not changed.')
    args.data_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    sys.path.insert(0,str(PROJECT))
    from server import core,model_settings
    core.DB_PATH=str(args.data_dir/'data.db')
    model_settings.PATH=str(args.data_dir/'model-settings.json')
    from server.main import app
    from server.paired_app import create_remote_app
    import uvicorn

    class ManagedServer(uvicorn.Server):
        @contextmanager
        def capture_signals(self): yield
        def install_signal_handlers(self): pass

    local=ManagedServer(uvicorn.Config(app,host='127.0.0.1',port=args.local_port,
        lifespan='off',workers=1,proxy_headers=False,forwarded_allow_ips='',access_log=False))
    servers=[local];tasks=[]
    def stop():
        for server in servers:server.should_exit=True
    loop=asyncio.get_running_loop()
    # The lease outlives BOTH listeners and their in-flight work during shutdown.
    # Neither Uvicorn instance is allowed to enter/exit main's lifespan itself.
    async with app.router.lifespan_context(app):
        saved_handlers={sig:signal.getsignal(sig) for sig in (signal.SIGINT,signal.SIGTERM)}
        for sig in saved_handlers:
            try:loop.add_signal_handler(sig,stop)
            except NotImplementedError:signal.signal(sig,lambda *_:loop.call_soon_threadsafe(stop))
        try:
            task=asyncio.create_task(local.serve());tasks.append(task)
            while not local.started:
                if task.done():await task;return
                await asyncio.sleep(.02)
            if args.enable_paired_tls:
                host='['+args.paired_host+']' if ':' in args.paired_host else args.paired_host
                origins={f'https://{host}:{args.paired_port}'}
                if args.paired_host=='127.0.0.1':origins.add(f'https://localhost:{args.paired_port}')
                remote=create_remote_app(app,lambda:core.DB_PATH,allowed_origins=origins)
                tls=ManagedServer(uvicorn.Config(remote,host=args.paired_host,port=args.paired_port,
                    lifespan='off',workers=1,proxy_headers=False,forwarded_allow_ips='',access_log=False,
                    ssl_certfile=str(args.tls_certfile),ssl_keyfile=str(args.tls_keyfile),
                    limit_concurrency=32,timeout_keep_alive=5))
                servers.append(tls);tasks.append(asyncio.create_task(tls.serve()))
            done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in done:await task
        finally:
            stop()
            if tasks:await asyncio.gather(*tasks,return_exceptions=True)
            for sig,handler in saved_handlers.items():
                try:loop.remove_signal_handler(sig)
                except NotImplementedError:pass
                signal.signal(sig,handler)


def main(argv=None):
    args=arguments(argv)
    try:asyncio.run(serve(args))
    except (OSError,ValueError):
        raise SystemExit('Service did not start; check selected local ports and TLS files. No insecure fallback.') from None


if __name__=='__main__':main()
