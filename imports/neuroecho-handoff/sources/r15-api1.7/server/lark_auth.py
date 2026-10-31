"""飞书 Device Flow 授权：点「连接飞书」直接拉起授权，不让用户填 token/链接。

流程：
1. `lark-cli auth login --no-wait --json` 拿 verification_url + device_code；
2. 服务端生成二维码，返回给前端展示；
3. 后台线程执行 `--device-code` 轮询完成，前端轮询 /api/auth/lark/status。
"""
from __future__ import annotations

import base64
import io
import json
import subprocess
import threading
import time

from . import lark, lark_auth_coordinator as coordinator

SCOPE = "docx:document:readonly"
STATE: dict = {"status": "idle", "url": "", "qr": "", "error": "", "started_at": 0}
_LOCK = threading.Lock()


def _run(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run([lark.LARK_BIN, *args], capture_output=True, text=True, timeout=timeout,
                          env=lark.cli_env())


def _qr_data_url(url: str) -> str:
    import qrcode
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _friendly(msg: str) -> str:
    s = (msg or "").strip()
    if any(k in s.lower() for k in ("keychain", "operation not permitted", "sandbox")):
        return "飞书 CLI 无法访问本机凭据存储。请检查系统权限；变更凭据存储前需先确认其影响。"
    return s[:220]


def _cli_error(p: subprocess.CompletedProcess, action: str) -> str:
    """Return a useful category without forwarding arbitrary credential-bearing output."""
    raw = ((p.stderr or "") + " " + (p.stdout or "")).lower()
    if any(k in raw for k in ("keychain", "operation not permitted", "sandbox")):
        return _friendly("keychain")
    if "not_configured" in raw or "not configured" in raw:
        return "飞书连接尚未准备完成，请重新点击连接飞书。"
    if "scope" in raw or "permission" in raw:
        return f"{action}失败：飞书权限或应用配置不足，请检查所需授权范围。"
    return f"{action}失败：飞书 CLI 返回错误（退出码 {p.returncode}）。"


def setup_keychain() -> dict:
    try:
        p = _run(["config", "keychain-downgrade"], timeout=20)
    except Exception as e:
        return {"ok": False, "error": _friendly(str(e))}
    raw = (p.stdout or p.stderr or "").strip()
    if p.returncode == 0 or "already" in raw.lower():
        return {"ok": True, "message": raw[:200]}
    return {"ok": False, "error": _friendly(raw)}


def _public() -> dict:
    return {k: STATE.get(k) for k in ("status", "url", "qr", "error", "started_at", "phase")}


def _update(attempt: int, **values) -> None:
    with _LOCK:
        if STATE.get("attempt", 0) == attempt:
            STATE.update(**values)


def _complete(device_code: str, attempt: int, reservation: object) -> None:
    try:
        p = _run(["auth", "login", "--device-code", device_code, "--json"], timeout=600)
        if p.returncode != 0:
            _update(attempt, status="error", url="", qr="", error=_cli_error(p, "完成授权"))
            return
        st = lark.auth_status()
        if lark.user_ready(st):
            _update(attempt, status="success", url="", qr="", error="")
        else:
            _update(attempt, status="error", url="", qr="", error="授权已返回，但本地 token 未就绪；请重试")
    except Exception:
        _update(attempt, status="error", url="", qr="", error="授权未完成或已超时，请重试。")
    finally:
        coordinator.finish("document", reservation)


def _initialize(attempt, reservation):
    from . import lark_setup
    handed_off = False
    try:
        def show(url):
            try:
                qr = _qr_data_url(url)
            except Exception:
                qr = ""
            _update(attempt, status="pending", phase="setup", url=url, qr=qr, error="")
        if not lark_setup.initialize(show):
            raise RuntimeError("setup failed")
        _update(attempt, status="starting", phase="authorize", url="", qr="")
        p = _run(["auth", "login", "--no-wait", "--json", "--scope", SCOPE], timeout=20)
        if p.returncode != 0:
            raise RuntimeError("login failed")
        data = json.loads(p.stdout or "{}")
        url, code = data.get("verification_url"), data.get("device_code")
        if not url or not code or data.get("ok") is False:
            raise RuntimeError("missing grant")
        try:
            qr = _qr_data_url(url)
        except Exception:
            qr = ""
        _update(attempt, status="pending", phase="authorize", url=url, qr=qr, error="")
        handed_off = True
        _complete(code, attempt, reservation)
    except Exception:
        _update(attempt, status="error", url="", qr="",
                error="飞书连接未完成或已超时，请重新点击连接；若持续失败，请联系管理员检查服务网络和飞书应用权限。")
    finally:
        if not handed_off:
            coordinator.finish("document", reservation)

def start() -> dict:
    disposition, reservation = coordinator.begin("document")
    if disposition == "conflict":
        return {"status": "error", "error": "另一项飞书授权仍在进行，请等待完成或过期后重试。"}
    if disposition == "same":
        with _LOCK:
            current = _public()
        return current if current["status"] in ("starting", "pending") else {"status": "starting"}
    with _LOCK:
        attempt = STATE.get("attempt", 0) + 1
        STATE.update(status="starting", url="", qr="", error="", started_at=time.time(), attempt=attempt, phase="authorize")
    try:
        st = lark.auth_status()
        if lark.user_ready(st):
            _update(attempt, status="success", url="", qr="", error="", started_at=time.time())
            coordinator.finish("document", reservation)
            with _LOCK:
                return _public()
        p = _run(["auth", "login", "--no-wait", "--json", "--scope", SCOPE], timeout=20)
        if p.returncode != 0 and any(word in ((p.stdout or "") + (p.stderr or "")).lower()
                                     for word in ("not_configured", "not configured")):
            _update(attempt, phase="setup")
            threading.Thread(target=_initialize, args=(attempt, reservation), daemon=True).start()
            with _LOCK:
                return _public()
        if p.returncode != 0:
            _update(attempt, status="error", error=_cli_error(p, "启动授权"))
            coordinator.finish("document", reservation)
            with _LOCK:
                return _public()
        data = json.loads(p.stdout or "{}")
        if not isinstance(data, dict) or data.get("ok") is False:
            raise ValueError("invalid response")
        url, code = data.get("verification_url") or "", data.get("device_code") or ""
        if not url or not code:
            raise ValueError("missing authorization information")
        try:
            qr = _qr_data_url(url)
        except Exception:
            qr = ""
        _update(attempt, status="pending", url=url, qr=qr, error="", started_at=time.time())
        threading.Thread(target=_complete, args=(code, attempt, reservation), daemon=True).start()
    except Exception:
        _update(attempt, status="error", url="", qr="", error="无法启动飞书授权，请重试。")
        coordinator.finish("document", reservation)
    with _LOCK:
        return _public()


def status() -> dict:
    with _LOCK:
        cur = _public()
        attempt = STATE.get("attempt", 0)
    if cur["status"] in ("starting", "pending"):
        return cur
    st = lark.auth_status()
    with _LOCK:
        # A status lookup can outlive a later start or worker completion.
        if STATE.get("attempt", 0) != attempt or STATE.get("status") != cur["status"]:
            return _public()
        if lark.user_ready(st):
            STATE.update(status="success", url="", qr="", error="")
        elif cur["status"] == "success":
            STATE.update(status="idle", url="", qr="", error="授权未就绪或已过期，请重新授权")
        return _public()
