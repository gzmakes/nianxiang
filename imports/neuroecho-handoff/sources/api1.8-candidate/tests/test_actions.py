"""洞察 → 动作（提醒/日历）：预览、确认、回执（PRD F11/F12）。"""
import pytest
from fastapi.testclient import TestClient

from server import core
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    core.init_db()
    return TestClient(app)


def test_action_preview_then_commit(client):
    sid = client.post("/api/session", json={"mode": "sample"}).json()["session"]["id"]
    d = client.post("/api/action", json={"session_id": sid, "kind": "reminder", "title": "演示前彩排", "detail": "周三 15:00"}).json()
    assert d["status"] == "previewed"
    done = client.post(f"/api/action/{d['id']}/commit").json()
    assert done["status"] == "committed" and done["receipt"].startswith("reminder:")
    actions = client.get(f"/api/actions?session_id={sid}").json()["actions"]
    assert len(actions) == 1 and actions[0]["status"] == "committed"


def test_bad_action_kind(client):
    sid = client.post("/api/session", json={"mode": "sample"}).json()["session"]["id"]
    r = client.post("/api/action", json={"session_id": sid, "kind": "email", "title": "x"})
    assert r.status_code == 400


def test_message_draft_is_not_sent(client):
    sid = client.post("/api/session", json={"mode": "sample"}).json()["session"]["id"]
    d = client.post("/api/action", json={"session_id": sid, "kind": "message",
                                          "title": "回复邮件", "detail": "收到，今晚给进展"}).json()
    done = client.post(f"/api/action/{d['id']}/commit").json()
    assert done["status"] == "committed"
    assert done["receipt"].startswith("message:")
    assert done["real"] == 0


def test_bookmark_keeps_source_and_version(client):
    sid = client.post("/api/session", json={"mode": "sample"}).json()["session"]["id"]
    b = client.post("/api/bookmark", json={
        "session_id": sid, "note": "停在这一段", "choice": "保留取舍", "next_step": "先写开头",
        "source_memory_id": "mem_1", "source_version": 3,
        "source_label": "飞书 · 演示读取", "source_quote": "交互原型 v3 卡在上下文",
    }).json()
    assert b["source_memory_id"] == "mem_1" and b["source_version"] == 3
    got = client.get(f"/api/bookmark/latest?session_id={sid}").json()["bookmark"]
    assert got["source_quote"].startswith("交互原型 v3")
