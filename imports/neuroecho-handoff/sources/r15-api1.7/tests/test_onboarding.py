"""Unknown connectors must not invent concrete source details in conversation."""
import pytest
from fastapi.testclient import TestClient

from server import core
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    core.init_db()
    return TestClient(app)


def test_connector_answers_do_not_invent_specific_details(client):
    cases = [
        ("notion", "三个方向先砍哪个？", "Q4 路线图"),
        ("linear", "这周只清一个高优，选哪个？", "记忆删除联动"),
        ("google_calendar", "演示前最需要谁反馈？", "1:1"),
    ]
    for cid, q, fabricated in cases:
        d = client.post("/api/session", json={"mode": "empty"}).json()
        sid = d["session"]["id"]
        core.set_session_context(sid, cid, [{"title": "真实的另一条记录", "summary": ""}], [])
        r = client.post("/api/chat", json={"session_id": sid, "text": q}).json()
        assert fabricated not in r["reply"], (cid, r["reply"])
        assert "还没有连接对话模型" in r["reply"]
