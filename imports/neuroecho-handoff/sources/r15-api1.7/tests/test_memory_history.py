"""记忆版本历史（PRD F09：确认、来源、版本、可纠正）。"""
import pytest
from fastapi.testclient import TestClient

from server import core
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    core.init_db()
    return TestClient(app)


def test_history_records_each_correction(client):
    sid = client.post("/api/session", json={"mode": "paste", "text": "测试项目正在整理交互原型。测试团队准备下一轮演示。测试资料记录当前计划。测试选择先确认范围。测试安排稍后核对记录。"}).json()["session"]["id"]
    mem = client.get(f"/api/memory?session_id={sid}").json()["memories"][0]
    h = client.get(f"/api/memory/{mem['id']}/history").json()["revisions"]
    assert len(h) == 1 and h[0]["version"] == 1

    client.patch(f"/api/memory/{mem['id']}", json={"text": "第一次纠正", "status": "confirmed"})
    client.patch(f"/api/memory/{mem['id']}", json={"text": "第二次纠正"})
    h = client.get(f"/api/memory/{mem['id']}/history").json()["revisions"]
    assert [x["version"] for x in h] == [1, 2, 3]
    assert h[-1]["text"] == "第二次纠正"
    assert h[-1]["status"] == "confirmed"  # 状态保留


def test_history_deleted_with_memory(client):
    sid = client.post("/api/session", json={"mode": "paste", "text": "测试项目正在整理交互原型。测试团队准备下一轮演示。测试资料记录当前计划。测试选择先确认范围。测试安排稍后核对记录。"}).json()["session"]["id"]
    mem = client.get(f"/api/memory?session_id={sid}").json()["memories"][0]
    client.delete(f"/api/memory/{mem['id']}")
    assert client.get(f"/api/memory/{mem['id']}/history").json()["revisions"] == []


def test_export_includes_revisions(client):
    sid = client.post("/api/session", json={"mode": "paste", "text": "测试项目正在整理交互原型。测试团队准备下一轮演示。测试资料记录当前计划。测试选择先确认范围。测试安排稍后核对记录。"}).json()["session"]["id"]
    data = client.get(f"/api/export?session_id={sid}").json()
    assert "memory_revisions" in data and len(data["memory_revisions"]) >= 1
