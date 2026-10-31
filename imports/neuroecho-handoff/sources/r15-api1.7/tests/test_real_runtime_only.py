"""Production routes never promote examples or generated device ACKs to data.

Tests use isolated databases and tripwires; no accounts, credentials, devices,
network requests or production settings are accessed.
"""
import pytest
from fastapi.testclient import TestClient

from server import core, main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "real-runtime.db"))
    core.init_db()
    return TestClient(main.app)


RETIRED = [
    ("GET", "/api/onboarding/catalog", None),
    ("POST", "/api/onboarding/recommend", {"scenario": "work"}),
    ("POST", "/api/onboarding/read", {"connector_id": "feishu"}),
    ("POST", "/api/onboarding/start", {"connector_id": "feishu"}),
    ("POST", "/api/device/button", {"session_id": "unused"}),
    ("POST", "/api/device/display", {"session_id": "unused", "text": "unused"}),
    ("POST", "/api/device/start", None),
    ("POST", "/api/device/stop", None),
    ("GET", "/api/device/frame", None),
    ("GET", "/api/device/presentation", None),
    ("GET", "/api/debug/faults", None),
    ("POST", "/api/debug/faults", {"kind": "model_timeout", "enabled": True}),
    ("POST", "/api/debug/faults/clear", None),
    ("POST", "/api/auth/lark/setup", None),
]


@pytest.mark.parametrize("method,path,body", RETIRED)
def test_retired_routes_do_not_invoke_adapters_or_change_data(client, monkeypatch, method, path, body):
    def forbidden(*args, **kwargs):
        pytest.fail("A retired route invoked a data, device or credential operation")
    for module, functions in (
        (main.connectors, ("catalog", "recommend", "read", "greeting")),
        (main.device_bridge, ("button_press", "display", "state")),
        (main.faults, ("get_faults", "set_faults", "clear")),
        (main.lark_auth, ("setup_keychain",)),
        (core, ("create_session", "device_start", "device_stop", "device_frame", "audit")),
    ):
        for name in functions:
            monkeypatch.setattr(module, name, forbidden)
    response = client.request(method, path + "?demo=1&debug=1", json=body)
    assert response.status_code == 410
    assert response.json()["error_code"] in ("demo_unavailable", "credential_storage_change_disabled")
    assert "items" not in response.json() and "ack" not in response.json()
    assert core.list_sessions() == []


@pytest.mark.parametrize("body,code", [
    ({"mode": "sample"}, 410),
    ({"mode": "sample", "text": "即使有输入，也不能启用样例"}, 410),
    ({"mode": "paste", "text": ""}, 422),
    ({"mode": "paste", "text": "   "}, 422),
])
def test_session_rejects_sample_and_empty_paste_without_persistence(client, monkeypatch, body, code):
    monkeypatch.setenv("XINJI_DEMO", "1")
    monkeypatch.setenv("XINJI_ALLOW_DEMO", "true")
    monkeypatch.setattr(core, "create_session", lambda *a, **k: pytest.fail("rejected session was persisted"))
    response = client.post("/api/session?demo=1", json=body)
    assert response.status_code == code
    assert core.list_sessions() == []


def test_empty_and_explicit_paste_remain_available(client):
    empty = client.post("/api/session", json={"mode": "empty"})
    assert empty.status_code == 200
    assert empty.json()["memories"] == []
    text = "我今天明确选择了这段测试资料。"
    pasted = client.post("/api/session", json={"mode": "paste", "text": text})
    assert pasted.status_code == 200
    assert any(item["kind"] == "fact" and item["text"] == text.rstrip("。")
               for item in pasted.json()["memories"])
    assert all("下周需要给团队看原型" not in item["text"] for item in pasted.json()["memories"])


def test_diagnostics_do_not_claim_simulation_or_connector_success(client, monkeypatch):
    monkeypatch.setattr(main.model, "status", lambda: {"configured": False})
    for path in ("/api/health", "/api/config"):
        value = client.get(path).json()
        assert value["demo_available"] is False
        assert "synthetic" not in value
        assert "connected" not in value


def test_real_catalog_remains_available_without_enabling_legacy_routes(client, monkeypatch):
    rows = [{"id": "local_files", "name": "本地文件", "status": "ready", "mode": "real"}]
    monkeypatch.setattr(main.real_sources, "sources", lambda force=False: rows)
    response = client.get("/api/onboarding/sources")
    assert response.status_code == 200
    assert response.json()["sources"][0]["id"] == "local_files"
