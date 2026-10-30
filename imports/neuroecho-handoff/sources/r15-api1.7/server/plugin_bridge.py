"""本机 DSH 插件桥（BYO）：读取用户已安装的 dsh-meme / dsh-pet。

- 不分发插件素材，只读本机已安装目录；
- dsh-meme 图库的 manifest 可能标 personal，仅本机使用；
- dsh-pet 只做状态识别与启动说明，不复制动画。
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote
from pathlib import Path

PROFILES = Path.home() / ".dsh" / "profiles"
EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
BUILTIN = {"happy": "开心", "comfort": "安慰", "curious": "疑惑", "cheer": "鼓励"}
_MARKER = re.compile(r"\[表情[:：]\s*([^\]\r\n]{1,240}?)\s*\]")


def _builtin_items():
    root = Path(__file__).resolve().parent.parent / "web" / "stickers"
    return [{"id": f"builtin/{key}.svg", "label": label, "tags": [key], "pack": "builtin",
             "url": f"/static/stickers/{key}.svg"}
            for key, label in BUILTIN.items() if (root / f"{key}.svg").is_file()]



def _find(pkg: str) -> Path | None:
    if not PROFILES.exists():
        return None
    found = sorted(PROFILES.glob(f"*/node_modules/{pkg}/package.json"))
    return found[0].parent if found else None


def _version(root: Path | None) -> str:
    if not root:
        return ""
    try:
        return str(json.loads((root / "package.json").read_text()).get("version") or "")
    except Exception:
        return ""


def memes() -> dict:
    root = _find("dsh-meme")
    items = _builtin_items()
    packs = [{"id": "builtin", "name": "回响原创表情", "license": "project"}] if items else []
    if not root:
        return {"installed": bool(items), "version": "", "items": items, "packs": packs, "local_plugin": False}
    for manifest in sorted(root.glob("memes/*/manifest.json")):
        try:
            meta = json.loads(manifest.read_text())
        except Exception:
            meta = {}
        pack = manifest.parent.name
        packs.append({"id": pack, "name": meta.get("name") or pack,
                      "license": meta.get("license") or "unknown"})
        for f in sorted(manifest.parent.glob("memes/*/*")):
            if not f.is_file() or f.suffix.lower() not in EXTS:
                continue
            tag = f.parent.name
            if any(c in f"{pack}{tag}{f.name}" for c in "[]\\\r\n") or meme_file(pack, tag, f.name) is None:
                continue
            items.append({
                "id": f"{pack}/{tag}/{f.name}",
                "label": f.stem,
                "tags": [tag, pack],
                "pack": pack,
                "url": "/plugin-memes/" + "/".join(quote(x, safe="") for x in (pack, tag, f.name)),
            })
    return {"installed": True, "version": _version(root), "root": str(root),
            "items": items[:120], "packs": packs}


def pet() -> dict:
    root = _find("dsh-pet")
    if not root:
        return {"installed": False, "version": "", "hint": "DSH 插件市场安装 dsh-pet"}
    return {
        "installed": True,
        "version": _version(root),
        "license": "素材禁止商用（见插件 README）",
        "hint": "终端执行 dsh-pet-standalone，或从 DSH 插件页启动",
    }


def meme_file(pack: str, tag: str, name: str) -> Path | None:
    root = _find("dsh-meme")
    if not root or any(x in (pack, tag, name) for x in ("..", "/", "\\")):
        return None
    base = (root / "memes").resolve()
    target = (base / pack / "memes" / tag / name).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target if target.is_file() and target.suffix.lower() in EXTS else None


def meme_prompt_catalog() -> list[dict[str, str]]:
    available = {item["tags"][0] for item in _builtin_items()}
    return [{"id": key, "meaning": label} for key, label in BUILTIN.items() if key in available]


def sanitize_meme_markers(text: str) -> str:
    choices = {item["tags"][0]: item["id"] for item in _builtin_items()}
    def resolve(match):
        selected = choices.get(match.group(1).strip())
        return f"[表情: {selected}]" if selected else ""
    return _MARKER.sub(resolve, str(text or ""))
