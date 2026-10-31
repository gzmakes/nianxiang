"""本机模型设置（JSON 文件，仅本机）。

安全说明：这是本地演示产品的简化实现，API key 以明文写入本机文件（权限 600），
不进入仓库（.gitignore）。生产应改用系统钥匙串/KMS。
"""
from __future__ import annotations

import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model-settings.json")

# 公共演示节点（云函数代理，源码见仓库 nx-proxy/）。目的是让 clone 下来的人
# 不用自带 key 也能跑真模型：key 只在云端函数的环境变量里，客户端拿不到。
# 想强制「无模型 → 规则引擎」的行为，设 XINJI_MODEL_PUBLIC=0。
PUBLIC_BASE_URL = (os.getenv("XINJI_MODEL_PUBLIC_BASE_URL", "").strip()
                   or "https://yuntun-5g1u97p56054130d.service.tcloudbase.com/nxproxy")
PUBLIC_MODEL = os.getenv("XINJI_MODEL_PUBLIC_MODEL", "").strip() or "deepseek-v4-flash"
PUBLIC_KEY = os.getenv("XINJI_MODEL_PUBLIC_KEY", "").strip() or "public"


def public_enabled() -> bool:
    return os.getenv("XINJI_MODEL_PUBLIC", "").strip().lower() not in ("0", "false", "no", "off")


def public_endpoint() -> dict | None:
    if not public_enabled() or not PUBLIC_BASE_URL:
        return None
    try:
        timeout = float(os.getenv("XINJI_MODEL_PUBLIC_TIMEOUT", "") or 20)
    except ValueError:
        timeout = 20.0
    return {"base_url": PUBLIC_BASE_URL.rstrip("/"), "api_key": PUBLIC_KEY,
            "model": PUBLIC_MODEL, "timeout": timeout}


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
    configured = bool(base and key and name)
    public = public_endpoint()
    return {
        "configured": configured,
        "base_url": base.rstrip("/") if base else (public["base_url"] if public else ""),
        "model": name or (public["model"] if public else ""),
        "has_key": bool(key) or bool(public),
        "timeout": timeout,
        "managed_by_environment": environment_managed(),
        # 没有本机设置时是否在使用公共演示节点（前端可据此提示"公共节点"）。
        "public_fallback": (not configured) and public is not None,
    }
