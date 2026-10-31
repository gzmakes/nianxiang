"""Synthetic account state/approval/race regressions; no real credentials."""
import pytest
from fastapi.testclient import TestClient

from server import core, feishu_account, lark, main

KEY = "a" * 64


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "account.db"))
    core.init_db()
    monkeypatch.setattr(lark, "auth_status", lambda: {
        "ok": True, "user_status": "ready", "token_status": "valid", "account_key": KEY,
        "scopes": ["docx:document:readonly", "search:docs:read"]})
    monkeypatch.setattr(feishu_account, "verify_access", lambda: {
        "ok": True, "ready": True, "account_key": KEY, "search_checked": True})
    return TestClient(main.app)


def sid(client):
    return client.get("/api/conversation").json()["session"]["id"]


def test_existing_oauth_is_not_automatic_account_consent(client):
    session = sid(client)
    before = len(core.get_messages(session))
    status = client.get("/api/lark/account", params={"session_id": session})
    assert status.status_code == 200
    assert status.json()["ready"] is True and status.json()["enabled"] is False
    assert "account_key" not in status.json()
    assert status.headers["cache-control"] == "no-store"
    assert len(core.get_messages(session)) == before
    assert len(core.list_sessions()) == 1


def test_connect_verifies_then_persists_only_consent_and_can_be_disabled(client):
    session = sid(client)
    result = client.post("/api/lark/account/connect", json={"session_id": session})
    assert result.status_code == 200
    assert result.json()["enabled"] is True and result.json()["ready"] is True
    version = result.json()["version"]
    assert client.get("/api/lark/account", params={"session_id": session}).json()["enabled"] is True
    stopped = client.post("/api/lark/account/disconnect", json={"session_id": session})
    assert stopped.status_code == 200 and stopped.json()["enabled"] is False
    assert stopped.json()["version"] > version
    conn = core.get_db()
    try:
        assert feishu_account.snapshot(conn, session)["enabled"] is False
        assert conn.execute("SELECT count(*) FROM source_attachments").fetchone()[0] == 0
    finally:
        conn.close()


def test_search_or_permission_failure_never_enables_a_connection(client, monkeypatch):
    session = sid(client)
    monkeypatch.setattr(feishu_account, "verify_access", lambda: {
        "ok": False, "error": "搜索权限不足", "permission_issue": "user_grant"})
    result = client.post("/api/lark/account/connect", json={"session_id": session}).json()
    assert result["ok"] is False and result["ready"] is False and result["enabled"] is False
    assert result["permission_issue"] == "user_grant"


def test_disconnect_during_validation_cannot_be_overwritten_by_late_connect(client, monkeypatch):
    session = sid(client)
    def checking():
        assert client.post("/api/lark/account/disconnect", json={"session_id": session}).status_code == 200
        return {"ok": True, "ready": True, "account_key": KEY}
    monkeypatch.setattr(feishu_account, "verify_access", checking)
    result = client.post("/api/lark/account/connect", json={"session_id": session})
    assert result.status_code == 409 and result.json()["error_code"] == "connection_changed"
    assert client.get("/api/lark/account", params={"session_id": session}).json()["enabled"] is False


def test_disconnect_preserves_explicit_snapshot_manual_memory_and_history(client):
    session = sid(client)
    core.add_message(session, "user", "合成历史，断开不能删除。")
    core.attach_source_to_empty_session(session, "明确导入的合成文件", "保留的快照", {"facts": [], "inferences": [], "questions": []}, [], [], [], connector_id="local_files")
    before_messages = core.get_messages(session)
    before_sources = core.list_sources(session)
    before_memories = core.list_memories(session)
    client.post("/api/lark/account/connect", json={"session_id": session})
    assert client.post("/api/lark/account/disconnect", json={"session_id": session}).status_code == 200
    assert core.get_messages(session) == before_messages
    assert core.list_sources(session) == before_sources
    assert core.list_memories(session) == before_memories
    conn = core.get_db()
    try:
        cutoff = conn.execute("SELECT context_after_message_rowid FROM sessions WHERE id=?", (session,)).fetchone()[0]
        assert cutoff == conn.execute("SELECT max(rowid) FROM messages WHERE session_id=?", (session,)).fetchone()[0]
    finally:
        conn.close()


def test_changed_cli_identity_requires_reconnection(client, monkeypatch):
    session = sid(client)
    client.post("/api/lark/account/connect", json={"session_id": session})
    monkeypatch.setattr(lark, "auth_status", lambda: {
        "ok": True, "user_status": "ready", "token_status": "valid", "account_key": "b" * 64,
        "scopes": ["docx:document:readonly", "search:docs:read"]})
    current = client.get("/api/lark/account", params={"session_id": session}).json()
    assert current["enabled"] is True and current["ready"] is False
    assert current["permission_issue"] == "account_changed"


def test_unknown_conversation_and_extra_credentials_are_rejected(client):
    for route in ("connect", "disconnect"):
        assert client.post("/api/lark/account/" + route, json={"session_id": "missing"}).status_code == 404
    assert client.get("/api/lark/account", params={"session_id": "missing"}).status_code == 404
    assert client.post("/api/lark/account/connect", json={"session_id": sid(client), "token": "unit-only"}).status_code == 422
