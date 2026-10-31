"""Fresh user grants and app-readiness classification. No real CLI or account."""
import json
import subprocess

import pytest
from fastapi.testclient import TestClient
from server import lark, lark_auth, lark_auth_coordinator as coordinator
from server.main import app

READY = {"ok": True, "app_configured": True, "config_status": "configured",
         "user_status": "ready", "token_status": "valid"}
FAKE_URL = "https://accounts.feishu.cn/oauth/v1/device/verify/?flow_id=synthetic&user_code=NOT-A-REAL-CODE"


def proc(code=0, out="", err=""):
    return subprocess.CompletedProcess(["fake-cli"], code, out, err)


@pytest.fixture(autouse=True)
def isolated_auth(monkeypatch):
    monkeypatch.setattr(coordinator, "_active", None)
    monkeypatch.setattr(lark_auth, "STATE", {"status": "idle", "url": "", "qr": "", "error": "", "started_at": 0})
    monkeypatch.setattr(lark, "auth_status", lambda: dict(READY))


def pending(monkeypatch):
    calls, workers = [], []
    def run(args, timeout):
        calls.append(args)
        return proc(out=json.dumps({"verification_url": FAKE_URL, "device_code": "fake-device-code"}))
    class Thread:
        def __init__(self, **kwargs): workers.append(kwargs)
        def start(self): pass
    monkeypatch.setattr(lark_auth, "_run", run)
    monkeypatch.setattr(lark_auth, "_qr_data_url", lambda value: "synthetic-qr")
    monkeypatch.setattr(lark_auth.threading, "Thread", Thread)
    return calls, workers


def test_default_compatible_but_force_requests_fresh_minimal_grant(monkeypatch):
    calls, workers = pending(monkeypatch)
    assert lark_auth.start()["status"] == "success"
    assert calls == []
    fresh = lark_auth.start(force=True)
    assert fresh["status"] == "pending" and fresh["url"] == FAKE_URL
    assert calls == [["auth", "login", "--no-wait", "--json", "--scope", "docx:document:readonly"]]
    assert len(workers) == 1 and "device_code" not in fresh
    assert lark_auth.status()["status"] == "pending"  # old token is not completion
    assert lark_auth.start(force=True)["status"] == "pending"  # reuse one in-flight flow
    assert len(calls) == 1
    assert coordinator.begin("search")[0] == "conflict"


@pytest.mark.parametrize("old_state", ["error", "cancelled"])
def test_terminal_attempt_cannot_be_relabelled_success_by_existing_grant(monkeypatch, old_state):
    lark_auth.STATE.update(status=old_state, error="synthetic denial", attempt=3)
    monkeypatch.setattr(lark, "auth_status", lambda: pytest.fail("terminal attempt must not consult an old grant"))
    assert lark_auth.status()["status"] == old_state


def test_failed_force_worker_clears_url_and_old_grant_cannot_mask_it(monkeypatch):
    calls, workers = pending(monkeypatch)
    assert lark_auth.start(force=True)["status"] == "pending"
    monkeypatch.setattr(lark_auth, "_run", lambda *a, **k: proc(3, err="PRIVATE synthetic CLI output"))
    workers[0]["target"](*workers[0]["args"])
    result = lark_auth.status()
    assert result["status"] == "error" and result["url"] == result["qr"] == ""
    assert "PRIVATE" not in repr(result)
    disposition, token = coordinator.begin("search")
    assert disposition == "new"
    coordinator.finish("search", token)


def test_real_completion_receipt_and_rechecked_user_status_can_finish_fresh_attempt(monkeypatch):
    _, workers = pending(monkeypatch)
    lark_auth.start(force=True)
    monkeypatch.setattr(lark_auth, "_run", lambda *a, **k: proc(0, out=json.dumps({"ok": True})))
    workers[0]["target"](*workers[0]["args"])
    result = lark_auth.status()
    assert result["status"] == "success" and result["url"] == result["qr"] == ""


# Rebind the actual adapter after the autouse auth-status stub where needed.
REAL_AUTH_STATUS = lark.auth_status


def adapter(monkeypatch, result):
    monkeypatch.setattr(lark.subprocess, "run", lambda *a, **k: result)
    return REAL_AUTH_STATUS()


def test_only_exact_official_missing_app_envelope_reports_setup(monkeypatch):
    error = {"ok": False, "error": {"type": "config", "message": "not configured", "hint": "PRIVATE"}}
    result = adapter(monkeypatch, proc(3, err=json.dumps(error)))
    assert result["app_configured"] is False
    assert result["error_code"] == "needs_app_setup"
    assert result["setup_url"] == lark.SETUP_HELP_URL and "user_code" not in result["setup_url"]
    assert "PRIVATE" not in repr(result)


@pytest.mark.parametrize("code,payload", [
    (3, {"ok": False, "error": {"type": "config", "message": "no active profile"}}),
    (3, {"ok": False, "error": {"type": "config", "message": "keychain PRIVATE"}}),
    (3, {"ok": False, "error": {"type": "config", "message": "failed to load config: PRIVATE"}}),
    (3, {"ok": False, "error": {"type": "network", "message": "not configured"}}),
    (1, {"ok": False, "error": {"type": "config", "message": "not configured"}}),
    (3, []), (3, "PRIVATE"),
])
def test_other_failure_is_not_permission_to_replace_app(monkeypatch, code, payload):
    result = adapter(monkeypatch, proc(code, err=json.dumps(payload)))
    assert result["error_code"] == "configuration_unavailable"
    assert result["app_configured"] is None and "setup_url" not in result
    assert "PRIVATE" not in repr(result)


def test_configured_app_is_independent_from_user_grant_and_does_not_expose_id(monkeypatch):
    result = adapter(monkeypatch, proc(out=json.dumps({"appId": "synthetic-app-id",
        "appSecret": "PRIVATE", "identities": {"user": {"status": "missing"}}})))
    assert result["ok"] and result["app_configured"] is True
    assert result["config_status"] == "configured"
    assert "synthetic-app-id" not in repr(result) and "PRIVATE" not in repr(result)


def test_unknown_status_exception_is_safe_not_setup(monkeypatch):
    def failed(*a, **k): raise RuntimeError("PRIVATE")
    monkeypatch.setattr(lark.subprocess, "run", failed)
    result = REAL_AUTH_STATUS()
    assert result["error_code"] == "configuration_unavailable"
    assert "PRIVATE" not in repr(result)


def test_missing_app_blocks_auth_without_creating_app(monkeypatch):
    error = {"ok": False, "app_configured": False, "error_code": "needs_app_setup",
             "error": "首次配置", "setup_url": lark.SETUP_HELP_URL}
    monkeypatch.setattr(lark, "auth_status", lambda: error)
    monkeypatch.setattr(lark_auth, "_run", lambda *a, **k: pytest.fail("no auth or config writes before app setup"))
    result = lark_auth.start(force=True)
    assert result["status"] == "error" and result["error_code"] == "needs_app_setup"
    assert result["url"] == result["qr"] == ""
    assert lark_auth.status() == result


def test_missing_app_from_login_is_classified_without_stdout_or_secret_echo(monkeypatch):
    monkeypatch.setattr(lark_auth, "_run", lambda *a, **k: proc(3, err=json.dumps({
        "ok": False, "error": {"type": "config", "message": "not configured", "appSecret": "PRIVATE"}})))
    result = lark_auth.start(force=True)
    assert result["error_code"] == "needs_app_setup" and "PRIVATE" not in repr(result)


def test_http_optional_body_strict_force_and_no_store(monkeypatch):
    calls = []
    monkeypatch.setattr(lark_auth, "start", lambda force=False: calls.append(force) or {"status": "pending", "url": FAKE_URL})
    monkeypatch.setattr(lark_auth, "status", lambda: {"status": "pending", "url": FAKE_URL})
    with TestClient(app) as client:
        for body in (None, {}, {"force": False}, {"force": True}):
            response = client.post("/api/auth/lark/start", **({} if body is None else {"json": body}))
            assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        for value in ("true", "false", 1, 0, None, []):
            assert client.post("/api/auth/lark/start", json={"force": value}).status_code == 422
        assert client.get("/api/auth/lark/status").headers["cache-control"] == "no-store"
    assert calls == [False, False, False, True]
