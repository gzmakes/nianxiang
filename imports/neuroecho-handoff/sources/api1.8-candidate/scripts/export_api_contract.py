#!/usr/bin/env python3
"""Export FastAPI's declared schema without starting a server or opening a database."""
from pathlib import Path
import argparse, json, sys
ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--check', action='store_true', help='Fail on drift instead of writing.')
args = parser.parse_args()
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from server.main import app
schema = app.openapi()
content = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
target = ROOT / 'shared/api/openapi.json'
if args.check:
    if not target.exists() or target.read_text() != content:
        raise SystemExit('API schema changed. Review client impact, then run scripts/export_api_contract.py.')
    print('Declared API schema matches server source. Response coverage is tracked separately.')
else:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    print('Exported declared schema:', len(schema.get('paths', {})), 'paths. No server started.')
