#!/usr/bin/env python3
"""Create frozen source handoffs only. Never reads credentials or private databases."""
from pathlib import Path
import argparse, hashlib, json, re, zipfile
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--replace-generated',action='store_true');a=p.parse_args()
out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=True)
blocked={'.venv','.syntax-venv','node_modules','__pycache__','.pytest_cache','.build','.gradle','.gradle-user-home','build','.git','work','DerivedData','xcuserdata','dist'}
def allowed(path):
    rel=path.relative_to(ROOT)
    if path.is_symlink() or not path.is_file() or set(rel.parts)&blocked:return False
    if path.name.startswith(('data.db','.DS_Store','local.properties')) or path.name in {'model-settings.json','auth.json'}:return False
    if path.name=='.env' or path.name.startswith('.env.'):return False
    if path.suffix.lower() in {'.pyc','.db','.sqlite','.sqlite3','.server.lock','.key','.pem','.p12','.pfx','.crt','.cer','.der'}:return False
    return True

release=json.loads((ROOT/'shared/release.json').read_text(encoding='utf-8'))
source=[path for path in ROOT.rglob('*') if allowed(path)]
for path in source:
    if path.suffix in {'.md','.py','.js','.json','.txt','.html','.swift','.kt','.kts','.sh','.mjs','.css'}:
        if re.search(rb'sk-[A-Za-z0-9]{24,}|-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----',path.read_bytes()):raise SystemExit('Potential secret; inspect filename privately: '+str(path.relative_to(ROOT)))

def platform_readme(kind):
    native='iOS' if kind=='ios' else 'Android'
    entry='native/ios/Echo.xcodeproj' if kind=='ios' else 'native/android/'
    return f'''# 回响 {native} 开发交接\n\n版本：{release['release_id']}。先读 docs/技术交接/{native}接手.md，用{('完整Xcode打开' if kind=='ios' else 'Android Studio打开')}{entry}。\n\n这是可继续开发的原生源码基线，没有{('IPA/iOS SDK构建' if kind=='ios' else 'APK/Android SDK构建')}或真机验收保证。已知功能差异与第一轮任务在交接说明中；不能只做外观打磨后直接发布。\n\n包含：本端原生源码/检查、design.md、shared参考与API声明、无数据的server和web、后端依赖与启动入口。没有另一端源码、Electron运行时、账号、模型密钥、私人数据库、SDK或构建缓存。跨端完整回归请用完整源码包或同一仓库。\n\n本机后端可双击启动念响.command，或执行：\n\n```sh\npython3 -m venv .venv\n.venv/bin/python -m pip install -r requirements.txt\n.venv/bin/python -m uvicorn server.main:app --host 127.0.0.1 --port 18787\n```\n\n需自行配置开发模型；不附带任何个人账号。iOS模拟器与Android adb reverse见本端README。真手机不能直接使用Mac回环地址。R13已实现逐设备令牌与受限TLS入口源码，R14增加前台只读更新发现和安全快照替换；R15补原生弹层反馈与本机文字只读取回，详见本端ACCEPTANCE-ROUND15.md。默认不启动远程服务；接入范围、证书与未验收项见docs/技术交接/设备连接API-R13.md及跨端更新API-R14.md。没有真实手机配对或云同步验收，不把本机个人服务直接开放公网。\n\n首批共享资源已接入各端运行源码，可用scripts/sync_clients.py生成并检查；剩余手写文案/布局和平台运行仍分别验收。详细协作与架构见 docs/技术交接/多端同步与架构方案.md。SHA256逐文件清单见 SOURCE-MANIFEST.json；它验证内容一致性，不是签名或发行认证。\n'''

def package_specs(root_name):
    # Use the frozen source directory's label for every archive. A later round
    # must not silently retain the previous round's root folder or ZIP name.
    return [('full',f'{root_name}-完整源码交接包.zip',root_name),
            ('ios',f'{root_name}-iOS源码交接包.zip','回响-iOS-开发交接'),
            ('android',f'{root_name}-Android源码交接包.zip','回响-Android-开发交接')]

specs=package_specs(ROOT.name)
for kind,name,folder in specs:
    target=out/name
    if target.exists() and not a.replace_generated:raise SystemExit('Refusing overwrite: '+str(target))
    payload={};origins={}
    for path in source:
        rel=path.relative_to(ROOT)
        if kind!='full':
            if rel.parts[0]=='desktop':continue
            if rel.parts[0]=='native' and rel.parts[1]!=kind:continue
            if rel.parts[0]=='tests' and rel.name!='test_shared_baseline.py':continue
        payload[rel.as_posix()]=path.read_bytes();origins[rel.as_posix()]=path
    if kind!='full':payload['README.md']=platform_readme(kind).encode()
    manifest={'release_id':release['release_id'],'package':kind,'platform_build_verified':False if kind!='full' else {'ios':False,'android':False},'files':{key:hashlib.sha256(value).hexdigest() for key,value in sorted(payload.items())}}
    payload['SOURCE-MANIFEST.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        for rel,data in sorted(payload.items()):
            info=zipfile.ZipInfo(folder+'/'+rel)
            info.compress_type=zipfile.ZIP_DEFLATED;info.create_system=3
            info.external_attr=((origins[rel].stat().st_mode if rel in origins else 0o100644)&0xFFFF)<<16
            archive.writestr(info,data)
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:raise SystemExit('Corrupt ZIP')
        for rel,digest in manifest['files'].items():
            assert hashlib.sha256(archive.read(folder+'/'+rel)).hexdigest()==digest,rel
        required=['server/main.py','server/paired_access.py','server/paired_app.py','server/conversation_changes.py','scripts/run_paired_service.py','web/index.html','web/paired-devices.js','web/paired-devices.css','requirements.txt','requirements-dev.txt','design.md','shared/api/openapi.json','scripts/check_consistency.py']
        if kind in ('ios','full'):required+=['native/ios/Echo.xcodeproj/project.pbxproj','native/ios/Echo.xcodeproj/xcshareddata/xcschemes/Echo.xcscheme']
        if kind in ('android','full'):required+=['native/android/gradlew','native/android/gradle/wrapper/gradle-wrapper.jar','native/android/app/src/main/AndroidManifest.xml']
        assert all(folder+'/'+item in archive.namelist() for item in required)
    print(json.dumps({'file':name,'entries':len(payload),'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()},ensure_ascii=False))
