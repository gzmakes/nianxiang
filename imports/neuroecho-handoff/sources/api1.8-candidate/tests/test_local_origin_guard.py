"""Local guard regression checks; no real keychain operation or network."""
from fastapi.testclient import TestClient
from server import main


def test_cross_origin_cannot_invoke_sensitive_bodyless_post(monkeypatch):
    calls = []
    monkeypatch.setattr(main.lark_auth, "setup_keychain", lambda: calls.append(True) or {"ok": True})
    with TestClient(main.app, base_url="http://127.0.0.1:8787", client=("127.0.0.1", 12345)) as client:
        for headers in (
            {"Origin": "https://evil.example", "Content-Type": "text/plain"},
            {"Origin": "null", "Content-Type": "text/plain"},
            {"Sec-Fetch-Site": "cross-site"},
            {"Sec-Fetch-Site": "same-site"},
            {"Origin": "http://127.0.0.1:9999"},
        ):
            assert client.post("/api/auth/lark/setup", headers=headers).status_code == 403
        assert calls == []
        assert client.post("/api/auth/lark/setup", headers={"Origin": "http://127.0.0.1:8787", "Sec-Fetch-Site": "same-origin"}).status_code == 200
        assert client.post("/api/auth/lark/setup").status_code == 200
        assert calls == [True, True]


def test_host_peer_and_cross_site_get_are_rejected():
    with TestClient(main.app, base_url="http://127.0.0.1:8787", client=("127.0.0.1", 12345)) as local:
        assert local.get("/api/health").status_code == 200
        assert local.get("/api/health", headers={"Host": "evil.example:8787"}).status_code == 403
        assert local.get("/api/health", headers={"Host": "testserver"}).status_code == 403
        assert local.get("/api/health", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    with TestClient(main.app, base_url="http://127.0.0.1:8787", client=("192.0.2.5", 12345)) as remote:
        assert remote.get("/api/health").status_code == 403
    with TestClient(main.app) as test_client:
        assert test_client.get("/api/health").status_code == 200
