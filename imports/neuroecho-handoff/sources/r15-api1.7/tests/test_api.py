"""验收用例（对应 PRD 11 / acceptance.json 的核心 P0）。"""
import pytest
from fastapi.testclient import TestClient

from server import core
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    core.init_db()
    return TestClient(app)


def new_session(client, mode="sample", text=""):
    r = client.post("/api/session", json={"mode": mode, "text": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_health(client):
    r = client.get("/api/health")
    assert r.json()["ok"] is True
    assert r.json()["synthetic"] is True


def test_session_understanding_split(client):
    d = new_session(client)
    kinds = [m["kind"] for m in d["memories"]]
    assert kinds.count("fact") == 3
    assert kinds.count("inference") == 2
    assert kinds.count("question") == 1
    assert d["session"]["source_label"] == "示例资料"


def test_chat_memory_and_correction(client):
    d = new_session(client)
    sid = d["session"]["id"]
    r = client.post("/api/chat", json={"session_id": sid, "text": "记住：我下周要给团队看原型"})
    assert r.status_code == 200
    mems = r.json()["memories"]
    assert any(m["status"] == "candidate" and "团队" in m["text"] for m in mems)

    mem = [m for m in mems if "团队" in m["text"]][0]
    r = client.patch(f"/api/memory/{mem['id']}", json={"text": "我下周要给团队看原型（已确认）", "status": "confirmed"})
    assert r.status_code == 200
    assert r.json()["version"] == mem["version"] + 1
    assert r.json()["status"] == "confirmed"


def test_bookmark_commit_receipt(client):
    sid = new_session(client)["session"]["id"]
    r = client.post("/api/bookmark", json={"session_id": sid, "note": "整理原型", "choice": "先做最小闭环", "next_step": "给团队看"})
    bid = r.json()["id"]
    assert r.json()["status"] == "draft"
    r = client.post(f"/api/bookmark/{bid}/commit")
    assert r.status_code == 200
    assert r.json()["status"] == "committed"
    assert r.json()["receipt"].startswith("stored:")


def test_device_contract_and_abstain(client):
    client.post("/api/device/start")
    f = client.get("/api/device/frame").json()
    assert f["source"] == "synthetic"
    assert f["status"] == "on"
    assert 0 <= f["quality"] <= 1
    assert f["abstain"] == (f["quality"] < core.THRESHOLDS["quality_min"])
    assert {"ts", "seq", "algo_version"} <= set(f)
    client.post("/api/device/stop")
    assert client.get("/api/device/frame").json()["status"] == "off"


def test_export_and_audit(client):
    sid = new_session(client)["session"]["id"]
    client.post("/api/chat", json={"session_id": sid, "text": "下一步怎么走"})
    data = client.get(f"/api/export?session_id={sid}").json()
    assert set(["sessions", "messages", "memories", "bookmarks", "audit"]) <= set(data)
    audit = client.get(f"/api/audit?session_id={sid}").json()["events"]
    assert any(e["action"] == "chat.turn" for e in audit)


def test_revoke_source_cleans_derived(client):
    sid = new_session(client)["session"]["id"]
    r = client.post("/api/source/revoke", json={"session_id": sid})
    assert r.status_code == 200
    assert r.json()["cleaned"] >= 6
    assert client.get(f"/api/memory?session_id={sid}").json()["memories"] == []
    assert client.get(f"/api/session/{sid}").json()["session"]["state"] == "revoked"


def test_budget_limit(client, monkeypatch):
    sid = new_session(client)["session"]["id"]
    monkeypatch.setattr(core, "CHAT_BUDGET", 1)
    assert client.post("/api/chat", json={"session_id": sid, "text": "一"}).status_code == 200
    r = client.post("/api/chat", json={"session_id": sid, "text": "二"})
    assert r.status_code == 429


def test_next_step_reflects_correction(client):
    sid = new_session(client)["session"]["id"]
    before = client.get(f"/api/next-step?session_id={sid}").json()
    assert before["step"]
    mem = client.get(f"/api/memory?session_id={sid}").json()["memories"][0]
    client.patch(f"/api/memory/{mem['id']}", json={"text": "把记忆做成一次确认交互", "status": "confirmed"})
    after = client.get(f"/api/next-step?session_id={sid}").json()
    assert after["changed_by_version"] > before["changed_by_version"] or after["step"] != before["step"]
