"""Explicit combined read/search grant; importing never starts authorization."""
from __future__ import annotations

import json
import threading

from . import feishu_account, lark_auth, lark_auth_coordinator as coordinator

SCOPE = "docx:document:readonly search:docs:read"
STATE = {"status": "idle", "url": "", "qr": "", "error": "", "error_code": "", "attempt": 0}
LOCK = threading.Lock()


def _public() -> dict:
    return {key: STATE.get(key, "") for key in ("status", "url", "qr", "error", "error_code", "permission_issue")}


def _update(attempt: int, **values) -> None:
    with LOCK:
        if STATE["attempt"] == attempt:
            STATE.update(**values)


def _complete(device_code: str, attempt: int, reservation: object) -> None:
    try:
        result = lark_auth._run(["auth", "login", "--device-code", device_code, "--json"], timeout=600)
        if result.returncode != 0:
            _update(attempt, status="error", url="", qr="", error=lark_auth._cli_error(result, "完成账户授权"),
                    error_code="authorization_completion_failed")
            return
        receipt = json.loads(result.stdout or "{}")
        if not isinstance(receipt, dict) or receipt.get("ok") is not True:
            raise ValueError("invalid completion")
        # A successful OAuth receipt is not proof of search readiness. Use the
        # real read-only search endpoint before reporting account readiness.
        checked = feishu_account.verify_access()
        if checked.get("ok"):
            _update(attempt, status="success", url="", qr="", error="", error_code="", permission_issue="")
        else:
            _update(attempt, status="error", url="", qr="", error=checked["error"],
                    error_code=checked["error_code"], permission_issue=checked.get("permission_issue", ""))
    except Exception:
        _update(attempt, status="error", url="", qr="", error="账户授权未完成或已超时，请重试。", error_code="authorization_completion_failed")
    finally:
        coordinator.finish("account", reservation)


def start() -> dict:
    """Called only after an explicit account-authorization action in the UI."""
    disposition, reservation = coordinator.begin("account")
    if disposition == "conflict":
        return {"status": "error", "error": "另一项飞书授权仍在进行，请等待完成或过期后重试。", "error_code": "authorization_in_progress"}
    if disposition == "same":
        with LOCK:
            current = _public()
        return current if current["status"] in ("starting", "pending") else {"status": "starting"}
    with LOCK:
        attempt = STATE["attempt"] + 1
        STATE.update(status="starting", url="", qr="", error="", error_code="", permission_issue="", attempt=attempt)
    try:
        result = lark_auth._run(["auth", "login", "--no-wait", "--json", "--scope", SCOPE], timeout=20)
        if result.returncode:
            setup = lark_auth.lark.cli_configuration_failure(result)
            _update(attempt, status="error", url="", qr="", error=setup["error"] if setup else lark_auth._cli_error(result, "启动账户授权"),
                    error_code=setup["error_code"] if setup else "authorization_start_failed", permission_issue="app_config" if setup else "")
            coordinator.finish("account", reservation)
            return status()
        payload = json.loads(result.stdout or "{}")
        if not isinstance(payload, dict) or payload.get("ok") is False:
            raise ValueError("invalid start")
        url, code = payload.get("verification_url"), payload.get("device_code")
        if not isinstance(url, str) or not url or not isinstance(code, str) or not code:
            raise ValueError("missing grant fields")
        try:
            qr = lark_auth._qr_data_url(url)
        except Exception:
            qr = ""
        _update(attempt, status="pending", url=url, qr=qr, error="", error_code="", permission_issue="")
        threading.Thread(target=_complete, args=(code, attempt, reservation), daemon=True).start()
    except Exception:
        _update(attempt, status="error", url="", qr="", error="无法启动飞书账户授权，请重试。", error_code="authorization_start_failed")
        coordinator.finish("account", reservation)
    return status()


def status() -> dict:
    with LOCK:
        return _public()
