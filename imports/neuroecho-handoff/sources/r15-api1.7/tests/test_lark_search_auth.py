"""Search consent tests use no real credentials or network."""
import json
import subprocess

import pytest
from server import lark, lark_auth, lark_search_auth as auth, lark_auth_coordinator as coordinator


def proc(returncode=0, out="", err=""):
    return subprocess.CompletedProcess(["fake"], returncode, out, err)


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.setattr(auth, "STATE", {"status": "idle", "url": "", "qr": "", "error": "", "attempt": 0})
    monkeypatch.setattr(coordinator, "_active", None)


def test_search_error_distinguishes_user_app_and_ordinary_failure(monkeypatch):
    def search(error):
        monkeypatch.setattr(lark.subprocess, "run", lambda *a, **kw: proc(1, json.dumps({"ok": False, "error": error})))
        return lark.search_docs("demo")
    assert search({"subtype": "need_user_authorization", "scope": "search:docs:read"})["permission_issue"] == "user_grant"
    assert search({"subtype": "need_user_authorization", "scope": "search:docs:read", "console_url": "https://example.invalid"})["permission_issue"] == "user_grant"
    assert search({"message": "missing search:docs:read", "console_url": "https://example.invalid"})["permission_issue"] == "app_config"
    assert "permission_issue" not in search({"message": "network unavailable"})


def test_search_grant_requires_new_flow_even_with_ready_existing_user(monkeypatch):
    monkeypatch.setattr(lark, "auth_status", lambda: {"ok": True, "user_status": "ready"})
    calls = []
    def fake_run(args, timeout):
        calls.append(args)
        return proc(out=json.dumps({"verification_url": "https://example.invalid/auth", "device_code": "fake"}))
    monkeypatch.setattr(lark_auth, "_run", fake_run)
    monkeypatch.setattr(lark_auth, "_qr_data_url", lambda url: "fake-qr")
    threads = []
    class Thread:
        def __init__(self, **kwargs): threads.append(kwargs)
        def start(self): pass
    monkeypatch.setattr(auth.threading, "Thread", Thread)
    result = auth.start()
    assert result["status"] == "pending"
    assert calls == [["auth", "login", "--no-wait", "--json", "--scope", "search:docs:read"]]
    assert auth.status()["status"] == "pending"  # existing user token is not search consent
    assert auth.start()["status"] == "pending" and len(calls) == 1
    assert "device_code" not in result


def test_only_successful_device_completion_sets_success(monkeypatch):
    _, token1 = coordinator.begin("search")
    auth.STATE.update(status="pending", attempt=1, url="fake")
    monkeypatch.setattr(lark_auth, "_run", lambda *a, **kw: proc(0, json.dumps({"ok": False})))
    auth._complete("fake", 1, token1)
    assert auth.status()["status"] == "error"
    _, token2 = coordinator.begin("search")
    auth.STATE.update(status="pending", attempt=2)
    monkeypatch.setattr(lark_auth, "_run", lambda *a, **kw: proc(0, json.dumps({"ok": True})))
    auth._complete("fake", 1, token1)
    assert auth.status()["status"] == "pending"  # stale attempt cannot win
    assert coordinator.begin("document")[0] == "conflict"  # stale worker cannot release token2
    auth._complete("fake", 2, token2)
    assert auth.status()["status"] == "success"


def test_simultaneous_flows_are_serialized_and_starting_is_not_failure(monkeypatch):
    import threading
    RealThread = threading.Thread
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(lark, "auth_status", lambda: {"ok": True, "user_status": "not_authorized"})
    def fake_run(args, timeout):
        if "--no-wait" in args:
            entered.set()
            assert release.wait(3)
            return proc(out=json.dumps({"verification_url": "https://example.invalid/auth", "device_code": "fake"}))
        raise subprocess.TimeoutExpired(args, timeout)
    monkeypatch.setattr(lark_auth, "_run", fake_run)
    monkeypatch.setattr(lark_auth, "_qr_data_url", lambda _: "")
    workers = []
    class FakeThread:
        def __init__(self, **kwargs): workers.append(kwargs)
        def start(self): pass
    monkeypatch.setattr(auth.threading, "Thread", FakeThread)
    results = []
    t = RealThread(target=lambda: results.append(auth.start()))
    t.start()
    assert entered.wait(3)
    assert auth.start()["status"] == "starting"
    assert lark_auth.start()["status"] == "error"
    release.set(); t.join()
    assert results[0]["status"] == "pending"
    assert lark_auth.start()["status"] == "error"
    workers[0]["target"](*workers[0]["args"])
    assert auth.status()["status"] == "error"
    # The timed-out worker releases the lock so the other purpose can begin.
    disposition, token = coordinator.begin("document")
    assert disposition == "new"
    coordinator.finish("document", token)


def test_search_query_is_post_body_not_url(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from server import core
    from server.main import app
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    seen = []
    monkeypatch.setattr(lark, "search_docs", lambda query: seen.append(query) or {"ok": True, "items": []})
    with TestClient(app) as client:
        assert client.post("/api/lark/docs", json={"q": "合成搜索词"}).status_code == 200
        assert client.get("/api/lark/docs", params={"q": "合成搜索词"}).status_code == 405
    assert seen == ["合成搜索词"]
