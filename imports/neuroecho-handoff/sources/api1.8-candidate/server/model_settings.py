"""本机模型设置（JSON 文件，仅本机）。

安全说明：这是本地演示产品的简化实现，API key 以明文写入本机文件（权限 600），
不进入仓库（.gitignore）。生产应改用系统钥匙串/KMS。
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlsplit

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model-settings.json")
DEFAULT_TIMEOUT = 40


def load() -> dict:
    try:
        with open(PATH, encoding="utf-8") as f:
            d = json.load(f)
        return {
            "base_url": d.get("base_url", ""),
            "api_key": d.get("api_key", ""),
            "model": d.get("model", ""),
            "timeout": float(d.get("timeout", DEFAULT_TIMEOUT) or DEFAULT_TIMEOUT),
        }
    except Exception:
        return {"base_url": "", "api_key": "", "model": "", "timeout": DEFAULT_TIMEOUT}


def save(base_url: str, api_key: str, model: str, timeout: float | None = None) -> dict:
    if not is_safe_model_url(base_url):
        raise ValueError('模型服务地址无效：远程服务须使用 HTTPS；HTTP 仅支持本机 localhost、127.0.0.1 或 [::1]。')
    # The settings UI edits model/key/base only. An omitted timeout means keep
    # the current value, not reset it to the default on every save.
    if timeout is None:
        timeout = load()["timeout"]
    d = {"base_url": base_url.strip().rstrip("/"), "api_key": api_key.strip(),
         "model": model.strip(), "timeout": float(timeout or DEFAULT_TIMEOUT)}
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    try:
        os.chmod(PATH, 0o600)
    except OSError:
        pass
    return redacted()


def clear() -> dict:
    try:
        os.remove(PATH)
    except FileNotFoundError:
        pass
    return redacted()


def environment_managed() -> bool:
    """Any runtime model override makes editing only the file misleading."""
    return any(os.getenv(name, "").strip() for name in (
        "XINJI_MODEL_BASE_URL", "XINJI_MODEL_API_KEY", "XINJI_MODEL_NAME"))


def _origin(url: str):
    try:
        if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url) or '\\' in url:
            return None
        parts = urlsplit(url.strip())
        scheme = parts.scheme.lower()
        if (scheme not in ("http", "https") or not parts.hostname or
                parts.username is not None or parts.password is not None or
                parts.query or parts.fragment):
            return None
        port = parts.port
        if port == 0:
            return None
        return (scheme, parts.hostname.lower(), port if port is not None else (443 if scheme == "https" else 80))
    except (ValueError, AttributeError):
        return None


def is_safe_model_url(url: str) -> bool:
    """Require TLS except for exact loopback literals; never resolve DNS."""
    origin = _origin(url)
    return bool(origin and (origin[0] == 'https' or
                            (origin[0] == 'http' and origin[1] in ('localhost', '127.0.0.1', '::1'))))


def resolved() -> dict:
    """Resolve a configuration without transferring a saved key to a new origin."""
    d = load()
    override_base = os.getenv("XINJI_MODEL_BASE_URL", "").strip()
    saved_base = (d.get("base_url") or "").strip()
    base = override_base or saved_base
    key = os.getenv("XINJI_MODEL_API_KEY", "").strip()
    if not key:
        # A partial environment override may change the destination. Do not
        # implicitly send the saved credential to a different or invalid origin.
        safe_saved_key = not override_base or (_origin(override_base) is not None and
                                               _origin(override_base) == _origin(saved_base))
        key = (d.get("api_key") or "").strip() if safe_saved_key else ""
    name = os.getenv("XINJI_MODEL_NAME", "").strip() or (d.get("model") or "").strip()
    try:
        timeout = float(os.getenv("XINJI_MODEL_TIMEOUT", "") or d.get("timeout") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    return {"base_url": base.rstrip("/"), "api_key": key, "model": name, "timeout": timeout}


def redacted() -> dict:
    value = resolved()
    return {"configured": bool(is_safe_model_url(value["base_url"]) and value["api_key"] and value["model"]),
            "base_url": value["base_url"], "model": value["model"],
            "has_key": bool(value["api_key"]), "timeout": value["timeout"],
            "managed_by_environment": environment_managed()}
