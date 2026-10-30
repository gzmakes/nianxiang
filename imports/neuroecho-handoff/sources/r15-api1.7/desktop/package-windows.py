#!/usr/bin/env python3
"""Build a Windows x64 portable folder from verified LOCAL runtimes and wheels.

No downloads, account access, credentials, private DB, Windows execution or overwrite.
Use uv pip compile --python-version 3.13 --python-platform x86_64-pc-windows-msvc
--only-binary :all: --generate-hashes to prepare the lock, then a local wheelhouse.
"""
from __future__ import annotations

import argparse
import base64
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile

ELECTRON_VERSION = '43.3.0'
ELECTRON_SHA256 = '18528bedc6a9b04bdc5efb7b803cbc3cb0e5ea6415d54046e23d464d89a00da9'
PYTHON_VERSION = '3.13.13'
# This is the exact -embed-amd64.zip, not the different -embeddable-amd64.zip.
# Digest matched the TLS-fetched python.org .sigstore bundle; no claim here that
# the Sigstore signature/certificate chain itself was cryptographically verified.
PYTHON_SHA256 = '8766a8775746235e23cf5aee5027ab1060bb981d93110577adcf3508aa0cbd55'
MAX_UNPACKED = 2 * 1024**3
PRIVATE_NAMES = {'data.db', 'model-settings.json', 'auth.json', '.env', 'project-root.json', 'desktop-connection.json', 'desktop-preferences.json'}
SKIP_DIRS = {'node_modules', '__pycache__', '.venv', '.git', 'test', 'tests', 'dist', '.build', '.gradle'}
RESERVED = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))}


class PackagingError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_hash(path: Path, expected: str) -> str:
    if not path.is_file() or path.is_symlink():
        raise PackagingError(f'Expected regular local file: {path.name}')
    actual = sha256(path)
    if actual != expected:
        raise PackagingError(f'SHA256 mismatch for {path.name}: expected {expected}, got {actual}. Partial downloads are not accepted.')
    return actual


def member_path(name: str) -> PurePosixPath:
    if not name or '\\' in name or ':' in name or name.startswith('/') or any(ord(c) < 32 for c in name):
        raise PackagingError(f'Unsafe archive member: {name!r}')
    parts = name.rstrip('/').split('/')
    if any(part in ('', '.', '..') or part.endswith((' ', '.')) or part.split('.')[0].casefold() in RESERVED for part in parts):
        raise PackagingError(f'Unsafe Windows archive path: {name!r}')
    return PurePosixPath(*parts)


def inspect_zip(path: Path, required=()) -> set[str]:
    seen, names, total = set(), set(), 0
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            member = member_path(item.filename)
            key = str(member).casefold()
            if key in seen:
                raise PackagingError(f'Duplicate/case-colliding ZIP member: {item.filename}')
            seen.add(key); names.add(str(member)); total += item.file_size
            if stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                raise PackagingError(f'ZIP symlink/encrypted member rejected: {item.filename}')
            if total > MAX_UNPACKED:
                raise PackagingError('Archive exceeds the unpacked size limit.')
        if not set(required).issubset(names):
            raise PackagingError(f'{path.name} missing required runtime files: {sorted(set(required)-names)}')
    return names


def extract_zip(path: Path, target: Path) -> None:
    inspect_zip(path)
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            out = target.joinpath(*member_path(item.filename).parts)
            if item.is_dir():
                out.mkdir(parents=True, exist_ok=True)
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, out.open('xb') as dest:
                    shutil.copyfileobj(source, dest)


def validate_lock(path: Path) -> set[str]:
    text = path.read_text(encoding='utf-8')
    hashes = set(re.findall(r'--hash=sha256:([0-9a-fA-F]{64})', text))
    if not hashes:
        raise PackagingError('Dependency lock must contain uv-generated SHA256 hashes.')
    for line in text.splitlines():
        value = line.strip()
        if not value or value.startswith('#') or value.startswith('--hash='):
            continue
        if '://' in value or '@' in value or value.startswith('-') or '==' not in value:
            raise PackagingError('Only pinned name==version requirements and hashes are accepted; no URLs, nested files or index configuration.')
    return hashes


def verify_python_provenance(path: Path) -> None:
    bundle = json.loads(path.read_text(encoding='utf-8'))
    digest = bundle.get('messageSignature', {}).get('messageDigest', {})
    if digest.get('algorithm') != 'SHA2_256' or base64.b64decode(digest.get('digest', ''), validate=True).hex() != PYTHON_SHA256:
        raise PackagingError('Python provenance bundle digest does not match the pinned exact embed archive.')


def verify_wheelhouse(folder: Path, lock: Path) -> list[dict]:
    hashes = validate_lock(lock)
    wheels = sorted(folder.glob('*.whl'))
    if not wheels:
        raise PackagingError('Local wheelhouse is empty.')
    records = []
    for wheel in wheels:
        digest = sha256(wheel)
        if digest not in hashes:
            raise PackagingError(f'Wheel not present in hashed lock: {wheel.name}')
        inspect_zip(wheel)
        with zipfile.ZipFile(wheel) as archive:
            metadata_names = [name for name in archive.namelist() if name.endswith('.dist-info/METADATA')]
            wheel_names = [name for name in archive.namelist() if name.endswith('.dist-info/WHEEL')]
            if len(metadata_names) != 1 or len(wheel_names) != 1:
                raise PackagingError(f'Invalid wheel metadata layout: {wheel.name}')
            metadata = Parser().parsestr(archive.read(metadata_names[0]).decode('utf-8'))
            tags = Parser().parsestr(archive.read(wheel_names[0]).decode('utf-8')).get_all('Tag', [])
            if not tags or any(tag.rsplit('-', 1)[-1] not in ('any', 'win_amd64') for tag in tags):
                raise PackagingError(f'Non-Windows-x64/universal wheel rejected: {wheel.name}')
            if not metadata['Name'] or not metadata['Version']:
                raise PackagingError(f'Wheel name/version missing: {wheel.name}')
            records.append({'filename':wheel.name, 'name':metadata['Name'], 'version':metadata['Version'], 'sha256':digest, 'tags':tags})
    return records


def copy_file(source: Path, dest: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise PackagingError(f'Source is not a regular file: {source.name}')
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open('xb') as stream:
        stream.write(source.read_bytes())


CONNECTION_FILES = ('service-connection.js', 'connection-security.js', 'selector-preload.js',
                    'shared-preload.js', 'connection-selector.html', 'connection-selector.css',
                    'connection-selector.js')


def verify_connection_sources(root: Path) -> None:
    # A missing selector/restricted bridge cannot become a partially working release.
    for name in CONNECTION_FILES:
        source = root/'desktop'/name
        if source.is_symlink() or not source.is_file():
            raise PackagingError(f'Missing regular desktop connection source: {name}')


def copy_clean_tree(source: Path, target: Path, suffixes: set[str]) -> None:
    for path in sorted(source.rglob('*')):
        relative = path.relative_to(source)
        if any(part in SKIP_DIRS or part.startswith('.') for part in relative.parts):
            continue
        if path.is_symlink():
            raise PackagingError(f'Source symlink rejected: {relative}')
        if path.is_file() and path.name not in PRIVATE_NAMES and path.suffix.lower() in suffixes:
            copy_file(path, target / relative)


def inventory(root: Path, paths: list[Path]) -> list[dict]:
    return [{'path':str(path.relative_to(root)).replace(os.sep,'/'), 'size':path.stat().st_size, 'sha256':sha256(path)}
            for path in sorted(paths) if path.is_file()]


def uv_install(args, target: Path, *, dry_run=False) -> str:
    command = [args.uv, 'pip', 'install', '--target', str(target), '--python-version', '3.13',
               '--python-platform', 'x86_64-pc-windows-msvc', '--only-binary', ':all:',
               '--require-hashes', '--no-index', '--find-links', str(args.wheels_dir), '--offline',
               '--no-config', '--no-python-downloads', '--no-cache', '--link-mode', 'copy',
               '--requirements', str(args.requirements_lock)]
    if dry_run:
        command.append('--dry-run')
    # Ignore ambient package indexes/configuration. No network or keyring provider
    # is needed; credentials must never become part of build logs or arguments.
    env = {key:value for key,value in os.environ.items() if not key.upper().startswith(('UV_', 'PIP_', 'PYTHON')) and key != 'VIRTUAL_ENV'}
    result = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode:
        raise PackagingError('Offline cross-target dependency resolution/install failed:\n' + result.stdout)
    return result.stdout


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)+'\n', encoding='utf-8')


def assemble(args, destination: Path, wheels: list[dict]) -> None:
    root = args.project_root
    extract_zip(args.electron_zip, destination)
    resources = destination / 'resources'; app = resources / 'app'; project = resources / 'project'
    for name in ('default_app.asar','electron.asar'):
        (resources/name).unlink(missing_ok=True)
    (destination/'electron.exe').rename(destination/'Echo.exe')
    copy_clean_tree(root/'desktop', app, {'.js','.json','.html','.css','.png','.ico','.icns','.md'})
    write_json(app/'project-root.json', {'relativeRoot':'../project'})
    copy_clean_tree(root/'server', project/'server', {'.py'})
    copy_clean_tree(root/'web', project/'web', {'.js','.mjs','.html','.css','.svg','.png','.jpg','.jpeg','.webp','.gif','.webmanifest','.woff','.woff2','.mp3','.wav'})
    copy_clean_tree(root/'shared', project/'shared', {'.json','.js','.mjs','.css','.swift','.kt','.md'})
    for name in ('SOUL.md','requirements.txt','design.md'):
        copy_file(root/name, project/name)
    copy_file(root/'scripts/run_paired_service.py', project/'scripts/run_paired_service.py')
    copy_file(root/'desktop/paired_service_bootstrap.py', project/'paired_service_bootstrap.py')
    copy_file(args.requirements_lock, project/'requirements-windows-x64.lock')
    source_paths = [*app.rglob('*'), *(path for path in project.rglob('*') if 'python' not in path.relative_to(project).parts)]
    write_json(destination/'SOURCE-MANIFEST.json', inventory(destination, source_paths))
    python = project/'python'
    extract_zip(args.python_zip, python)
    (python/'python313._pth').write_text('python313.zip\n.\nLib/site-packages\n..\n\nimport site\n', encoding='utf-8')
    install_log = uv_install(args, python/'Lib/site-packages')
    (destination/'DEPENDENCY-INSTALL.log').write_text(install_log, encoding='utf-8')
    copy_file(args.python_provenance, destination/'PYTHON-PROVENANCE.sigstore.json')
    write_json(destination/'DEPENDENCIES.json', {'target':'cp313-win_amd64','lock_sha256':sha256(args.requirements_lock),'wheels':wheels})
    # Detect a download/input changed between preflight and extraction.
    verify_hash(args.electron_zip, ELECTRON_SHA256); verify_hash(args.python_zip, PYTHON_SHA256)
    write_json(destination/'BUILD-MANIFEST.json', {
        'product':'回响 Windows x64 portable','electron_version':ELECTRON_VERSION,'python_version':PYTHON_VERSION,
        'runtimes':{'electron':{'sha256':ELECTRON_SHA256,'source':'https://github.com/electron/electron/releases/tag/v43.3.0'},
                    'python':{'sha256':PYTHON_SHA256,'source':'https://www.python.org/ftp/python/3.13.13/python-3.13.13-embed-amd64.zip',
                              'provenance':'Official TLS bundle digest compared; Sigstore signature verification not performed.'}},
        'windows_runtime_validation':'NOT_RUN','cross_target_dependencies':'offline uv hashed wheel installation only',
        'private_database_or_credentials_bundled':False,'signing':'NOT_SIGNED_BY_THIS_BUILDER',
        'source_manifest_sha256':sha256(destination/'SOURCE-MANIFEST.json')})
    (destination/'README-Windows.md').write_text(
        '# 回响 Windows x64 便携开发版\n\n解压到当前用户可写目录，双击 Echo.exe。附带 Python，无需另外安装 Python。\n\n'
        '当前包在 Mac 组装，尚未在 Windows 运行、验收或签名；这不是已完成真机验收的安装程序。\n\n'
        '首次启动会在本副本创建新的本机数据；没有携带开发者的对话、模型密钥或账号授权。'
        '模型/来源需要在本机按界面显式配置；Mac 日历、提醒事项在 Windows 不可用。\n\n'
        '服务只监听 127.0.0.1；没有开放局域网、远程账户或云同步。CLI 是否安装及已授权需单独验收，'
        'Rokid/脑电真机、系统通知和签名仍未完成。\n\n'
        '源码校验见 SOURCE-MANIFEST.json，运行时与依赖来源见 BUILD-MANIFEST.json、DEPENDENCIES.json。'
        'Electron 的 LICENSE / LICENSES.chromium.html 和 Python 的 LICENSE.txt 随包保留。\n', encoding='utf-8')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project-root','electron-zip','python-zip','python-provenance','requirements-lock','wheels-dir','output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--zip-output', type=Path)
    parser.add_argument('--uv', default=shutil.which('uv') or 'uv')
    parser.add_argument('--preflight', action='store_true', help='Validate inputs and offline resolution; publish no output.')
    args = parser.parse_args(argv)
    try:
        for name in ('project_root','electron_zip','python_zip','python_provenance','requirements_lock','wheels_dir','output'):
            setattr(args,name,getattr(args,name).absolute())
        if args.output.is_symlink():
            raise PackagingError('Output cannot be a symlink, including a broken one.')
        args.project_root = args.project_root.resolve(strict=True)
        args.output = args.output.resolve()
        if args.output.exists() or not args.output.parent.is_dir() or args.output.is_relative_to(args.project_root):
            raise PackagingError('Output must be a NEW folder outside project-root with an existing parent. Never overwrite.')
        if args.zip_output:
            args.zip_output = args.zip_output.absolute()
            if args.zip_output.is_symlink():
                raise PackagingError('ZIP output cannot be a symlink.')
            args.zip_output = args.zip_output.resolve()
            if args.zip_output.exists() or args.zip_output.suffix.lower() != '.zip' or not args.zip_output.parent.is_dir() or args.zip_output.is_relative_to(args.output) or args.zip_output.is_relative_to(args.project_root):
                raise PackagingError('ZIP output must be a NEW .zip outside project-root and portable output.')
        package = json.loads((args.project_root/'desktop/package.json').read_text())
        if package.get('devDependencies',{}).get('electron') != ELECTRON_VERSION:
            raise PackagingError('Desktop source must pin the same Electron version as the runtime.')
        for name in ('server/main.py','web/index.html','SOUL.md','requirements.txt','design.md','desktop/main.js','desktop/package.json'):
            if not (args.project_root/name).is_file():
                raise PackagingError(f'Missing required project source: {name}')
        verify_connection_sources(args.project_root)
        verify_hash(args.electron_zip,ELECTRON_SHA256); verify_hash(args.python_zip,PYTHON_SHA256)
        inspect_zip(args.electron_zip,('electron.exe','LICENSE','LICENSES.chromium.html'))
        inspect_zip(args.python_zip,('python.exe','python313.dll','python313.zip','python313._pth','LICENSE.txt'))
        verify_python_provenance(args.python_provenance)
        wheels = verify_wheelhouse(args.wheels_dir,args.requirements_lock)
        with tempfile.TemporaryDirectory(prefix='.echo-windows-build-',dir=args.output.parent) as scratch:
            scratch = Path(scratch)
            if args.preflight:
                uv_install(args,scratch/'site-packages',dry_run=True)
                print(f'PREFLIGHT_OK: verified two exact runtime hashes and {len(wheels)} locked wheels. Windows execution NOT_RUN. No output published.')
                return 0
            staged = scratch/'portable'
            staged.mkdir()
            assemble(args,staged,wheels)
            # Reserve atomically. A concurrently-created output is never replaced.
            args.output.mkdir(exist_ok=False)
            for child in staged.iterdir():
                child.rename(args.output/child.name)
        if args.zip_output:
            with zipfile.ZipFile(args.zip_output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
                for path in sorted(args.output.rglob('*')):
                    if path.is_file():
                        archive.write(path,arcname=str(Path(args.output.name)/path.relative_to(args.output)))
        print(f'BUILD_OK: {args.output.name}; Windows execution NOT_RUN; no private DB/credentials bundled.')
        return 0
    except (PackagingError, OSError, zipfile.BadZipFile, ValueError, subprocess.SubprocessError) as error:
        parser.exit(2,f'BUILD_NOT_COMPLETED: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
