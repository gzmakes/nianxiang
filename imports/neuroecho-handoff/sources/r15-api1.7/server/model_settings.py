"""本机模型设置（JSON 文件，仅本机）。

安全说明：这是本地演示产品的简化实现，API key 以明文写入本机文件（权限 600），
不进入仓库（.gitignore）。生产应改用系统钥匙串/KMS。
"""
from __future__ import annotations

import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model-settings.json")


def load() -> dict:
    try:
        with open(PATH, encoding="utf-8") as f:
            d = json.load(f)
        return {
            "base_url": d.get("base_url", ""),
            "api_key": d.get("api_key", ""),
            "model": d.get("model", ""),
            "timeout": float(d.get("timeout", 8) or 8),
        }
    except Exception:
        return {"base_url": "", "api_key": "", "model": "", "timeout": 8}


def save(base_url: str, api_key: str, model: str, timeout: float = 8) -> dict:
    d = {"base_url": base_url.strip().rstrip("/"), "api_key": api_key.strip(),
         "model": model.strip(), "timeout": float(timeout or 8)}
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


def redacted() -> dict:
    d = load()
    base = os.getenv("XINJI_MODEL_BASE_URL", "").strip() or (d.get("base_url") or "").strip()
    key = os.getenv("XINJI_MODEL_API_KEY", "").strip() or (d.get("api_key") or "").strip()
    name = os.getenv("XINJI_MODEL_NAME", "").strip() or (d.get("model") or "").strip()
    try:
        timeout = float(os.getenv("XINJI_MODEL_TIMEOUT", "") or d.get("timeout") or 8)
    except (TypeError, ValueError):
        timeout = 8
    return {
        "configured": bool(base and key and name),
        "base_url": base.rstrip("/"),
        "model": name,
        "has_key": bool(key),
        "timeout": timeout,
        "managed_by_environment": environment_managed(),
    }
