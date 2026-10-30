"""删除本次会话：派生数据全部清理。"""
import pytest
from fastapi.testclient import TestClient

from server import core
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    core.init_db()
    return TestClient(app)


def test_delete_session_cleans_everything(client):
    d = client.post("/api/session", json={"mode": "sample"}).json()
    sid = d["session"]["id"]
    client.post("/api/chat", json={"session_id": sid, "text": "记住：测试"})
    b = client.post("/api/bookmark", json={"session_id": sid, "note": "n"}).json()
    client.post(f"/api/bookmark/{b['id']}/commit")
    client.post("/api/action", json={"session_id": sid, "kind": "reminder", "title": "t"})

    r = client.delete(f"/api/session/{sid}")
    assert r.status_code == 200 and r.json()["ok"] is True

    assert client.get(f"/api/session/{sid}").status_code == 404
    assert client.get(f"/api/memory?session_id={sid}").json()["memories"] == []
    assert client.get(f"/api/actions?session_id={sid}").json()["actions"] == []
    assert client.get(f"/api/audit?session_id={sid}").json()["events"] == []
