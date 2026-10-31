"""指标面板（PRD 11：先验收工程，再验证用户价值）。"""
import pytest
from fastapi.testclient import TestClient

from server import core
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    core.init_db()
    return TestClient(app)


def test_metrics_counts_actions(client):
    sid = client.post("/api/session", json={"mode": "paste", "text": "测试项目正在整理交互原型。测试团队准备下一轮演示。测试资料记录当前计划。测试选择先确认范围。测试安排稍后核对记录。"}).json()["session"]["id"]
    mems = client.get(f"/api/memory?session_id={sid}").json()["memories"]
    client.patch(f"/api/memory/{mems[0]['id']}", json={"text": "纠正后的理解", "status": "confirmed"})
    b = client.post("/api/bookmark", json={"session_id": sid, "note": "n", "choice": "c", "next_step": "s"}).json()
    client.post(f"/api/bookmark/{b['id']}/commit")
    assert client.post("/api/device/start").status_code == 410
    assert client.get("/api/device/frame").status_code == 410
    assert client.post("/api/device/stop").status_code == 410

    m = client.get(f"/api/metrics?session_id={sid}").json()
    assert m["sessions"] == 1
    assert m["messages"] >= 1
    assert m["memories"]["confirmed"] == 1
    assert m["corrections"] == 1
    assert m["bookmarks"]["committed"] == 1
    assert m["device"]["starts"] == 0 and m["device"]["stops"] == 0
    assert m["rates"]["confirm"] > 0
    assert m["rates"]["bookmark"] == 1.0


def test_metrics_global_and_empty(client):
    m = client.get("/api/metrics").json()
    assert m["sessions"] == 0 and m["rates"]["confirm"] == 0
