#!/usr/bin/env python3
"""Use content hashes for local CSS/JS URLs so a release cannot mix cached code."""
from pathlib import Path
import argparse
import hashlib
import re

ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(r'((?:src|href)=[\"\'])(/static/[^\"\'?]+\.(?:js|css))(?:\?v=[^\"\']*)?([\"\'])')

def stamp(text):
    def replace(match):
        path = ROOT / 'web' / match[2].removeprefix('/static/')
        if not path.is_file() or not path.resolve().is_relative_to((ROOT/'web').resolve()):
            raise ValueError('Missing local asset: ' + match[2])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        return match[1] + match[2] + '?v=' + digest + match[3]
    return PATTERN.sub(replace, text)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for name in ('index.html','m.html'):
        target = ROOT/'web'/name
        source = target.read_text(encoding='utf-8')
        result = stamp(source)
        if args.check and source != result:
            raise SystemExit('ASSET_URL_DRIFT: '+name+'; run scripts/stamp_web_assets.py')
        if not args.check: target.write_text(result, encoding='utf-8')
    print('ASSET_HASHES_MATCH' if args.check else 'Local JS/CSS URLs stamped with content hashes.')

if __name__ == '__main__': main()
