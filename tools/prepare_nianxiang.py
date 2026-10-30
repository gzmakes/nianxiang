"""Prepare an isolated, rebranded source import; never edit the originals."""
from pathlib import Path
import json, hashlib, re, shutil

import argparse
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('workspace', type=Path, help='Folder containing the original handoff and standalone input files')
args = parser.parse_args()
ROOT = args.workspace.resolve()
SOURCE = ROOT / '心迹回响-队友交接总包-R15-20261030'
OUT = ROOT / 'nianxiang-import'
BASE = OUT / 'imports' / 'neuroecho-handoff'
TEXT = {'.py','.js','.mjs','.cjs','.ts','.tsx','.jsx','.json','.md','.txt','.html','.css','.svg','.xml','.swift','.kt','.kts','.toml','.ini','.yaml','.yml','.sh','.command','.cmd','.bat','.plist','.pbxproj','.xcworkspacedata','.xcscheme','.entitlements','.xcconfig','.properties','.gradle','.cs','.csproj','.ps1'}
SKIP = {'.git','__pycache__','node_modules','.venv','venv','__MACOSX','.pytest_cache','recordings'}
ASSETS = {'.png','.icns','.ico','.jpg','.jpeg','.woff','.woff2'}

def rename(s):
    return s.replace('心迹回响', '念响')

def prepare():
    if OUT.exists():
        raise SystemExit('Output already exists; refusing to overwrite')
    records, excluded = [], []
    mappings = [
        ('01_源码候选/R15_桌面与多端_API1.7','sources/r15-api1.7'),
        ('01_源码候选/并行整合候选_API1.8_待处理阻塞','sources/api1.8-candidate'),
        ('03_产品与设计','docs/product-design'),
        ('05_脑机与设备','devices'),
        ('06_验收与交接记录','docs/handoff'),
    ]
    for folder, target in mappings:
        for p in sorted((SOURCE / folder).rglob('*')):
            if not p.is_file():
                continue
            rel = p.relative_to(SOURCE / folder)
            is_text = p.suffix.lower() in TEXT or p.name in {'.gitignore','LICENSE','NOTICE'}
            asset = target.startswith('sources/') and 'assets' in rel.parts and p.suffix.lower() in ASSETS
            if p.is_symlink() or SKIP.intersection(rel.parts) or p.name.startswith('.env') or not (is_text or asset):
                excluded.append({'path': rename(str(p.relative_to(SOURCE))), 'reason':'binary, private runtime, cache, or unselected asset'})
                continue
            dest = BASE / target / rename(rel.as_posix())
            raw = p.read_bytes()
            if is_text:
                try:
                    raw = rename(raw.decode('utf-8-sig')).encode('utf-8')
                except UnicodeDecodeError:
                    excluded.append({'path':rename(str(p.relative_to(SOURCE))), 'reason':'non UTF-8; manual review required'})
                    continue
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(raw)
            records.append({'path':dest.relative_to(OUT).as_posix(),'sha256':hashlib.sha256(raw).hexdigest()})
    for p, dest in [(ROOT/'API接口说明.txt',BASE/'devices/MindLink-API.txt'),(ROOT/'design (1).md',BASE/'docs/product-design/design.md'),(SOURCE/'00_先看这里_交接文档.md',BASE/'docs/handoff/原交接说明.md'),(SOURCE/'01_源码候选/API1.8_原交接说明_含重要阻塞.md',BASE/'docs/handoff/API1.8阻塞说明.md')]:
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(rename(p.read_text(encoding='utf-8-sig')),encoding='utf-8')
    (BASE/'import-manifest.json').write_text(json.dumps({'files':records,'excluded':excluded},ensure_ascii=False,indent=2),encoding='utf-8')
    (BASE/'README.md').write_text('''# 念响 NeuroEcho · 分类导入

当前方向：五人团队参加模型训练赛道，基于 MiniMind 等开源小模型训练个性化交互策略模块，接入情感 Personal Agent。此导入是既有应用与研究材料，不代表已有训练代码、训练权重或训练效果。

| 目录 | 内容 |
|---|---|
| sources/r15-api1.7 | R15 应用源码，含 Web/H5、桌面、原生客户端、服务端与测试 |
| sources/api1.8-candidate | 未合并的并行候选；先处理删除与迟到请求并发问题 |
| docs/product-design | 产品、设计和研究；历史赛道与排期表述仅作历史参考 |
| docs/handoff | 交接与验收文档，历史测试数并非本次复验 |
| devices | MindLink 接口、SDK 与设备研究；硬件仍待真机验收 |

## 导入边界

已替换导入文本及路径中的旧中文全称为“念响”。保留 XINJI_* 等配置键和 API 标识，避免破坏兼容；不修改既有根目录文件或设计 ZIP。两份源码没有合并。历史图片、录屏、个人素材、第三方逆向整包、平台安装包、模型二进制和缓存没有上传。原始文件留在本地，图像内文字未编辑。

部分历史文档链接指向未上传的截图或原目录；历史哈希/签名只能描述原包，不能验证更名后的内容。import-manifest.json 为本次复制文件的新 SHA256 清单（新增导入说明及工具不在清单中）。

## 开发与验证

先进入 sources/r15-api1.7，按其 README 安装 Python 依赖；Node 测试可用 `node --test tests/*.js`。模型需要自行配置，包内不应包含凭据。新策略训练模块通过后续 Issue/PR 约定接口，本 PR 不改共享接口，不声称完成 MiniMind 训练。

根目录 tools/verify_import.py 可核验导入完整性与名称残留。禁止将本目录历史测试记录当作当前平台已通过验收。
''',encoding='utf-8')
    print(json.dumps({'copied':len(records),'excluded':len(excluded),'output':str(OUT)},ensure_ascii=False))

if __name__ == '__main__':
    prepare()
