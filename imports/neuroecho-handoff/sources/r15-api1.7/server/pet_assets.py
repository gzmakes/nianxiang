"""Read the separately installed, non-commercial dsh-pet assets locally.

The animation files remain in the user's installation and are not bundled with
the web application.  Only direct, regular WebM files may be opened.
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from urllib.parse import quote

ROOT = Path.home() / ".dsh/profiles/desktop/node_modules/dsh-pet/assets/webm"
MEMES_ROOT = Path.home() / ".dsh/profiles/desktop/node_modules/dsh-pet/assets/memes"
MEME_NAMES = frozenset({
    "Ciallo", "token给妈妈保管", "假如给我三天多模态", "先养着吧", "厉害了我的鲸", "压力一只大肥鱼",
    "可爱", "吃白饭的大肥鱼", "吃饱饱摸肚子", "哦鲸鲸", "哪来的电脑病毒", "大师这个区是什么意思",
    "大烧货", "大的药来了", "大的要来啦", "完蛋了把黄油删了", "就一碗", "就骚了怎么滴吧",
    "我不更新你们用什么", "死掉了", "深度睡眠", "电死你", "要不直接骂他", "誓死践行开源精神",
    "除了调情没啥用", "鱼片有资源吗", "黎曼猜想没证明喵",
})


def manifest() -> dict:
    try:
        entries = sorted((p for p in ROOT.iterdir() if p.suffix == ".webm"
                          and p.is_file() and not p.is_symlink()), key=lambda p: p.name)
    except OSError:
        entries = []
    return {"available": bool(entries), "animations": [
        {"name": p.stem, "url": "/api/pet-assets/" + quote(p.name, safe="")}
        for p in entries
    ]}


def meme_manifest() -> dict:
    try:
        entries = sorted((p for p in MEMES_ROOT.iterdir() if p.suffix == ".png"
                          and p.stem in MEME_NAMES and p.is_file() and not p.is_symlink()), key=lambda p: p.name)
    except OSError:
        entries = []
    return {"available": bool(entries), "memes": [
        {"name": p.stem, "url": "/api/pet-memes/" + quote(p.name, safe="")}
        for p in entries
    ]}


def _open_direct(root: Path, name: str, suffix: str):
    if not name.endswith(suffix) or name in (suffix, ".", "..") or "/" in name or "\\" in name:
        return None
    try:
        fd = os.open(root / name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                os.close(fd)
                return None
            return os.fdopen(fd, "rb"), info.st_size
        except BaseException:
            os.close(fd)
            raise
    except (OSError, ValueError):
        return None


def open_video(name: str):
    """Open a single directly installed video, never following a file symlink."""
    return _open_direct(ROOT, name, ".webm")


def open_meme(name: str):
    if not name.endswith(".png") or name[:-4] not in MEME_NAMES:
        return None
    return _open_direct(MEMES_ROOT, name, ".png")


def byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Resolve one RFC 9110 byte range; None means malformed/unsatisfiable."""
    if not header:
        return (0, size - 1)
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if not match or not (match[1] or match[2]) or not size:
        return None
    if not match[1]:
        suffix = int(match[2])
        return (max(size - suffix, 0), size - 1) if suffix else None
    start = int(match[1])
    end = min(int(match[2]), size - 1) if match[2] else size - 1
    return (start, end) if start < size and start <= end else None
