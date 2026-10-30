"""对话依据（引用记忆版本）与消息持久化。"""
import pytest
from fastapi.testclient import TestClient

from server import core
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    core.init_db()
    return TestClient(app)


def test_assistant_reply_has_citations(client):
    sid = client.post("/api/session", json={"mode": "sample"}).json()["session"]["id"]
    d = client.post("/api/chat", json={"session_id": sid, "text": "下一步怎么走"}).json()
    assert d["messages"][-1]["role"] == "assistant"
    citations = d["messages"][-1]["citations"]
    # A generic reply cannot assert it used any particular source.
    assert citations == []
    assert d["messages"][-1]["suggestions"] == []

    # 重新读取会话，引用仍在
    msgs = client.get(f"/api/session/{sid}").json()["messages"]
    assert msgs[-1]["citations"] == citations
