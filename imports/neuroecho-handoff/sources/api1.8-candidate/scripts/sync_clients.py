#!/usr/bin/env python3
"""Generate shared resources and adopt them in every PRESENT client, without SDKs.

Only generated files are updated. Native layouts, handwritten copy and behavioral
flows are not automatically ported; this is not platform build/visual acceptance.
"""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit
import argparse
import re
import subprocess
import sys

from generate_shared import outputs

ROOT = Path(__file__).resolve().parents[1]
NATIVE = {
    'ios': ('native/ios', 'sync_shared.py', 'App/SharedDesign.generated.swift', 'EchoSharedReference.swift'),
    'android': ('native/android', 'scripts/sync_shared.py', 'app/src/main/java/cn/xinji/echo/shared/EchoSharedReference.kt', 'EchoSharedReference.kt'),
}
WEB = {'generated-design.css':'design.css', 'generated-shared.js':'runtime.js'}


def surfaces(root=ROOT):
    return [name for name in ('web', *NATIVE) if (root/('web' if name == 'web' else NATIVE[name][0])).is_dir()]


def runtime_copy_issues(root=ROOT):
    """Exact bytes, not a copy timestamp or a marker string."""
    issues = []
    for name in surfaces(root):
        if name == 'web':
            pairs = [(root/'web'/target, root/'shared/generated'/source) for target,source in WEB.items()]
        else:
            directory, _, target, source = NATIVE[name]
            pairs = [(root/directory/target, root/'shared/generated'/source)]
        for target,source in pairs:
            if not source.is_file() or not target.is_file() or target.read_bytes() != source.read_bytes():
                issues.append(f'{target.relative_to(root)} differs from shared/generated; run scripts/sync_clients.py')
    return issues


def code_without_comments(text):
    # Preserve quoted strings, so URL literals cannot accidentally swallow the
    # rest of a source line while stripping comments used to fake adoption.
    pattern = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/'
    return re.sub(pattern, lambda match: '' if match[0].startswith(('//','/*')) else match[0], text)


class Imports(HTMLParser):
    def __init__(self):
        super().__init__(); self.scripts=[]; self.styles=[]; self.copy_keys=set()

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if 'data-copy-key' in attrs: self.copy_keys.add(attrs['data-copy-key'])
        if tag == 'link' and 'stylesheet' in attrs.get('rel','').split():
            parts=urlsplit(attrs.get('href',''))
            if not parts.scheme and not parts.netloc and '..' not in parts.path.split('/'): self.styles.append(parts.path)
        if tag == 'script' and attrs.get('src') and attrs.get('type','') in ('','text/javascript','application/javascript','module'):
            parts=urlsplit(attrs['src'])
            if not parts.scheme and not parts.netloc and '..' not in parts.path.split('/'):
                self.scripts.append((parts.path, 'async' in attrs or 'defer' in attrs or attrs.get('type') == 'module'))


def runtime_adoption_issues(root=ROOT):
    """Static integration gate, not proof that a native app has run."""
    issues=[]
    def require(condition, message):
        if not condition: issues.append(message)
    def read(path):
        target=root/path
        return code_without_comments(target.read_text()) if target.is_file() else ''
    present=surfaces(root)
    require(bool(present), 'No runtime client is present; runtime adoption cannot be validated.')
    if 'web' in present:
        for name,consumer in (('index.html','app.js'),('m.html','m.js')):
            path=root/'web'/name
            require(path.is_file(), f'web/{name} is missing')
            if not path.is_file(): continue
            imports=Imports(); imports.feed(path.read_text())
            scripts=[Path(path).name for path,_ in imports.scripts]
            styles=[Path(path).name for path in imports.styles]
            require('generated-design.css' in styles, f'web/{name} must import generated-design.css as a real stylesheet')
            require('generated-shared.js' in scripts, f'web/{name} must import generated-shared.js as an executable script')
            for consumer_name in ('design-system.js',consumer):
                require(consumer_name in scripts, f'web/{name} lacks runtime consumer {consumer_name}')
                if 'generated-shared.js' in scripts and consumer_name in scripts:
                    require(scripts.index('generated-shared.js') < scripts.index(consumer_name), f'web/{name} must load generated-shared.js before {consumer_name}')
            for src,async_script in imports.scripts:
                if Path(src).name == 'generated-shared.js': require(not async_script, f'web/{name} shared runtime must load synchronously before its consumers')
            require({'nav.today','nav.chat','nav.memory'} <= imports.copy_keys, f'web/{name} must bind the three shared navigation copy keys')
        design=read('web/design-system.js')
        require(bool(re.search(r'(?:window|globalThis)\.EchoShared\?*\.defaults', design)), 'Web preferences must consume generated EchoShared.defaults')
        require('EchoShared?.copy' in design and bool(re.search(r'\bapplyCopy\s*\(\s*\)\s*;',design)), 'Web must apply generated copy to actual data-copy-key elements')
    if 'ios' in present:
        design=read('native/ios/App/Design.swift'); settings=read('native/ios/App/SettingsView.swift'); views=read('native/ios/App/RootViews.swift')
        require('EchoSharedReference.color_ink' in design and 'EchoSharedReference.color_bg_start' in design, 'iOS design must use generated color constants')
        for key,value in (('reduceMotion','defaultReduceMotion'),('reduceTransparency','defaultReduceTransparency'),('lightStrength','defaultLightIntensity')):
            bindings=re.findall(r'@AppStorage\("echo\.native\.'+key+r'"\)([^\n]*)',design+'\n'+settings)
            require(bool(bindings) and all(re.search(r'=\s*EchoSharedReference\.'+value+r'\b',binding) for binding in bindings), f'Every iOS stored {key} binding must use {value}')
        for value in ('copy_nav_today','copy_nav_chat','copy_nav_memory'):
            require('EchoSharedReference.'+value in views, 'iOS navigation must consume '+value)
        project=read('native/ios/Echo.xcodeproj/project.pbxproj')
        # A copied Swift file must also belong to the app's actual build phase.
        reference=re.search(r'(\w+)\s*=\s*\{\s*isa\s*=\s*PBXFileReference;[^\n]*path\s*=\s*"?SharedDesign\.generated\.swift"?',project)
        build=re.search(r'(\w+)\s*=\s*\{\s*isa\s*=\s*PBXBuildFile;\s*fileRef\s*=\s*'+(reference[1] if reference else 'MISSING')+r'\b',project)
        phases=re.findall(r'isa\s*=\s*PBXSourcesBuildPhase;[^}]*files\s*=\s*\(([^)]*)\)',project)
        require(bool(build and any(build[1] in phase for phase in phases)), 'iOS generated Swift resource is not registered in PBXSourcesBuildPhase')
    if 'android' in present:
        main=read('native/android/app/src/main/java/cn/xinji/echo/MainActivity.kt')
        viewmodel=read('native/android/app/src/main/java/cn/xinji/echo/EchoViewModel.kt')
        require('import cn.xinji.echo.shared.EchoSharedReference as Shared' in main and 'Shared.COLOR_INK' in main and 'Shared.COLOR_BG_START' in main, 'Android theme must import and consume generated colors')
        for value in ('COPY_NAV_TODAY','COPY_NAV_CHAT','COPY_NAV_MEMORY'):
            require('Shared.'+value in main, 'Android navigation must consume '+value)
        for getter,key,value in (('getBoolean','reduce_motion','DEFAULT_REDUCE_MOTION'),('getBoolean','reduce_transparency','DEFAULT_REDUCE_TRANSPARENCY'),('getFloat','light_intensity','DEFAULT_LIGHT_INTENSITY')):
            require(bool(re.search(getter+r'\(\s*"'+key+r'"\s*,\s*Shared\.'+value+r'\b',viewmodel)), 'Android stored preference must use '+value)
        product=read('native/android/app/src/main/java/cn/xinji/echo/ProductRules.kt')
        if product:
            for value in ('DEFAULT_REDUCE_MOTION','DEFAULT_REDUCE_TRANSPARENCY','DEFAULT_LIGHT_INTENSITY'):
                require('Shared.'+value in product, 'Android comfort defaults must consume '+value)
    # These controls ship together in R9; require their actual source references
    # on every present surface, rather than accepting generated definitions alone.
    keys = ('companion.boundary.title', 'companion.boundary.today', 'companion.boundary.effect', 'followup.contact.consent', 'mood.title', 'mood.save', 'mood.context', 'mood.to_chat', 'mood.recovery.check', 'mood.recovery.retry', 'mood.recovery.cancel', 'voice.read', 'voice.stop', 'voice.disclosure', 'connection.devices.title', 'connection.devices.scope', 'connection.sync.check', 'connection.sync.pending', 'connection.sync.updated', 'connection.sync.offline', 'connection.sync.unsupported')
    if 'web' in present:
        consumers=set()
        for name in ('index.html', 'm.html'):
            path=root/'web'/name
            if path.is_file():
                imports=Imports(); imports.feed(path.read_text())
                consumers.update(Path(src).name for src,_ in imports.scripts)
        code='\n'.join(read('web/'+name) for name in consumers if name not in ('generated-shared.js',))
        for key in keys:
            require(key in code, 'Web companion controls must bind shared '+key)
        require('EchoShared' in code, 'Web companion controls must consume the generated shared copy')
    if 'ios' in present:
        code='\n'.join(read(str(path.relative_to(root))) for path in (root/'native/ios/App').glob('*.swift') if path.name != 'SharedDesign.generated.swift')
        for key in keys:
            require('EchoSharedReference.copy_'+key.replace('.', '_') in code, 'iOS companion controls must bind shared '+key)
    if 'android' in present:
        code='\n'.join(read(str(path.relative_to(root))) for path in (root/'native/android/app/src/main/java/cn/xinji/echo').glob('*.kt'))
        for key in keys:
            require('Shared.COPY_'+key.replace('.', '_').upper() in code, 'Android companion controls must bind shared '+key)
    return issues


def sync_clients(*, check=False, root=ROOT):
    command=[sys.executable,str(root/'scripts/generate_shared.py')]
    if check: command.append('--check')
    subprocess.run(command,check=True)
    if (root/'web').is_dir():
        for target,source in WEB.items():
            destination=root/'web'/target
            if not check: destination.write_bytes((root/'shared/generated'/source).read_bytes())
    for name,(directory,script,_,_) in NATIVE.items():
        project=root/directory
        if not project.is_dir():
            print(f'SKIP: {name} source absent in this package.'); continue
        helper=project/script
        if not helper.is_file(): raise ValueError(f'{name} exists but its sync helper is missing: {helper.relative_to(root)}')
        command=[sys.executable,str(helper)]
        if check: command.append('--check')
        subprocess.run(command,check=True)
    issues=runtime_copy_issues(root)
    if issues: raise ValueError('RUNTIME_COPY_DRIFT: '+'; '.join(issues))
    present=surfaces(root)
    if present: print('CLIENT_RESOURCES_MATCH: '+', '.join(present)+' (generated bytes only; layouts/handwritten copy/platform builds remain separate).')
    else: print('NO_CLIENT_SOURCES: generated shared files match; runtime adoption was not validated.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true',help='Check generated source and every present platform snapshot without modifying files.')
    args=parser.parse_args()
    try: sync_clients(check=args.check)
    except (OSError,ValueError,subprocess.CalledProcessError) as error: parser.exit(1,str(error)+'\n')


if __name__ == '__main__': main()
