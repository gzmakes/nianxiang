"""会话历史列表。"""
import pytest
from fastapi.testclient import TestClient

from server import core
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    core.init_db()
    return TestClient(app)


def test_list_sessions(client):
    a = client.post("/api/session", json={"mode": "sample"}).json()["session"]["id"]
    client.post("/api/chat", json={"session_id": a, "text": "记住：第一条"})
    b = client.post("/api/session", json={"mode": "sample"}).json()["session"]["id"]
    d = client.get("/api/sessions").json()["sessions"]
    assert len(d) == 2
    assert d[0]["id"] == b and d[1]["id"] == a
    assert d[1]["title"]
    assert d[1]["memories"] >= 1


def test_rename_session(client):
    sid = client.post("/api/session", json={"mode": "sample"}).json()["session"]["id"]
    r = client.patch(f"/api/session/{sid}", json={"title": "我的演示复盘"})
    assert r.status_code == 200 and r.json()["title"] == "我的演示复盘"
    d = client.get("/api/sessions").json()["sessions"]
    assert d[0]["id"] == sid and d[0]["title"] == "我的演示复盘"
