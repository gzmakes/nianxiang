#!/usr/bin/env python3
"""Offline, self-contained Apple Silicon .app assembly from pinned local archives.

No system Python/venv copying, account access, runtime downloads or overwrite.
Python is Astral's CPython distribution, not a python.org-signed installer.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile

# Build-time helper imports must not write caches into frozen source trees.
sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location('windows_packaging_helpers', Path(__file__).with_name('package-windows.py'))
common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(common)
PackagingError = common.PackagingError
ELECTRON_VERSION = '43.3.0'
ELECTRON_SHA256 = 'ee939d1564d83d61032b3b3cb23af4e46005a4900c91f0695f7ed793f0ce6e83'
PYTHON_VERSION = '3.13.18'
PYTHON_ASSET = 'cpython-3.13.18+20261026-aarch64-apple-darwin-install_only.tar.gz'
PYTHON_SHA256 = 'e5af2fde6a937a0e0c795a0c595c4efb70578d57463a2657c819992b9b9acbac'
PYTHON_RELEASE = 'https://github.com/astral-sh/python-build-standalone/releases/tag/20261026'
PYTHON_FULL_ASSET = 'cpython-3.13.18+20261026-aarch64-apple-darwin-pgo+lto-full.tar.zst'
PYTHON_FULL_SHA256 = '5706f1fdf82f7ea10b56a9b9cbadfa5f372010568a9794f19e0af4c48d975f34'
MAX_UNPACKED = 2 * 1024**3


def member_path(name):
    if not name or '\\' in name or name.startswith('/') or any(ord(c) < 32 for c in name):
        raise PackagingError('Unsafe archive path.')
    parts = name.rstrip('/').split('/')
    if any(part in ('', '.', '..') for part in parts):
        raise PackagingError('Unsafe archive traversal.')
    return PurePosixPath(*parts)


def safe_link(member, target):
    if not target or target.startswith('/') or '\\' in target or any(ord(c) < 32 for c in target):
        raise PackagingError('Unsafe archive link.')
    parts = list(member.parent.parts)
    for part in target.split('/'):
        if part == '..':
            if len(parts) <= 1:
                raise PackagingError('Archive link escapes its runtime root.')
            parts.pop()
        elif part not in ('', '.'):
            parts.append(part)
    if not parts or parts[0] != member.parts[0]:
        raise PackagingError('Archive link escapes its runtime root.')


def extract_runtime(archive_path, destination, *, kind):
    """Preserve legitimate in-runtime symlinks and execute bits, reject escapes."""
    seen, total, links = set(), 0, []
    expected_root = 'Electron.app' if kind == 'zip' else 'python'
    if kind == 'zip':
        archive = zipfile.ZipFile(archive_path)
        entries = [(i, i.filename, i.file_size, (i.external_attr >> 16), i.is_dir()) for i in archive.infolist()]
    else:
        archive = tarfile.open(archive_path, 'r:gz')
        entries = [(i, i.name, i.size, i.mode, i.isdir()) for i in archive.getmembers()]
    try:
        for item, name, size, mode, directory in entries:
            member = member_path(name)
            key = str(member).casefold()
            if key in seen:
                raise PackagingError('Duplicate/case-colliding archive path.')
            seen.add(key); total += size
            if total > MAX_UNPACKED:
                raise PackagingError('Runtime archive exceeds size limit.')
            if member.parts[0] != expected_root:
                if kind == 'zip' and len(member.parts) == 1 and name in ('LICENSE', 'LICENSES.chromium.html', 'version'):
                    pass
                else:
                    raise PackagingError('Unexpected runtime archive root.')
            out = destination.joinpath(*member.parts)
            link = stat.S_ISLNK(mode) if kind == 'zip' else item.issym()
            if kind == 'zip' and item.flag_bits & 1:
                raise PackagingError('Encrypted runtime archive rejected.')
            if kind != 'zip' and not (item.isfile() or directory or link):
                raise PackagingError('Hardlink/device/special archive member rejected.')
            if link:
                target = archive.read(item).decode('utf-8') if kind == 'zip' else item.linkname
                safe_link(member, target); links.append((out, target)); continue
            if directory:
                out.mkdir(parents=True, exist_ok=True)
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                stream = archive.open(item) if kind == 'zip' else archive.extractfile(item)
                with stream, out.open('xb') as target:
                    shutil.copyfileobj(stream, target)
                out.chmod((mode & 0o777) or 0o644)
        for out, target in links:
            out.parent.mkdir(parents=True, exist_ok=True); out.symlink_to(target)
        for out, _ in links:
            try:
                resolved = out.resolve(strict=True)
            except (OSError, RuntimeError) as error:
                raise PackagingError('Runtime symlink is missing or cyclic.') from error
            if not resolved.is_relative_to((destination / expected_root).resolve()):
                raise PackagingError('Runtime symlink chain escapes archive root.')
    finally:
        archive.close()


def verify_provenance(path):
    data = json.loads(path.read_text())
    asset = data.get('asset', {})
    expected_url = 'https://github.com/astral-sh/python-build-standalone/releases/download/20261026/'
    if (data.get('source') != PYTHON_RELEASE or asset.get('name') != PYTHON_ASSET
            or asset.get('digest') != 'sha256:' + PYTHON_SHA256
            or not asset.get('browser_download_url', '').startswith(expected_url)):
        raise PackagingError('Python official release metadata differs from pinned runtime.')
    full = data.get('full_asset', {})
    if (full.get('name') != PYTHON_FULL_ASSET or full.get('digest') != 'sha256:' + PYTHON_FULL_SHA256
            or not full.get('browser_download_url', '').startswith(expected_url)):
        raise PackagingError('Python full-license archive provenance differs from pinned release.')


def extract_licenses(full_tar, python):
    """The install-only tar omits full-distribution third-party notices."""
    try:
        archive = tarfile.open(full_tar, 'r:*')
    except tarfile.CompressionError as error:
        raise PackagingError('Reading the full .tar.zst license archive requires host Python 3.14 zstd support.') from error
    with archive:
        members = archive.getmembers()
        names = {m.name:m for m in members}
        metadata_member = names.get('python/PYTHON.json')
        if not metadata_member or not metadata_member.isfile():
            raise PackagingError('Full Python archive has no regular PYTHON.json.')
        raw = archive.extractfile(metadata_member).read()
        metadata = json.loads(raw)
        if metadata.get('python_version') != PYTHON_VERSION or metadata.get('target_triple') != 'aarch64-apple-darwin' or metadata.get('python_tag') != 'cp313':
            raise PackagingError('Python metadata target/version differs from bundled interpreter.')
        executable = names.get('python/' + metadata['python_exe'])
        if not executable or not executable.isfile() or hashlib.sha256(archive.extractfile(executable).read()).hexdigest() != common.sha256(python/'bin/python3.13'):
            raise PackagingError('Install-only interpreter differs from full distribution being licensed.')
        with (python/'PYTHON.json').open('xb') as target: target.write(raw)
        copied = set()
        for item in members:
            if not item.name.startswith('python/licenses/') or item.isdir(): continue
            member = member_path(item.name)
            if not item.isfile() or item.size > 4*1024**2:
                raise PackagingError('Unexpected Python license member.')
            out = python.joinpath(*member.parts[1:]);out.parent.mkdir(parents=True,exist_ok=True)
            with archive.extractfile(item) as stream, out.open('xb') as target:
                shutil.copyfileobj(stream,target)
            copied.add(str(member.relative_to('python')))
        required = set()
        def collect(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == 'license_path' and isinstance(item,str): required.add(item)
                    elif key == 'license_paths': required.update(item)
                    else: collect(item)
            elif isinstance(value,list):
                for item in value: collect(item)
        collect(metadata)
        if not required or not required.issubset(copied):
            raise PackagingError('Missing Python distribution license texts referenced by metadata.')
        return {'copied_license_files':len(copied),'all_metadata_license_paths_present':True,
                'apple_sdk_deployment_target':metadata.get('apple_sdk_deployment_target')}


def verify_wheels(folder, lock):
    hashes = common.validate_lock(lock); records = []
    from email.parser import Parser
    for wheel in sorted(folder.glob('*.whl')):
        digest = common.sha256(wheel)
        if digest not in hashes:
            raise PackagingError('Wheel absent from hashed lock: ' + wheel.name)
        common.inspect_zip(wheel)
        with zipfile.ZipFile(wheel) as archive:
            metadata_names = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
            wheel_names = [n for n in archive.namelist() if n.endswith('.dist-info/WHEEL')]
            if len(metadata_names) != 1 or len(wheel_names) != 1:
                raise PackagingError('Invalid wheel metadata layout.')
            metadata = Parser().parsestr(archive.read(metadata_names[0]).decode())
            tags = Parser().parsestr(archive.read(wheel_names[0]).decode()).get_all('Tag', [])
            if not tags or any(not re.fullmatch(r'(any|macosx_[0-9]+_[0-9]+_(arm64|universal2))', t.rsplit('-', 1)[-1]) for t in tags):
                raise PackagingError('Only arm64/universal2 macOS or universal wheels accepted.')
            records.append({'filename':wheel.name, 'name':metadata['Name'], 'version':metadata['Version'], 'sha256':digest, 'tags':tags})
    if not records:
        raise PackagingError('Empty wheelhouse.')
    return records


def install_dependencies(args, target, *, dry_run=False):
    command = [args.uv,'pip','install','--target',str(target),'--python-version','3.13',
               '--python-platform','aarch64-apple-darwin','--only-binary',':all:', '--require-hashes',
               '--no-index','--find-links',str(args.wheels_dir),'--offline','--no-config',
               '--no-python-downloads','--no-cache','--link-mode','copy','--requirements',str(args.requirements_lock)]
    if dry_run: command.append('--dry-run')
    env = {k:v for k,v in os.environ.items() if not k.upper().startswith(('UV_','PIP_','PYTHON')) and k != 'VIRTUAL_ENV'}
    result = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode:
        raise PackagingError('Offline dependency installation failed:\n' + result.stdout)
    return result.stdout


def assemble(args, staged, wheels):
    extract_runtime(args.electron_zip, staged, kind='zip')
    app = staged/'Electron.app'; resources = app/'Contents/Resources'
    (resources/'default_app.asar').unlink(missing_ok=True)
    (resources/'electron.asar').unlink(missing_ok=True)
    code, project = resources/'app', resources/'project'
    common.copy_clean_tree(args.project_root/'desktop', code, {'.js','.json','.html','.css','.png','.ico','.icns','.md'})
    common.write_json(code/'project-root.json', {'relativeRoot':'../project','port':args.port,'profile':args.profile})
    common.copy_clean_tree(args.project_root/'server', project/'server', {'.py'})
    common.copy_clean_tree(args.project_root/'web', project/'web', {'.js','.mjs','.html','.css','.svg','.png','.jpg','.jpeg','.webp','.gif','.webmanifest','.woff','.woff2','.mp3','.wav'})
    common.copy_clean_tree(args.project_root/'shared', project/'shared', {'.json','.js','.mjs','.css','.swift','.kt','.md'})
    for name in ('SOUL.md','requirements.txt','design.md'):
        common.copy_file(args.project_root/name, project/name)
    common.copy_file(args.project_root/'desktop/portable_backend.py', project/'desktop_bootstrap.py')
    common.copy_file(args.project_root/'scripts/run_paired_service.py', project/'scripts/run_paired_service.py')
    common.copy_file(args.project_root/'desktop/paired_service_bootstrap.py', project/'paired_service_bootstrap.py')
    common.copy_file(args.requirements_lock, project/'requirements-macos-arm64.lock')
    common.write_json(resources/'SOURCE-MANIFEST.json', common.inventory(app, [*code.rglob('*'),*project.rglob('*')]))
    extract_runtime(args.python_tar, project, kind='tar')
    python = project/'python/bin/python3.13'
    if not python.is_file() or not os.access(python, os.X_OK):
        raise PackagingError('Missing executable bundled Python3.13.')
    licensing = extract_licenses(args.python_full_tar, project/'python')
    install_log = install_dependencies(args, project/'deps')
    (resources/'DEPENDENCY-INSTALL.log').write_text(install_log)
    common.write_json(resources/'DEPENDENCIES.json', {'target':'cp313-macos-arm64','lock_sha256':common.sha256(args.requirements_lock),'wheels':wheels})
    common.copy_file(args.python_provenance, resources/'PYTHON-PROVENANCE.json')
    for name in ('LICENSE','LICENSES.chromium.html'):
        common.copy_file(staged/name, resources/name)
    common.copy_file(code/'assets/echo.icns', resources/'echo.icns')
    plist = app/'Contents/Info.plist'
    info = plistlib.loads(plist.read_bytes())
    if info.get('CFBundleShortVersionString') != ELECTRON_VERSION:
        raise PackagingError('Electron bundle version mismatch.')
    info.update(CFBundleIdentifier=args.bundle_id, CFBundleDisplayName='回响', CFBundleName='回响',
                CFBundleShortVersionString='0.2.0', CFBundleVersion='15', CFBundleIconFile='echo.icns')
    plist.write_bytes(plistlib.dumps(info))
    common.write_json(resources/'BUILD-MANIFEST.json', {
        'product':'回响 macOS arm64 portable developer app','architecture':'arm64',
        'electron_version':ELECTRON_VERSION,'electron_sha256':ELECTRON_SHA256,
        'python_version':PYTHON_VERSION,'python_sha256':PYTHON_SHA256,'python_source':PYTHON_RELEASE,
        'python_full_archive_sha256':PYTHON_FULL_SHA256,'python_licensing':licensing,
        'electron_LSMinimumSystemVersion':info.get('LSMinimumSystemVersion'),
        'runtime_check':'NOT_RUN_BY_BUILDER','GUI_acceptance':'NOT_RUN',
        'private_data_or_credentials_bundled':False,'signing':'AD_HOC' if args.adhoc_sign else 'UNSIGNED_AFTER_MODIFICATION',
        'publisher_identity_or_notarization':False,'source_manifest_sha256':common.sha256(resources/'SOURCE-MANIFEST.json')})
    common.verify_hash(args.electron_zip,ELECTRON_SHA256); common.verify_hash(args.python_tar,PYTHON_SHA256)
    common.verify_hash(args.python_full_tar,PYTHON_FULL_SHA256)
    if args.adhoc_sign:
        subprocess.run(['/usr/bin/codesign','--force','--deep','--sign','-',str(app)],check=True)
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True)
    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project-root','electron-zip','python-tar','python-full-tar','python-provenance','requirements-lock','wheels-dir','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--uv',default=shutil.which('uv') or 'uv')
    parser.add_argument('--port',type=int,default=18787)
    parser.add_argument('--profile',default='cn.xinji.echo.portable')
    parser.add_argument('--bundle-id',default='cn.xinji.echo.portable')
    parser.add_argument('--adhoc-sign',action='store_true')
    parser.add_argument('--preflight',action='store_true')
    args = parser.parse_args(argv)
    try:
        for name in ('project_root','electron_zip','python_tar','python_full_tar','python_provenance','requirements_lock','wheels_dir','output'):
            setattr(args,name,getattr(args,name).absolute())
        if args.output.is_symlink() or args.output.exists() or args.output.suffix != '.app' or not args.output.parent.is_dir():
            raise PackagingError('Output must be a NEW .app; never overwrite.')
        args.project_root = args.project_root.resolve(strict=True)
        if args.output.resolve().is_relative_to(args.project_root):
            raise PackagingError('Output must be outside project source.')
        if not 1 <= args.port <= 65535 or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]{0,63}',args.profile) or not re.fullmatch(r'cn\.xinji\.echo\.[a-zA-Z0-9.-]+',args.bundle_id):
            raise PackagingError('Invalid port/profile/bundle ID.')
        if json.loads((args.project_root/'desktop/package.json').read_text()).get('devDependencies',{}).get('electron') != ELECTRON_VERSION:
            raise PackagingError('Desktop Electron version differs from pinned runtime.')
        common.verify_connection_sources(args.project_root)
        common.verify_hash(args.electron_zip,ELECTRON_SHA256); common.verify_hash(args.python_tar,PYTHON_SHA256)
        common.verify_hash(args.python_full_tar,PYTHON_FULL_SHA256)
        verify_provenance(args.python_provenance)
        wheels = verify_wheels(args.wheels_dir,args.requirements_lock)
        with tempfile.TemporaryDirectory(prefix='.echo-macos-build-',dir=args.output.parent) as temp:
            temp = Path(temp)
            if args.preflight:
                install_dependencies(args,temp/'deps',dry_run=True)
                print('PREFLIGHT_OK: pinned arm64 runtimes and',len(wheels),'locked wheels; no output published.'); return 0
            app = assemble(args,temp,wheels)
            # Publish atomically to a previously absent path, never rename over user data.
            args.output.mkdir(exist_ok=False)
            for child in app.iterdir(): child.rename(args.output/child.name)
        print('BUILD_OK:',args.output.name,'; self-contained runtime; GUI NOT_RUN; no notarization.')
        return 0
    except (PackagingError,OSError,ValueError,tarfile.TarError,zipfile.BadZipFile,subprocess.SubprocessError) as error:
        parser.exit(2,'BUILD_NOT_COMPLETED: '+str(error)+'\n')


if __name__ == '__main__':
    raise SystemExit(main())
