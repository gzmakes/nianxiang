#!/usr/bin/env python3
"""Assemble a local macOS developer client from an existing official Electron runtime.
No downloads, credentials, database or Python runtime are bundled. No overwrite.
"""
import argparse,json,os,plistlib,re,shutil,stat,subprocess
from pathlib import Path


def arguments(argv=None):
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--runtime',type=Path,required=True,help='Official Electron.app, version 43.3.0')
 p.add_argument('--project-root',type=Path,required=True)
 p.add_argument('--output',type=Path,required=True,help='A new .app beside the project folder')
 p.add_argument('--adhoc-sign',action='store_true',help='Local ad-hoc signature only; no Developer ID or notarization')
 p.add_argument('--port',type=int,default=18787,help='Fixed local service port; never scan for a different one')
 p.add_argument('--bundle-id',default='cn.xinji.echo.local',help='Distinct identity for an isolated development candidate')
 p.add_argument('--profile',help='Optional isolated desktop app-data profile name, without paths')
 p.add_argument('--python',type=Path,help='Existing absolute executable Python path; preserves a venv symlink. Requires --backend-data-dir.')
 p.add_argument('--backend-data-dir',type=Path,help='Existing private (0700) data directory outside source/App; requires --python. Contents are not read or copied.')
 a=p.parse_args(argv);a.runtime=a.runtime.resolve();a.project_root=a.project_root.resolve();a.output=a.output.absolute()
 if not 1<=a.port<=65535:p.error('port must be 1–65535')
 if not re.fullmatch(r'cn\.xinji\.echo\.[A-Za-z0-9.-]+',a.bundle_id):p.error('bundle-id must be under cn.xinji.echo')
 if a.profile and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,63}',a.profile):p.error('profile must be a safe name, not a path')
 if a.output.suffix!='.app' or a.output.exists() or a.output.is_symlink():p.error('Output must be a new .app path; existing files are never overwritten.')
 if not (a.project_root/'server/main.py').is_file():p.error('project-root is not a 回响 source folder.')
 if bool(a.python)!=bool(a.backend_data_dir):p.error('Specify --python and --backend-data-dir together; never silently use another data profile.')
 if a.python:
  # resolve() would lose the venv entry point and its dependency environment.
  if not a.python.is_absolute() or not a.python.is_file() or not os.access(a.python,os.X_OK):p.error('python must be an existing absolute executable path.')
  a.python=a.python.absolute()
  data=a.backend_data_dir
  if not data.is_absolute() or data.is_symlink() or not data.is_dir():p.error('backend-data-dir must be an existing absolute directory, not a symlink.')
  actual=data.resolve()
  if (actual.is_relative_to(a.project_root) or actual.is_relative_to(a.output.resolve())
      or any(part.lower().endswith('.app') for candidate in (data,actual) for part in candidate.parts)
      or stat.S_IMODE(data.stat().st_mode)&0o077):p.error('backend-data-dir must be private (0700) and outside source/App; permissions are never changed.')
  runner=a.project_root/'scripts/run_paired_service.py'
  if not runner.is_file() or runner.is_symlink():p.error('project-root is missing the reviewed regular scripts/run_paired_service.py entry point.')
  a.backend_data_dir=actual
 else:
  legacy_python=a.project_root/'.venv/bin/python'
  if not legacy_python.is_file() or not os.access(legacy_python,os.X_OK):p.error('No executable project/.venv/bin/python. Specify both --python and --backend-data-dir; an existing Web service alone cannot make this developer shell self-start.')
 return a


def project_pointer(args,target):
 return {'relativeRoot':os.path.relpath(args.project_root,target.resolve()),'port':args.port,
         **({'profile':args.profile} if args.profile else {}),
         **({'python':str(args.python),'backendDataDir':str(args.backend_data_dir)} if args.python else {})}


def main(argv=None):
 a=arguments(argv);runtime=a.runtime;root=a.project_root;out=a.output
 info=plistlib.loads((runtime/'Contents/Info.plist').read_bytes())
 if info.get('CFBundleShortVersionString')!='43.3.0':raise SystemExit('Use the pinned official Electron 43.3.0 runtime, after checking its release SHA256.')
 for name in ('service-connection.js','connection-security.js','selector-preload.js','shared-preload.js','connection-selector.html','connection-selector.css','connection-selector.js'):
  if not (Path(__file__).resolve().parent/name).is_file() or (Path(__file__).resolve().parent/name).is_symlink():raise SystemExit('Missing regular desktop connection source: '+name)
 shutil.copytree(runtime,out,symlinks=True)
 resources=out/'Contents/Resources';target=resources/'app'
 shutil.copytree(Path(__file__).resolve().parent,target,ignore=shutil.ignore_patterns('node_modules','test','__pycache__','.DS_Store','project-root.json','desktop-connection.json','desktop-preferences.json'))
 (target/'project-root.json').write_text(json.dumps(project_pointer(a,target),ensure_ascii=False))
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
 print('Requires this source folder and selected Python/data paths. No portable installer, Developer ID, or notarization.')


if __name__=='__main__':main()
