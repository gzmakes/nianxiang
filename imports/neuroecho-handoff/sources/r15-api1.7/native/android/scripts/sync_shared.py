#!/usr/bin/env python3
"""Copy reviewed generated Kotlin resources into the native source set.

The copied resource ships in standalone Android source ZIPs. In the full monorepo,
run the root generator first. No credentials, network or Gradle are involved.
"""
from pathlib import Path
import argparse

project = Path(__file__).resolve().parents[1]
source = project.parents[1] / 'shared/generated/EchoSharedReference.kt'
target = project / 'app/src/main/java/cn/xinji/echo/shared/EchoSharedReference.kt'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--check', action='store_true')
args = parser.parse_args()
if not source.is_file():
    if target.is_file():
        print('Standalone Android package: using included generated shared resource.')
        raise SystemExit(0)
    raise SystemExit('Missing shared generated source and included resource.')
if args.check:
    if not target.is_file() or target.read_bytes() != source.read_bytes():
        raise SystemExit('Shared Kotlin resource drift; run scripts/sync_shared.py after review.')
else:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
print('Android shared resource matches.' if args.check else 'Synced Android shared Kotlin resource.')
