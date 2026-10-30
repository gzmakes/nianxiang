"""故障演练：failed/unknown 与降级（PRD F12/F13）。"""
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
    sid = client.post("/api/session", json={"mode": "sample"}).json()["session"]["id"]
    client.post("/api/debug/faults", json={"kind": "model_timeout", "enabled": True})
    r = client.post("/api/chat", json={"session_id": sid, "text": "你在吗"})
    assert r.status_code == 200
    d = r.json()
    assert d["state"] == "failed" and d["error"] == "model_timeout"
    audit = client.get(f"/api/audit?session_id={sid}").json()["events"]
    assert any(e["action"] == "model.timeout" for e in audit)


def test_device_stall_returns_unknown(client):
    client.post("/api/debug/faults", json={"kind": "device_stall", "enabled": True})
    client.post("/api/device/start")
    f = client.get("/api/device/frame").json()
    assert f["status"] == "stalled" and f["abstain"] is True
    assert "未知" in f["reason"] or "断流" in f["reason"]


def test_lark_auth_fault(client):
    client.post("/api/debug/faults", json={"kind": "lark_auth", "enabled": True})
    r = client.post("/api/lark/preview", json={"url": "https://example.feishu.cn/docx/x"})
    d = r.json()
    assert d["ok"] is False and "演练" in d["error"]
    client.post("/api/debug/faults/clear")
    assert client.get("/api/debug/faults").json() == {"model_timeout": False, "device_stall": False, "lark_auth": False}
