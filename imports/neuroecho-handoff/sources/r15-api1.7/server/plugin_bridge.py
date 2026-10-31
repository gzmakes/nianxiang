"""表情桥：服务端素材包 + 本机 DSH 插件（BYO）。

- 服务端包：随服务发布的素材，所有人共用（server/stickers/<pack>/memes/<tag>/<file>）；
- 本机插件：只读用户已安装的 dsh-meme，不分发插件素材；
- dsh-meme 图库的 manifest 可能标 personal，仅本机使用；
- dsh-pet 只做状态识别与启动说明，不复制动画。
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote
from pathlib import Path

PROFILES = Path.home() / ".dsh" / "profiles"
SERVER_STICKERS = Path(__file__).resolve().parent / "stickers"
EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
BUILTIN = {"happy": "开心", "comfort": "安慰", "curious": "疑惑", "cheer": "鼓励"}
_MARKER = re.compile(r"\[表情[:：]\s*([^\]\r\n]{1,240}?)\s*\]")


def _builtin_items():
    root = Path(__file__).resolve().parent.parent / "web" / "stickers"
    return [{"id": f"builtin/{key}.svg", "label": label, "tags": [key], "pack": "builtin",
             "url": f"/static/stickers/{key}.svg"}
            for key, label in BUILTIN.items() if (root / f"{key}.svg").is_file()]


def _pack_items(root: Path, *, subdir: str = "", label_by_pack: bool = False):
    """Items + pack descriptors for `root/<subdir>/<pack>/memes/<tag>/<file>` trees."""
    items, packs = [], []
    if not root.is_dir():
        return items, packs
    pattern = f"{subdir}/*/manifest.json" if subdir else "*/manifest.json"
    for manifest in sorted(root.glob(pattern)):
        pack = manifest.parent.name
        try:
            meta = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        packs.append({"id": pack, "name": meta.get("name") or pack,
                      "license": meta.get("license") or "unknown"})
        for f in sorted(manifest.parent.glob("memes/*/*")):
            if not f.is_file() or f.suffix.lower() not in EXTS:
                continue
            tag = f.parent.name
            if any(c in f"{pack}{tag}{f.name}" for c in "[]\\\r\n"):
                continue
            items.append({
                "id": f"{pack}/{tag}/{f.name}",
                "label": meta.get("name") if label_by_pack else f.stem,
                "tags": [tag, pack],
                "pack": pack,
                "url": "/plugin-memes/" + "/".join(quote(x, safe="") for x in (pack, tag, f.name)),
            })
    return items, packs


def _server_items():
    return _pack_items(SERVER_STICKERS, label_by_pack=True)


def _local_items():
    root = _find("dsh-meme")
    return _pack_items(root, subdir="memes") if root else ([], [])


def _all_items():
    """Builtin first, then server packs, then this machine's plugin packs."""
    builtin, (server, _), (local, _) = _builtin_items(), _server_items(), _local_items()
    seen, out = set(), []
    for item in [*builtin, *server, *local]:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        out.append(item)
    return out


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
    builtin = _builtin_items()
    server_items, server_packs = _server_items()
    items = [*builtin, *server_items]
    packs = ([{"id": "builtin", "name": "回响原创表情", "license": "project"}] if builtin else []) + server_packs
    if not root:
        return {"installed": bool(items), "version": "", "items": _all_items()[:120],
                "packs": packs, "local_plugin": False}
    local_items, local_packs = _local_items()
    packs += local_packs
    return {"installed": True, "version": _version(root), "root": str(root),
            "items": _all_items()[:120], "packs": packs}


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
    """Resolve a sticker file: shipped packs first, then this machine's plugin."""
    if any(x in (pack, tag, name) for x in ("..", "/", "\\")):
        return None
    try:
        root = SERVER_STICKERS.resolve()
        target = (root / pack / "memes" / tag / name).resolve()
        target.relative_to(root)
        if target.is_file() and target.suffix.lower() in EXTS:
            return target
    except (ValueError, OSError):
        pass
    root = _find("dsh-meme")
    if not root:
        return None
    base = (root / "memes").resolve()
    target = (base / pack / "memes" / tag / name).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target if target.is_file() and target.suffix.lower() in EXTS else None


def meme_prompt_catalog() -> list[dict[str, str]]:
    """Explicit sticker IDs plus tag aliases for model-generated markers."""
    catalog, seen = [], set()
    for item in _all_items():
        item_id = str(item.get("id") or "").strip()
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        tags = item.get("tags") or []
        catalog.append({"id": item_id, "meaning": str(item.get("label") or (tags[0] if tags else item_id)),
                        "tag": str(tags[0]) if tags else ""})
    return catalog


def sanitize_meme_markers(text: str) -> str:
    choices = {}
    for item in _all_items():
        item_id = item["id"]
        choices[item_id] = item_id
        for tag in item.get("tags") or []:
            choices.setdefault(tag, item_id)

    def resolve(match):
        selected = choices.get(match.group(1).strip())
        return f"[表情: {selected}]" if selected else ""

    return _MARKER.sub(resolve, str(text or ""))
