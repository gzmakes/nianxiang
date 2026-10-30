"""Synthetic UTC budget windows never retire or delete the persistent chat."""
import pytest
from fastapi.testclient import TestClient

from server import core, main

NOW = "2026-10-29T12:00:00+00:00"


@pytest.fixture()
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "rolling-budget.db"))
    monkeypatch.setattr(core, "now", lambda: NOW)
    calls = []
    class SyntheticModel:
        model = "synthetic-budget-test"
        def complete(self, system, prompt):
            calls.append(prompt)
            return "合成模型回复"
    monkeypatch.setattr(core.model, "from_env", lambda: SyntheticModel())
    core.init_db()
    client = TestClient(main.app)
    sid = client.get("/api/conversation").json()["session"]["id"]
    return client, sid, calls


def seed_turns(sid, stamps):
    conn = core.get_db()
    try:
        for index, stamp in enumerate(stamps):
            conn.execute("INSERT INTO audit(id,session_id,action,detail,reason,created_at) VALUES(?,?,'chat.turn','','synthetic',?)", (core.uid("aud"), sid, stamp))
            conn.execute("INSERT INTO messages(id,session_id,role,text,created_at) VALUES(?,?,'user',?,?)", (core.uid("msg"), sid, f"保留的合成历史 {index}", stamp))
            conn.execute("INSERT INTO messages(id,session_id,role,text,created_at) VALUES(?,?,'assistant','保留的合成回复',?)", (core.uid("msg"), sid, stamp))
        conn.commit()
    finally:
        conn.close()


def chat(client, sid):
    return client.post("/api/chat", json={"session_id": sid, "text": "请听我讲一段合成的经历"})


def test_forty_old_turns_do_not_permanently_lock_the_only_conversation(setup):
    client, sid, calls = setup
    seed_turns(sid, ["2026-10-29T10:00:00+00:00"] * 40)
    before = core.get_messages(sid)
    assert core.chat_budget_left(sid) == 40
    assert chat(client, sid).status_code == 200
    assert len(calls) == 1 and core.chat_budget_left(sid) == 39
    assert core.get_messages(sid)[:len(before)] == before
    assert len(core.get_messages(sid)) == len(before) + 2
    assert client.get("/api/conversation").json()["session"]["id"] == sid


def test_in_window_limit_returns_429_before_model_or_new_message(setup):
    client, sid, calls = setup
    seed_turns(sid, ["2026-10-29T11:45:00Z"] * 40)
    before = core.get_messages(sid)
    result = chat(client, sid)
    assert result.status_code == 429
    detail = result.json()["detail"]
    assert "近60分钟" in detail and "稍后再试" in detail and "内容仍保留" in detail
    assert "新建" not in detail and "会话" not in detail
    assert calls == [] and core.get_messages(sid) == before
    assert core.chat_budget_left(sid) == 0


def test_expired_window_releases_capacity_without_archiving_any_history(setup, monkeypatch):
    client, sid, calls = setup
    seed_turns(sid, ["2026-10-29T11:15:00+00:00"] * 40)
    before = core.get_messages(sid)
    assert chat(client, sid).status_code == 429
    monkeypatch.setattr(core, "now", lambda: "2026-10-29T12:15:00+00:00")
    assert core.chat_budget_left(sid) == 40
    assert chat(client, sid).status_code == 200
    assert len(calls) == 1 and core.chat_budget_left(sid) == 39
    assert core.get_messages(sid)[:len(before)] == before


def test_remaining_and_admission_use_the_same_window(setup, monkeypatch):
    client, sid, calls = setup
    monkeypatch.setattr(core, "CHAT_BUDGET", 3)
    seed_turns(sid, ["2026-10-29T10:59:59+00:00", "2026-10-29T11:00:01+00:00", NOW])
    assert core.chat_budget_left(sid) == 1
    assert chat(client, sid).status_code == 200
    assert core.chat_budget_left(sid) == 0
    count = len(core.get_messages(sid))
    assert chat(client, sid).status_code == 429
    assert core.chat_budget_left(sid) == 0 and len(calls) == 1
    assert len(core.get_messages(sid)) == count


@pytest.mark.parametrize("current", [NOW, "2026-10-29T20:00:00+08:00", "2026-10-29T08:00:00-04:00", "2026-10-29T12:00:00Z"])
def test_window_boundaries_normalize_utc_and_explicit_offsets(setup, monkeypatch, current):
    _, sid, _ = setup
    seed_turns(sid, ["2026-10-29T11:00:00+00:00",  # exactly 60 minutes: released
                     "2026-10-29T11:00:01+00:00",  # inside
                     "2026-10-29T19:00:01+08:00",  # same instant, explicit local offset
                     "2026-10-29T07:00:00-04:00",  # exactly cutoff in another timezone
                     "2026-10-29T11:30:00",        # legacy UTC without offset
                     "2026-10-29T11:59:59Z",       # UTC Z
                     NOW,                         # current instant included
                     "2026-10-29T12:00:01+00:00"]) # future record is outside the window
    monkeypatch.setattr(core, "now", lambda: current)
    assert core.chat_budget_left(sid) == 35


def test_config_identifies_rolling_window_without_changing_capacity(setup):
    client, _, _ = setup
    result = client.get("/api/config").json()
    assert result["budget"] == 40 and result["budget_window_minutes"] == 60
