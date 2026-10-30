"""Build portable source/model bundle; exclude recordings, caches and environments."""
from pathlib import Path
import json,hashlib,zipfile
root=Path(__file__).resolve().parents[1]
files=[p for p in root.rglob('*') if p.is_file() and not any(x in p.relative_to(root).parts for x in ['__pycache__','recordings','.venv','.git']) and p.suffix not in ['.zip','.pyc'] and p.name not in ['package_manifest.json','validation_feedback.json']]
manifest={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
mp=root/'package_manifest.json';mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
out=root.parent/'MindLink_Windows_API_package.zip'
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
 for p in files+[mp]:z.write(p,'mindlink_live/'+str(p.relative_to(root)))
with zipfile.ZipFile(out) as z:assert z.testzip() is None
print(out, out.stat().st_size, 'bytes',len(files)+1,'files')
