import sqlite3
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from server import chat_delivery, core, prompts
from server.main import app


def test_new_session_defaults_to_companion_and_mode_switch_preserves_other_preferences(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "mode.db"))
    core.init_db()
    with TestClient(app) as client:
        created = client.post("/api/session", json={"mode": "empty"})
        assert created.status_code == 200
        session = created.json()["session"]
        sid = session["id"]
        assert session["interaction_mode"] == "companion"
        assert session["persona_id"] == "nianxiang"

        core.set_session_persona(sid, "whale")
        switched = client.put(f"/api/session/{sid}/mode", json={"interaction_mode": "work"})
        assert switched.status_code == 200
        assert switched.json()["interaction_mode"] == "work"
        assert switched.json()["persona_id"] == "whale"
        assert switched.json()["conversation_style"] == "warm"

        loaded = client.get(f"/api/session/{sid}").json()["session"]
        assert loaded["interaction_mode"] == "work"
        assert loaded["persona_id"] == "whale"


def test_mode_api_rejects_invalid_values_and_missing_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "mode-errors.db"))
    core.init_db()
    with TestClient(app) as client:
        sid = client.post("/api/session", json={"mode": "empty"}).json()["session"]["id"]
        assert client.put(f"/api/session/{sid}/mode", json={"interaction_mode": "other"}).status_code == 400
        assert client.put("/api/session/missing/mode", json={"interaction_mode": "work"}).status_code == 404


def test_existing_schema_migrates_sessions_and_assistant_messages_to_companion(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE sessions(id TEXT PRIMARY KEY, created_at TEXT, mode TEXT, source_text TEXT,
                              source_label TEXT, state TEXT);
        CREATE TABLE messages(id TEXT PRIMARY KEY, session_id TEXT, role TEXT, text TEXT,
                              citations TEXT DEFAULT '[]', suggestions TEXT DEFAULT '[]', created_at TEXT);
        INSERT INTO sessions VALUES('s', 'now', 'empty', '', '旧对话', 'listening');
        INSERT INTO messages VALUES('m', 's', 'assistant', '旧回复', '[]', '[]', 'now');
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(core, "DB_PATH", str(db_path))

    core.init_db()

    assert core.get_session("s")["interaction_mode"] == "companion"
    assert core.get_messages("s")[0]["interaction_mode"] == "companion"


def test_legacy_mode_is_ignored_by_the_unified_prompt_and_preserves_whale_identity():
    rendered = prompts.system_prompt("whale", "work")
    assert "【产品人格：whale】" in rendered
    assert "【工作模式】" not in rendered
    assert rendered == prompts.system_prompt("whale", "companion")
    assert "大肥鱼" in rendered
    assert "你是当前会话选定的具身伙伴" in rendered


def test_interaction_mode_does_not_change_model_context_stamp(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "stamp.db"))
    core.init_db()
    sid = core.create_session("empty")["session"]["id"]
    before = core._model_context_stamp(sid)
    core.set_session_mode(sid, "work")
    assert core._model_context_stamp(sid) == before


def test_work_reply_uses_one_complete_delivery_block_and_records_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "reply.db"))
    core.init_db()
    sid = core.create_session("empty", interaction_mode="work")["session"]["id"]
    sent = []

    class FakeModel:
        model = "synthetic"

        def complete(self, system, prompt):
            sent.append((system, prompt))
            return "结论先说。\n\n详细说明如下。\n- 保持结构。"

    monkeypatch.setattr(core.model, "from_env", lambda: FakeModel())
    result = core.generate_reply(sid, "请分析这个问题")
    assistant = result["messages"][-1]

    assert "【工作模式】" not in sent[0][0]
    assert assistant["interaction_mode"] == "work"
    assert assistant["text"] == "结论先说。\n\n详细说明如下。\n- 保持结构。"
    assert not assistant.get("delivery_pending", False)


def test_work_delivery_marker_splits_only_outside_code_fences():
    text = "先说结论。<!--NX-BUBBLE-->再展开。\n```text\n<!--NX-BUBBLE-->\n保留在代码里\n```"
    assert chat_delivery.split_reply(text, mode="work") == [
        "先说结论。",
        "再展开。\n```text\n<!--NX-BUBBLE-->\n保留在代码里\n```",
    ]
