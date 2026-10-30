"""Verify renamed import paths, bytes and JSON without third-party packages."""
from pathlib import Path
import hashlib
import json
import ast

root = Path(__file__).resolve().parents[1]
base = root / 'imports' / 'neuroecho-handoff'
manifest = json.loads((base / 'import-manifest.json').read_text(encoding='utf-8'))
errors = []
for item in manifest['files']:
    path = root / item['path']
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
        errors.append('Missing/changed: ' + item['path'])
count = 0
for path in base.rglob('*'):
    if not path.is_file() or '__pycache__' in path.parts:
        continue
    if '\u5fc3\u8ff9\u56de\u54cd' in path.relative_to(base).as_posix():
        errors.append('Old name in path: ' + str(path))
    try:
        text = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        continue
    if '\u5fc3\u8ff9\u56de\u54cd' in text:
        errors.append('Old name in content: ' + str(path))
    try:
        if path.suffix == '.json':
            json.loads(text)
        elif path.suffix == '.py':
            ast.parse(text)
    except (ValueError, SyntaxError) as exc:
        errors.append(str(path) + ': ' + str(exc))
    count += 1
print(json.dumps({'verified_manifest_entries':len(manifest['files']), 'text_files_checked':count, 'errors':errors},ensure_ascii=False,indent=2))
raise SystemExit(bool(errors))
