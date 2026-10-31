"""macOS 真实连接器：提醒事项 / 日历（osascript 只读，失败不伪造数据）。"""
import pytest
from fastapi.testclient import TestClient

from server import apple_source, core
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # These tests replace osascript output; explicitly simulate Mac on any host.
    monkeypatch.setattr(apple_source, "platform_supported", lambda: True)
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    core.init_db()
    return TestClient(app)


def test_reminders_real_read(client, monkeypatch):
    monkeypatch.setattr(apple_source, "_run", lambda script: "给团队发演示脚本||工作\n预约牙医||个人\n")
    r = client.post("/api/onboarding/read", json={"connector_id": "apple_reminders"}).json()
    assert r["ok"] is True and r["synthetic"] is False
    assert len(r["items"]) == 2
    assert r["source"] == "macos"

    s = client.post("/api/onboarding/start", json={"connector_id": "apple_reminders"}).json()
    assert s["session"]["source_label"] == "提醒事项 · 只读"


def test_reminders_permission_error_never_falls_back_to_demo(client, monkeypatch):
    def boom(script):
        raise RuntimeError("Not authorized to send Apple events to Reminders")
    monkeypatch.setattr(apple_source, "_run", boom)
    r = client.post("/api/onboarding/read", json={"connector_id": "apple_reminders"}).json()
    assert r["ok"] is False and "无法读取" in r["error"]
    assert "items" not in r and "synthetic" not in r
    result = client.post("/api/onboarding/start", json={"connector_id": "apple_reminders"})
    assert result.status_code == 400
    assert core.list_sessions() == []


def test_real_apple_greeting_uses_selected_item_without_demo_claims(client, monkeypatch):
    monkeypatch.setattr(apple_source, "_run", lambda script: "合成的散步提醒||个人\n")
    result = client.post("/api/onboarding/start", json={"connector_id": "apple_reminders"}).json()
    greeting = result["messages"][0]["text"]
    assert "合成的散步提醒" in greeting
    assert "演示" not in greeting and "两条承诺悬着" not in greeting
    assert result["context"]["items"][0]["title"] == "合成的散步提醒"


def test_calendar_real_read(client, monkeypatch):
    monkeypatch.setattr(apple_source, "_run", lambda script: "周三 15:00 团队演示||2026-10-29 15:00||工作\n")
    r = client.post("/api/onboarding/read", json={"connector_id": "apple_calendar"}).json()
    assert r["ok"] is True and len(r["items"]) == 1
    assert "演示" in r["items"][0]["title"]
    assert "工作" in r["items"][0]["meta"]


def test_calendar_without_time_does_not_turn_calendar_name_into_title():
    items = apple_source._items(["   || 2026-10-29 || 工作", "示例日程||||工作"], "日程")
    assert len(items) == 1
    assert items[0]["title"] == "示例日程"
    assert items[0]["meta"] == "工作"


def test_real_apple_read_failure_is_not_reported_as_empty(client, monkeypatch):
    def denied(script):
        raise RuntimeError("synthetic-private-apple-error")
    monkeypatch.setattr(apple_source, "_run", denied)
    result = client.post("/api/onboarding/real/read", json={"source_id": "apple_calendar"}).json()
    assert result["ok"] is False and "无法读取" in result["error"]
    assert "synthetic" not in result
    assert "synthetic-private" not in repr(result)
