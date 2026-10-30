"""Separate, opt-in device grant for Feishu search. No authorization at import."""
import json
import threading

from . import lark_auth, lark_auth_coordinator as coordinator

SCOPE = "search:docs:read"
STATE = {"status": "idle", "url": "", "qr": "", "error": "", "attempt": 0}
LOCK = threading.Lock()


def _public():
    return {k: STATE[k] for k in ("status", "url", "qr", "error")}


def _update(attempt, **values):
    with LOCK:
        if STATE["attempt"] == attempt:
            STATE.update(**values)


def _complete(device_code, attempt, reservation):
    try:
        p = lark_auth._run(["auth", "login", "--device-code", device_code, "--json"], timeout=600)
        if p.returncode != 0:
            _update(attempt, status="error", url="", qr="", error=lark_auth._cli_error(p, "完成搜索授权"))
            return
        data = json.loads(p.stdout or "{}")
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise ValueError("授权返回错误")
        # This only confirms completion of the device flow. Actual search may
        # still fail due to app configuration or another permission condition.
        _update(attempt, status="success", url="", qr="", error="")
    except Exception:
        _update(attempt, status="error", url="", qr="", error="搜索授权未完成，请重试或粘贴文档链接。")
    finally:
        coordinator.finish("search", reservation)


def start():
    disposition, reservation = coordinator.begin("search")
    if disposition == "conflict":
        return {"status": "error", "error": "另一项飞书授权仍在进行，请等待完成或过期后重试。"}
    if disposition == "same":
        with LOCK:
            current = _public()
        return current if current["status"] in ("starting", "pending") else {"status": "starting"}
    with LOCK:
        attempt = STATE["attempt"] + 1
        STATE.update(status="starting", url="", qr="", error="", attempt=attempt)
    try:
        p = lark_auth._run(["auth", "login", "--no-wait", "--json", "--scope", SCOPE], timeout=20)
        if p.returncode:
            _update(attempt, status="error", error=lark_auth._cli_error(p, "启动搜索授权"))
            coordinator.finish("search", reservation)
            return status()
        data = json.loads(p.stdout or "{}")
        url, code = data.get("verification_url"), data.get("device_code")
        if data.get("ok") is False or not url or not code:
            raise ValueError("missing authorization information")
        try:
            qr = lark_auth._qr_data_url(url)
        except Exception:
            qr = ""
        _update(attempt, status="pending", url=url, qr=qr, error="")
        threading.Thread(target=_complete, args=(code, attempt, reservation), daemon=True).start()
    except Exception:
        _update(attempt, status="error", error="无法启动搜索授权，请重试或粘贴文档链接。")
        coordinator.finish("search", reservation)
    return status()


def status():
    with LOCK:
        return _public()
