"""Fault injection is a test helper, not an externally writable product API."""
import pytest
from fastapi.testclient import TestClient

from server import core, faults
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    core.init_db()
    faults.clear()
    yield TestClient(app)
    faults.clear()


def test_model_timeout_returns_failed(client):
    sid = client.post("/api/session", json={"mode": "empty"}).json()["session"]["id"]
    faults.set_faults("model_timeout", True)
    result = client.post("/api/chat", json={"session_id": sid, "text": "你在吗"})
    assert result.status_code == 200
    assert result.json()["state"] == "failed" and result.json()["error"] == "model_timeout"
    events = client.get(f"/api/audit?session_id={sid}").json()["events"]
    assert any(event["action"] == "model.timeout" for event in events)


def test_device_stall_unit_contract(client):
    faults.set_faults("device_stall", True)
    core.device_start()
    try:
        frame = core.device_frame()
        assert frame["status"] == "stalled" and frame["abstain"] is True
        assert "未知" in frame["reason"] or "断流" in frame["reason"]
    finally:
        core.device_stop()
        faults.clear()


def test_lark_auth_fault_is_only_injected_inside_test(client):
    faults.set_faults("lark_auth", True)
    result = client.post("/api/lark/preview", json={"url": "https://example.feishu.cn/docx/x"})
    assert result.json()["ok"] is False and "演练" in result.json()["error"]
    faults.clear()
    assert faults.get_faults() == {"model_timeout": False, "device_stall": False, "lark_auth": False}
    assert client.post("/api/debug/faults", json={"kind": "lark_auth", "enabled": True}).status_code == 410
    assert faults.active("lark_auth") is False
