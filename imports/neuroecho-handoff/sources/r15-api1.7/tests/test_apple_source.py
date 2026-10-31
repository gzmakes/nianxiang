"""macOS 真实连接器：提醒事项 / 日历（osascript 只读，失败不伪造数据）。"""
import pytest
import subprocess
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
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
    r = client.post("/api/onboarding/real/read", json={"source_id": "apple_reminders"}).json()
    assert r["ok"] is True and r["synthetic"] is False
    assert len(r["items"]) == 2
    assert r["source"] == "macos"

    s = client.post("/api/onboarding/real/start", json={"source_id": "apple_reminders", "preview_id": r["preview_id"]}).json()
    assert s["session"]["source_label"] == "提醒事项 · 已连接"


def test_reminders_permission_error_never_falls_back_to_demo(client, monkeypatch):
    def boom(script):
        raise RuntimeError("Not authorized to send Apple events to Reminders")
    monkeypatch.setattr(apple_source, "_run", boom)
    r = client.post("/api/onboarding/real/read", json={"source_id": "apple_reminders"}).json()
    assert r["ok"] is False and "无法读取" in r["error"]
    assert "items" not in r and "synthetic" not in r
    result = client.post("/api/onboarding/real/start", json={"source_id": "apple_reminders", "preview_id": "never-created"})
    assert result.status_code == 400
    assert core.list_sessions() == []


def test_real_apple_greeting_does_not_invent_demo_claims(client, monkeypatch):
    monkeypatch.setattr(apple_source, "_run", lambda script: "合成的散步提醒||个人\n")
    preview = client.post("/api/onboarding/real/read", json={"source_id": "apple_reminders"}).json()
    result = client.post("/api/onboarding/real/start", json={"source_id": "apple_reminders", "preview_id": preview["preview_id"]}).json()
    greeting = result["messages"][0]["text"]
    assert "你选的这些记录" in greeting
    assert "演示" not in greeting and "两条承诺悬着" not in greeting
    assert result["context"]["items"][0]["title"] == "合成的散步提醒"


def test_calendar_real_read(client, monkeypatch):
    monkeypatch.setattr(apple_source, "_run", lambda script: "周三 15:00 团队演示||2026-10-29 15:00||工作\n")
    r = client.post("/api/onboarding/real/read", json={"source_id": "apple_calendar"}).json()
    assert r["ok"] is True and len(r["items"]) == 1
    assert "演示" in r["items"][0]["title"]
    assert "工作" in r["items"][0]["meta"]


def test_calendar_without_time_does_not_turn_calendar_name_into_title():
    items = apple_source._items(["   || 2026-10-29 || 工作", "示例日程||||工作"], "日程")
    assert len(items) == 2
    assert items[0]["title"] == "未命名日程"
    assert items[0]["meta"] == "2026-10-29 · 工作"
    assert items[1]["title"] == "示例日程"
    assert items[1]["meta"] == "工作"


def test_real_apple_read_failure_is_not_reported_as_empty(client, monkeypatch):
    def denied(script):
        raise RuntimeError("synthetic-private-apple-error")
    monkeypatch.setattr(apple_source, "_run", denied)
    result = client.post("/api/onboarding/real/read", json={"source_id": "apple_calendar"}).json()
    assert result["ok"] is False and "无法读取" in result["error"]
    assert "synthetic" not in result
    assert "synthetic-private" not in repr(result)


@pytest.mark.parametrize("source_id", ["apple_reminders", "apple_calendar"])
def test_empty_apple_read_is_a_real_empty_result(client, monkeypatch, source_id):
    monkeypatch.setattr(apple_source, "_run", lambda script: "")
    result = client.post("/api/onboarding/real/read", json={"source_id": source_id}).json()
    assert result["ok"] is True
    assert result["items"] == []
    assert result["synthetic"] is False
    assert result["source"] == "macos"
    assert result["preview_id"]
    fact, = result["understanding"]["facts"]
    assert result["read_at"] in fact and "0 条" in fact
    assert ("未完成提醒" if source_id == "apple_reminders" else "未来 7 天") in fact
    assert result["insights"] == []


@pytest.mark.parametrize("error,code", [
    ("application isn't running (-600)", "app_not_running"),
    ("Not authorized to send Apple events (-1743)", "automation_denied"),
    ("synthetic private details", "read_failed"),
])
def test_apple_error_classification_does_not_expose_stderr(monkeypatch, error, code):
    monkeypatch.setattr(apple_source, "_run", lambda script: (_ for _ in ()).throw(RuntimeError(error)))
    monkeypatch.setattr(apple_source.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 1))
    result = apple_source.read_calendar()
    assert result["ok"] is False and result["error_code"] == code
    assert error not in repr(result)


def test_apple_start_retries_only_app_not_running(monkeypatch):
    calls = []
    def run(script):
        calls.append("read")
        if len(calls) == 1:
            raise RuntimeError("application isn't running (-600)")
        return "测试日程||明天||合成日历\n"
    def launch(args, **kwargs):
        calls.append(tuple(args))
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(apple_source, "_run", run)
    monkeypatch.setattr(apple_source.subprocess, "run", launch)
    result = apple_source.read_calendar()
    assert result["ok"] is True
    assert calls == ["read", ("/usr/bin/open", "-g", "-b", "com.apple.iCal"), "read"]


def test_apple_timeout_is_not_reported_as_permission_denial(monkeypatch):
    def timeout(script):
        raise subprocess.TimeoutExpired("osascript", apple_source.TIMEOUT)
    monkeypatch.setattr(apple_source, "_run", timeout)
    result = apple_source.read_reminders()
    assert result["error_code"] == "read_timeout"
    assert result["ok"] is False


def test_apple_read_timeout_has_room_for_slow_calendar(monkeypatch):
    calls = []
    def fake_run(args, **kwargs):
        calls.append(kwargs["timeout"])
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
    monkeypatch.setattr(apple_source.subprocess, "run", fake_run)
    assert apple_source.read_calendar()["ok"] is True
    assert calls == [45]


@pytest.mark.parametrize("reader,placeholder", [("read_calendar", "未命名日程"), ("read_reminders", "未命名提醒")])
def test_empty_title_is_preserved_as_an_unnamed_item(monkeypatch, reader, placeholder):
    monkeypatch.setattr(apple_source, "_run", lambda _: " || 合成列表\n")
    result = getattr(apple_source, reader)()
    assert result["ok"] is True
    assert len(result["items"]) == 1
    assert result["items"][0]["title"] == placeholder
    assert result["items"][0]["meta"] == "合成列表"
    assert not any("0 条" in fact for fact in result["understanding"]["facts"])


def test_permission_denial_never_attempts_to_launch_app(monkeypatch):
    monkeypatch.setattr(apple_source, "_run", lambda script: (_ for _ in ()).throw(RuntimeError("(-1743)")))
    def forbidden_launch(*args, **kwargs):
        raise AssertionError("must not launch app for permission error")
    monkeypatch.setattr(apple_source.subprocess, "run", forbidden_launch)
    assert apple_source.read_calendar()["error_code"] == "automation_denied"


@pytest.mark.parametrize("reader,field,label", [
    ("read_calendar_recent", "start_at", "过去 7 天开始的日程"),
    ("read_reminders_recent", "modified_at", "过去 7 天修改过的提醒"),
])
def test_recent_window_reads_past_seven_days_and_preserves_scope(monkeypatch, reader, field, label):
    clock = datetime(2026, 10, 31, 10, 0).astimezone()
    recent = clock - timedelta(days=1)
    stale = clock - timedelta(days=8)
    scripts = []
    def run(script):
        scripts.append(script)
        return (f"合成近期事项||{int(recent.timestamp())}||合成列表||已完成\n"
                f"合成旧事项||{int(stale.timestamp())}||合成列表||未完成\n")
    monkeypatch.setattr(apple_source, "_run", run)
    result = getattr(apple_source, reader)(now=clock)
    assert result["ok"] and result["read_window"] == "recent7"
    assert len(result["items"]) == 1 and result["items"][0]["title"] == "合成近期事项"
    assert result["items"][0][field] == recent.isoformat(timespec="seconds")
    assert result["items"][0]["read_scope"] == result["scope"]
    assert result["scope"]["since"] == (clock-timedelta(days=7)).isoformat(timespec="seconds")
    assert label in result["scope"]["label"] and "未来" not in repr(result)
    assert "windowStart" in scripts[0] and "windowEnd" in scripts[0]
    if reader == "read_reminders_recent":
        assert "modification date" in scripts[0] and result["items"][0]["completed"] is True


@pytest.mark.parametrize("reader", ["read_calendar_recent", "read_reminders_recent"])
def test_recent_zero_result_is_truthful_and_retains_date_scope(monkeypatch, reader):
    monkeypatch.setattr(apple_source, "_run", lambda _: "")
    result = getattr(apple_source, reader)()
    assert result["ok"] and result["items"] == [] and result["synthetic"] is False
    assert result["scope"]["kind"] == "last_7_days" and result["insights"] == []
    assert "0 条" in result["understanding"]["facts"][0]
    assert "过去 7 天" in result["understanding"]["facts"][0]
    assert "未来" not in repr(result)
    assert result["scope"]["since"] in result["text"] and result["scope"]["until"] in result["text"]


def test_recent_invalid_timestamp_is_failure_not_empty(monkeypatch):
    monkeypatch.setattr(apple_source, "_run", lambda _: "合成事项||没有可靠日期||合成列表\n")
    result = apple_source.read_calendar_recent()
    assert not result["ok"] and result["error_code"] == "unreadable_results"


def test_default_calendar_keeps_future_window_for_legacy_callers(monkeypatch):
    seen = []
    monkeypatch.setattr(apple_source, "_run", lambda script: seen.append(script) or "")
    result = apple_source.read_calendar()
    assert result["ok"] and "未来 7 天" in repr(result)
    assert "set later to now + 7 * days" in seen[0] and "windowStart" not in seen[0]


@pytest.mark.parametrize("clock,inside", [
    (datetime(2027, 3, 16, 10, tzinfo=ZoneInfo("America/New_York")),
     datetime(2027, 3, 9, 9, 30, tzinfo=ZoneInfo("America/New_York"))),
    (datetime(2027, 11, 9, 1, 30, tzinfo=ZoneInfo("America/New_York")),
     datetime(2027, 11, 2, 3, 0, tzinfo=ZoneInfo("America/New_York"))),
])
def test_recent_epoch_window_matches_declared_scope_across_daylight_saving(monkeypatch, clock, inside):
    previous_tz = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    time.tzset()
    scripts = []
    try:
        outside = int(clock.timestamp())-7*24*3600-1800
        monkeypatch.setattr(apple_source, "_run", lambda script: scripts.append(script) or
                            f"合成 DST 范围事项||{int(inside.timestamp())}||合成列表\n合成窗口外||{outside}||合成列表\n")
        result = apple_source.read_calendar_recent(now=clock)
        start = datetime.fromisoformat(result["scope"]["since"])
        end = datetime.fromisoformat(result["scope"]["until"])
        assert end.astimezone(timezone.utc)-start.astimezone(timezone.utc) == timedelta(days=7)
        assert int(start.timestamp()) == int(end.timestamp())-7*24*3600
        assert f"({int(start.timestamp())} - unixAfter)" in scripts[0]
        assert f"({int(end.timestamp())} - unixAfter)" in scripts[0]
        assert len(result["items"]) == 1
        assert datetime.fromisoformat(result["items"][0]["start_at"]).timestamp() == inside.timestamp()
        assert "set year" not in scripts[0] and "epochText" in scripts[0]
    finally:
        if previous_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous_tz
        time.tzset()
