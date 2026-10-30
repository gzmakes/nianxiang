#!/usr/bin/env python3
"""Adopt the root-generated Swift design/copy resource; keep a standalone snapshot."""
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
source = root.parents[1] / 'shared/generated/EchoSharedReference.swift'
target = root / 'App/SharedDesign.generated.swift'
if not source.is_file():
    if target.is_file():
        print('SHARED_SNAPSHOT: using the packaged generated Swift resource.')
        raise SystemExit(0)
    raise SystemExit('MISSING_SHARED_RESOURCE: include the generated snapshot or the root shared/ directory.')
data = source.read_bytes()
if '--check' in sys.argv:
    if not target.is_file() or target.read_bytes() != data:
        raise SystemExit('SHARED_DRIFT: run python3 sync_shared.py')
    print('SHARED_ADOPTION: current generated Swift resource is in use.')
else:
    target.write_bytes(data)
    print('SHARED_ADOPTION: updated App/SharedDesign.generated.swift')
