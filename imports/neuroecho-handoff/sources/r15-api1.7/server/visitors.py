"""匿名访客隔离：签名 Cookie 身份（可选 IP/UA 兜底，不是账号系统）。

设计边界（必须如实告诉使用者）：
- 清空 Cookie 就会得到一个新身份，历史数据留在旧空间里；
- 开启 XINJI_VISITOR_IP_FALLBACK 后，同一出口 IP 且没有 Cookie 的多个访客会落到同一个空间（NAT/公司网）；
- 这里只做「数据分区」，不构成认证，不能用来保护隐私数据。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import threading
import uuid
from pathlib import Path

ENABLED = os.getenv("XINJI_VISITOR_ISOLATION", "").strip() not in ("", "0", "false", "False", "no")
IP_FALLBACK = os.getenv("XINJI_VISITOR_IP_FALLBACK", "").strip() not in ("", "0", "false", "False", "no")
COOKIE = "nx_visitor"
MAX_AGE = 60 * 60 * 24 * 365
_ID = re.compile(r"^v_[0-9a-f]{32}$")

DATA_DIR = Path(os.getenv("XINJI_VISITOR_DIR", "").strip()
                or (Path(__file__).resolve().parent / "visitors"))
_SECRET_FILE = DATA_DIR / ".secret"

_lock = threading.RLock()
_initialized: set[str] = set()


def _secret() -> bytes:
    """HMAC key: explicit env first, else a private file beside the databases."""
    env = os.getenv("XINJI_VISITOR_SECRET", "").strip()
    if env:
        return env.encode()
    with _lock:
        try:
            return _SECRET_FILE.read_bytes()
        except OSError:
            pass
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        value = os.urandom(32)
        _SECRET_FILE.write_bytes(value)
        try:
            os.chmod(_SECRET_FILE, 0o600)
        except OSError:
            pass
        return value


def _sign(visitor_id: str) -> str:
    return hmac.new(_secret(), visitor_id.encode("ascii"), hashlib.sha256).hexdigest()[:32]


def _valid(visitor_id: str, signature: str) -> bool:
    return bool(_ID.match(visitor_id)) and hmac.compare_digest(_sign(visitor_id), signature)


def cookie_value(visitor_id: str) -> str:
    return f"{visitor_id}.{_sign(visitor_id)}"


def from_cookie(raw: str | None) -> str | None:
    if not raw or "." not in raw:
        return None
    visitor_id, signature = raw.rsplit(".", 1)
    return visitor_id if _valid(visitor_id, signature) else None


def new_id() -> str:
    """Fresh identity for a browser that has no valid cookie yet."""
    return "v_" + uuid.uuid4().hex


def from_address(peer: str, user_agent: str) -> str:
    """Coarse fallback for clients that do not keep cookies.

    Anyone behind the same NAT with the same browser shares this space, so it is
    opt-in via XINJI_VISITOR_IP_FALLBACK instead of the default.
    """
    digest = hmac.new(_secret(), f"{peer}\n{user_agent}".encode("utf-8", "replace"),
                      hashlib.sha256).hexdigest()
    return "v_" + digest[:32]


def db_file(visitor_id: str) -> Path:
    return DATA_DIR / f"{visitor_id}.db"


def ensure(database: Path) -> None:
    """Create and migrate a visitor database once per process."""
    key = str(database)
    if key in _initialized:
        return
    with _lock:
        if key in _initialized:
            return
        database.parent.mkdir(parents=True, exist_ok=True)
        from . import core

        token = core.use_db(database)
        try:
            core.init_db()
        finally:
            core.reset_db(token)
        _initialized.add(key)
