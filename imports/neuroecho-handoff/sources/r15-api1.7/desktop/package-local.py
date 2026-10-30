#!/usr/bin/env python3
"""Assemble a local macOS developer client from an existing official Electron runtime.
No downloads, credentials, database or Python runtime are bundled. No overwrite.
"""
import argparse,json,os,plistlib,re,shutil,subprocess
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--runtime',type=Path,required=True,help='Official Electron.app, version 43.3.0')
p.add_argument('--project-root',type=Path,required=True)
p.add_argument('--output',type=Path,required=True,help='A new .app beside the project folder')
p.add_argument('--adhoc-sign',action='store_true',help='Local ad-hoc signature only; no Developer ID or notarization')
p.add_argument('--port',type=int,default=18787,help='Local service port; a separate development candidate may use its own port')
p.add_argument('--bundle-id',default='cn.xinji.echo.local',help='Distinct identity for an isolated development candidate')
p.add_argument('--profile',help='Optional isolated app-data profile name, without paths')
a=p.parse_args();runtime=a.runtime.resolve();root=a.project_root.resolve();out=a.output.absolute()
if not 1<=a.port<=65535:p.error('port must be 1–65535')
if not re.fullmatch(r'cn\.xinji\.echo\.[A-Za-z0-9.-]+',a.bundle_id):p.error('bundle-id must be under cn.xinji.echo')
if a.profile and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,63}',a.profile):p.error('profile must be a safe name, not a path')
if out.suffix!='.app' or out.exists():p.error('Output must be a new .app path; existing files are never overwritten.')
if not (root/'server/main.py').is_file():p.error('project-root is not a 回响 source folder.')
info=plistlib.loads((runtime/'Contents/Info.plist').read_bytes())
if info.get('CFBundleShortVersionString')!='43.3.0':p.error('Use the pinned official Electron 43.3.0 runtime, after checking its release SHA256.')
for name in ('service-connection.js','connection-security.js','selector-preload.js','shared-preload.js','connection-selector.html','connection-selector.css','connection-selector.js'):
 if not (Path(__file__).resolve().parent/name).is_file() or (Path(__file__).resolve().parent/name).is_symlink():p.error('Missing regular desktop connection source: '+name)
shutil.copytree(runtime,out,symlinks=True)
resources=out/'Contents/Resources';target=resources/'app'
shutil.copytree(Path(__file__).resolve().parent,target,ignore=shutil.ignore_patterns('node_modules','test','__pycache__','.DS_Store','project-root.json','desktop-connection.json','desktop-preferences.json'))
(target/'project-root.json').write_text(json.dumps({'relativeRoot':os.path.relpath(root,target),'port':a.port,**({'profile':a.profile} if a.profile else {})},ensure_ascii=False))
(resources/'electron.asar').unlink(missing_ok=True)
shutil.copy2(target/'assets/echo.icns',resources/'echo.icns')
info.update(CFBundleIdentifier=a.bundle_id,CFBundleDisplayName='回响',CFBundleName='回响',CFBundleShortVersionString='0.2.0',CFBundleVersion='15',CFBundleIconFile='echo.icns')
(out/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
for name in ('LICENSE','LICENSES.chromium.html'):
 if (runtime.parent/name).is_file():shutil.copy2(runtime.parent/name,resources/name)
if a.adhoc_sign:
 subprocess.run(['codesign','--force','--deep','--sign','-',str(out)],check=True)
 subprocess.run(['codesign','--verify','--deep','--strict',str(out)],check=True)
print('Local developer client:',out)
print('Requires this sibling project and an available local backend. No portable installer, Developer ID, or notarization.')
