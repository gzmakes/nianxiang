"""实体交互与 ACK（PRD F03/F06/F12/F18）。"""
import pytest
from fastapi.testclient import TestClient

from server import core
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    core.init_db()
    return TestClient(app)


def test_button_press_returns_ack(client):
    r = client.post("/api/device/button", json={"session_id": "ses_test"})
    assert r.status_code == 200
    d = r.json()
    assert d["type"] == "button.press" and d["source"] == "synthetic-button"
    assert d["ack"]["status"] == "received"
    assert d["ack"]["for"] == d["id"]


def test_display_command_has_ack_and_state(client):
    r = client.post("/api/device/display", json={"session_id": "ses_test", "text": "已保存：测试", "color": "amber"})
    assert r.status_code == 200
    d = r.json()
    assert d["ack"]["status"] == "displayed"
    assert d["ack"]["latency_ms"] > 0
    state = client.get("/api/device/presentation").json()
    assert state["last_display"]["id"] == d["id"]
    assert state["synthetic"] is True


def test_device_actions_audited(client):
    client.post("/api/device/button", json={"session_id": "ses_audit"})
    client.post("/api/device/display", json={"session_id": "ses_audit", "text": "hi"})
    events = client.get("/api/audit?session_id=ses_audit").json()["events"]
    actions = [e["action"] for e in events]
    assert "device.button" in actions and "device.display" in actions
