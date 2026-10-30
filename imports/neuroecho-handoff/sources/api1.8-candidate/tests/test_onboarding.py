"""Onboarding：场景推荐 → 读取 → 洞察 → 对话（PRD 19/20）。"""
import pytest
from fastapi.testclient import TestClient

from server import core
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    core.init_db()
    return TestClient(app)


def test_catalog_and_recommend(client):
    cat = client.get("/api/onboarding/catalog").json()
    assert len(cat["scenarios"]) == 4
    assert len(cat["connectors"]) >= 10

    r = client.post("/api/onboarding/recommend", json={"scenario": "work"}).json()
    assert len(r["items"]) >= 3
    assert r["items"][0]["connector"]["id"] == "feishu"
    assert r["items"][0]["recommended"] is True


def test_read_preview_has_boundary(client):
    r = client.post("/api/onboarding/read", json={"connector_id": "feishu"}).json()
    assert r["ok"] and r["synthetic"] is True
    assert len(r["items"]) == 3
    assert len(r["insights"]) == 3
    assert r["connector"]["scopes"]
    assert "facts" in r["understanding"]


def test_start_creates_grounded_session(client):
    r = client.post("/api/onboarding/start", json={"connector_id": "feishu", "scenario": "work"}).json()
    sid = r["session"]["id"]
    assert r["session"]["source_label"] == "飞书 · 演示读取"
    assert r["messages"][-1]["role"] == "assistant"
    assert "飞书" in r["messages"][-1]["text"]
    assert any("洞察" in m["text"] for m in r["memories"])
    audit = client.get(f"/api/audit?session_id={sid}").json()["events"]
    assert any(e["action"] == "connector.read" for e in audit)


def test_context_grounded_reply(client):
    r = client.post("/api/onboarding/start", json={"connector_id": "feishu", "scenario": "work"}).json()
    sid = r["session"]["id"]
    assert r["context"]["connector_id"] == "feishu"
    assert len(r["context"]["insights"]) == 3
    assert len(r["context"]["starters"]) == 3

    d = client.post("/api/chat", json={"session_id": sid, "text": "下一步怎么办"}).json()
    assert d["action"] == "context.reply"
    assert "飞书" in d["reply"] or "候选下一步" in d["reply"]

    w = client.post("/api/chat", json={"session_id": sid, "text": "依据是什么"}).json()
    assert "3 条读取" in w["reply"] or "推测" in w["reply"]

    sess = client.get(f"/api/session/{sid}").json()
    assert sess["context"]["connector_id"] == "feishu"


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
