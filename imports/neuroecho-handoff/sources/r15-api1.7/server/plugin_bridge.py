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
BUILTIN_MEANINGS = {
    "happy": "轻松开心地回应",
    "comfort": "温柔安慰和陪伴",
    "curious": "对事情感到好奇，想继续了解",
    "cheer": "为对方加油和鼓劲",
}
# The shipped whale pack is a personal-licensed asset.  These descriptions
# are intentionally conservative and describe the visible gesture rather
# than making claims about the original artwork or licensing.
PACK_MEANINGS = {
    "angry/shengqi.jpg": ("生气", "皱眉鼓起脸，表达不满或抗议", ["angry", "frustrated"]),
    "baka/xianqi.jpg": ("嫌弃", "有点嫌弃又嘴硬地看着对方", ["teasing", "dismissive"]),
    "color/huachi.jpg": ("花痴", "开心到冒爱心，表达喜欢或心动", ["love", "excited"]),
    "confused/jiazai.jpg": ("加载中", "头顶转圈，表示正在思考或加载", ["thinking", "waiting"]),
    "confused/wenhao.jpg": ("疑问", "头顶问号，表示疑惑和想确认", ["curious", "question"]),
    "cpu/jiaban.jpg": ("加班", "抱着电脑忙碌，表示正在处理工作", ["work", "busy"]),
    "daily/ganfan.jpg": ("干饭", "开心吃饭，表达满足和日常分享", ["daily", "happy"]),
    "fool/buyao.jpg": ("不要", "摆手拒绝或表示不想要", ["refuse", "playful"]),
    "givemoney/yaoqian.jpg": ("要钱", "伸手索要，适合玩笑式催付款", ["teasing", "request"]),
    "happy/deyi.jpg": ("得意", "得意地笑，表达小小的骄傲", ["proud", "teasing"]),
    "happy/ok.jpg": ("好的", "竖起拇指表示认可和确认", ["approve", "ok"]),
    "happy/piaole.jpg": ("飘了", "得意到飘起来，适合轻松玩笑", ["proud", "teasing"]),
    "like/bixin.jpg": ("比心", "双手比心，表达喜欢和支持", ["love", "support"]),
    "meow/maozhua.jpg": ("猫爪", "伸出猫爪撒娇或打招呼", ["cute", "greeting"]),
    "morning/zaoshanghao.jpg": ("早上好", "挥手打招呼，适合早安问候", ["greeting", "morning"]),
    "sad/qiurao.jpg": ("求饶", "双手合十求饶，表示歉意或请求原谅", ["sorry", "pleading"]),
    "sad/yun.jpg": ("晕", "眼神发晕，表示疲惫或被信息冲击", ["tired", "surprised"]),
    "see/zhenjing.jpg": ("震惊", "睁大眼睛，表达惊讶", ["surprised", "shocked"]),
    "shy/haixiu.jpg": ("害羞", "捂脸害羞，表达不好意思", ["shy", "cute"]),
    "shy/toukan.jpg": ("偷看", "躲在围巾后偷看，表示好奇或害羞", ["shy", "curious"]),
    "sigh/wuyu.jpg": ("无语", "扶额叹气，表达无奈", ["sigh", "frustrated"]),
    "sleep/shuijiao.jpg": ("睡觉", "闭眼休息，表达困倦或晚安", ["sleepy", "rest"]),
    "surprised/xia.jpg": ("吓到", "受到惊吓，表达意外", ["surprised", "shocked"]),
    "work/tangping.jpg": ("躺平", "趴着躺平，表达暂时休息或摆烂玩笑", ["tired", "relaxed"]),
}
_MARKER = re.compile(r"\[表情[:：]\s*([^\]\r\n]{1,240}?)\s*\]")


def _builtin_items():
    root = Path(__file__).resolve().parent.parent / "web" / "stickers"
    return [{"id": f"builtin/{key}.svg", "label": label,
             "meaning": BUILTIN_MEANINGS.get(key, label), "tags": [key],
             "persona_scope": ["nianxiang", "whale"], "license": "project",
             "pack": "builtin", "url": f"/static/stickers/{key}.svg"}
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
            rel = f"{tag}/{f.name}"
            known = PACK_MEANINGS.get(rel)
            label = (known[0] if known else (meta.get("name") if label_by_pack else f.stem))
            meaning = known[1] if known else label
            tags = list(known[2]) if known else [tag, pack]
            items.append({
                "id": f"{pack}/{tag}/{f.name}",
                "label": label,
                "meaning": meaning,
                "tags": tags,
                "persona_scope": ["whale"] if pack == "dafeiyu-001" else ["nianxiang", "whale"],
                "license": meta.get("license") or "unknown",
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


def _shared_items(persona_id: str = "nianxiang"):
    """Return only deployed, shared assets allowed for a persona.

    Local DSH plugin assets intentionally stay out of this list: they are
    useful to the manual picker on this machine but are not guaranteed to be
    available to another client or to the model service.
    """
    persona = str(persona_id or "nianxiang").strip().lower()
    builtin, (server, _) = _builtin_items(), _server_items()
    return [item for item in [*builtin, *server]
            if persona in (item.get("persona_scope") or ["nianxiang", "whale"])]


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


def meme_prompt_catalog(persona_id: str = "nianxiang") -> list[dict[str, str]]:
    """Return precise, safe sticker IDs for model prompting.

    The catalog is limited to server-shipped assets and includes one entry per
    image so the model can distinguish two images in the same emotion group.
    """
    return [{"id": item["id"], "label": str(item.get("label") or item["id"]),
             "meaning": str(item.get("meaning") or item.get("label") or item["id"]),
             "tags": list(item.get("tags") or []),
             "persona_scope": list(item.get("persona_scope") or []),
             "license": str(item.get("license") or "unknown"),
             "url": item["url"]}
            for item in _shared_items(persona_id)]


def sanitize_meme_markers(text: str, persona_id: str = "nianxiang", max_count: int = 1) -> str:
    """Normalize precise/legacy markers and remove unsafe or excess markers."""
    allowed = _shared_items(persona_id)
    by_id = {item["id"]: item["id"] for item in allowed}
    by_tag = {}
    for item in allowed:
        # Legacy tags remain supported; prefer the first deterministic item.
        for tag in [*(item.get("tags") or []), item.get("pack", "")]:
            if tag:
                by_tag.setdefault(str(tag), item["id"])
    remaining = max(0, int(max_count))

    def resolve(match):
        nonlocal remaining
        key = match.group(1).strip()
        selected = by_id.get(key) or by_tag.get(key)
        if not selected or remaining <= 0:
            return ""
        remaining -= 1
        return f"[表情: {selected}]"

    return _MARKER.sub(resolve, str(text or ""))
