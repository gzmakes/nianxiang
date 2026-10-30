"""Run the reviewed optional service entry with this package's own dependencies.

It does not select certificates, enable TLS or change the runner's safe defaults.
"""
from pathlib import Path
import runpy
import sys

sys.dont_write_bytecode = True
project = Path(__file__).resolve().parent
if not (project / 'server/main.py').is_file():
    raise SystemExit('Run the packaged helper beside its reviewed server directory.')
if (project / 'deps').is_dir():
    sys.path.insert(0, str(project / 'deps'))
sys.path.insert(0, str(project))
runpy.run_path(str(project / 'scripts/run_paired_service.py'), run_name='__main__')
