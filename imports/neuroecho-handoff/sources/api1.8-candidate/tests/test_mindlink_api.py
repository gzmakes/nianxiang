"""MindLink consent routes: every EEG read is mocked, never contacts a device."""
import threading

import pytest
from fastapi.testclient import TestClient

from server import main, mindlink


@pytest.fixture
def client():
    with main._mindlink_lock:
        main._mindlink_grants.clear()
    with TestClient(main.app, base_url="http://127.0.0.1:8787", client=("127.0.0.1", 50000)) as c:
        yield c
    with main._mindlink_lock:
        main._mindlink_grants.clear()


def test_explicit_consent_then_read_and_stop(client, monkeypatch):
    calls = []
    def fake_read(*, enabled=False):
        calls.append(enabled)
        return {"available": True, "reason": None, "source": "neurosky_esense", "score": 67, "age_ms": 500}
    monkeypatch.setattr(mindlink, "read_attention", fake_read)
    assert client.post("/api/mindlink/state").status_code == 403
    assert client.post("/api/mindlink/start", json={"consent": False}).status_code == 400
    assert calls == []
    start = client.post("/api/mindlink/start", json={"consent": True})
    assert start.status_code == 200 and start.headers["cache-control"] == "no-store"
    assert calls == []
    headers = {"X-MindLink-Token": start.json()["token"]}
    reading = client.post("/api/mindlink/state", headers=headers)
    assert reading.status_code == 200 and reading.json()["score"] == 67
    assert calls == [True]
    assert client.post("/api/mindlink/stop", headers=headers).json() == {"enabled": False}
    assert client.post("/api/mindlink/state", headers=headers).status_code == 403
    assert client.post("/api/mindlink/stop", headers=headers).status_code == 403
    assert calls == [True]


def test_offline_is_explicit_and_never_preserves_score(client, monkeypatch):
    results = iter([
        {"available": True, "reason": None, "source": "neurosky_esense", "score": 70, "age_ms": 100},
        {"available": False, "reason": "service_unavailable", "source": "neurosky_esense", "score": None, "age_ms": None},
    ])
    monkeypatch.setattr(mindlink, "read_attention", lambda **kwargs: next(results))
    token = client.post("/api/mindlink/start", json={"consent": True}).json()["token"]
    headers = {"X-MindLink-Token": token}
    assert client.post("/api/mindlink/state", headers=headers).json()["score"] == 70
    offline = client.post("/api/mindlink/state", headers=headers).json()
    assert offline["available"] is False and offline["score"] is None
    assert offline["reason"] == "service_unavailable"


def test_disallows_remote_and_foreign_origins(client, monkeypatch):
    monkeypatch.setattr(mindlink, "read_attention", lambda **kwargs: pytest.fail("unauthorized read"))
    assert client.post("/api/mindlink/start", headers={"Origin": "https://attacker.example"}, json={"consent": True}).status_code == 403
    assert client.post("/api/mindlink/start", headers={"Host": "evil.example"}, json={"consent": True}).status_code == 403
    assert client.post("/api/mindlink/start", headers={"Origin": "null"}, json={"consent": True}).status_code == 403
    # Same running app, a different peer; do not start a second DB owner.
    remote = TestClient(main.app, base_url="http://127.0.0.1:8787", client=("192.0.2.5", 50000))
    try:
        assert remote.post("/api/mindlink/start", json={"consent": True}).status_code == 403
    finally:
        remote.close()
    assert client.post("/api/mindlink/start", headers={"Origin": "http://127.0.0.1:8787"}, json={"consent": True}).status_code == 200


def test_no_arbitrary_url_and_strict_consent(client, monkeypatch):
    monkeypatch.setattr(mindlink, "read_attention", lambda **kwargs: pytest.fail("unexpected read"))
    assert client.post("/api/mindlink/start", json={"consent": True, "url": "http://example.test"}).status_code == 422
    assert client.post("/api/mindlink/start", json={"consent": "true"}).status_code == 422
    token = client.post("/api/mindlink/start", json={"consent": True}).json()["token"]
    headers = {"X-MindLink-Token": token}
    assert client.post("/api/mindlink/state", headers=headers, json={"url": "http://example.test"}).status_code == 422
    assert client.post("/api/mindlink/stop", headers=headers, json={"url": "http://example.test"}).status_code == 422


def test_expired_token_cannot_read(client, monkeypatch):
    monkeypatch.setattr(mindlink, "read_attention", lambda **kwargs: pytest.fail("expired token read"))
    token = client.post("/api/mindlink/start", json={"consent": True}).json()["token"]
    with main._mindlink_lock:
        main._mindlink_grants[token] = 0
    assert client.post("/api/mindlink/state", headers={"X-MindLink-Token": token}).status_code == 403


def test_stop_during_inflight_read_discards_result(client, monkeypatch):
    started, release = threading.Event(), threading.Event()
    def wait_read(**kwargs):
        started.set()
        assert release.wait(3)
        return {"available": True, "score": 90}
    monkeypatch.setattr(mindlink, "read_attention", wait_read)
    token = client.post("/api/mindlink/start", json={"consent": True}).json()["token"]
    headers = {"X-MindLink-Token": token}
    responses = []
    thread = threading.Thread(target=lambda: responses.append(client.post("/api/mindlink/state", headers=headers)))
    thread.start()
    try:
        assert started.wait(3)
        assert client.post("/api/mindlink/stop", headers=headers).status_code == 200
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert responses[0].status_code == 403
    assert "90" not in responses[0].text
