"""A DB has one stable normal conversation; legacy data is preserved."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from server import core, main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "conversation.db"))
    core.init_db()
    return TestClient(main.app)


def test_first_boot_and_concurrent_reloads_create_exactly_one_conversation(client):
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda _: client.get("/api/conversation").json()["session"]["id"], range(16)))
    assert len(set(ids)) == 1
    assert len(core.list_sessions()) == 1
    result = client.get("/api/conversation").json()
    assert set(result) == {"session", "messages", "memories", "bookmark", "context"}
    assert result["session"]["mode"] == "empty"
    assert len(result["messages"]) == 1


def test_migration_selects_recent_user_conversation_and_preserves_other_data(client):
    older = core.create_session("empty")["session"]["id"]
    newer = core.create_session("empty")["session"]["id"]
    sample = core.create_session("sample")["session"]["id"]
    core.add_message(newer, "user", "newer conversation created earlier")
    core.add_message(older, "user", "most recently spoken to")
    core.add_message(sample, "user", "demo is not a normal conversation")
    memory = core.add_memory(older, "fact", "Synthetic retained memory", source="用户手动添加")
    bookmark = core.create_bookmark(older, "Synthetic retained bookmark", "", "")
    before = {row["id"] for row in core.list_sessions()}
    result = client.get("/api/conversation").json()
    assert result["session"]["id"] == older
    assert memory["id"] in {row["id"] for row in result["memories"]}
    assert result["bookmark"]["id"] == bookmark["id"]
    assert {row["id"] for row in core.list_sessions()} == before
    core.add_message(newer, "user", "later writes must not switch canonical")
    assert client.get("/api/conversation").json()["session"]["id"] == older


def test_no_user_history_prefers_latest_empty_and_keeps_samples(client):
    core.create_session("empty")
    chosen = core.create_session("empty")["session"]["id"]
    core.create_session("sample")
    assert client.get("/api/conversation").json()["session"]["id"] == chosen
    assert len(core.list_sessions()) == 3


def test_sample_only_db_gets_one_new_normal_conversation(client):
    original = core.create_session("sample")["session"]["id"]
    result = client.get("/api/conversation").json()
    assert result["session"]["id"] != original and result["session"]["mode"] == "empty"
    assert len(core.list_sessions()) == 2
    assert core.get_session(original) is not None


def test_canonical_survives_schema_reinitialization_and_client_supplied_ids_are_ignored(client):
    sid = client.get("/api/conversation").json()["session"]["id"]
    other = core.create_session("empty")["session"]["id"]
    core.init_db()
    assert client.get("/api/conversation", params={"session_id": other}).json()["session"]["id"] == sid
