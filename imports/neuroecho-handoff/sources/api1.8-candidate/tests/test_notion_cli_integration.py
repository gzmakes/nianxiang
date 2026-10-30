"""Notion API routing and consent boundary, with synthetic adapters only."""
from copy import deepcopy
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from server import core, main, notion_cli_source, notion_source

PAGE = "https://www.notion.so/1234567890abcdef1234567890abcdef"


def snapshot():
    value = notion_source._package(
        "Synthetic chosen page",
        [{"type": "paragraph", "title": "Synthetic selected text", "meta": "Notion · paragraph", "summary": "Synthetic selected summary"}],
        "页面文本块", "单页只读")
    value["source"] = "notion-cli"
    return value


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "notion-cli-test.db"))
    monkeypatch.setattr(main, "_source_previews", {})
    monkeypatch.setattr(main, "_schedule_preview_expiry_locked", lambda: None)
    core.init_db()
    return TestClient(main.app)


def test_cli_preview_requires_no_token_and_uses_only_cli_adapter(client, monkeypatch):
    cli = Mock(return_value=snapshot())
    token = Mock(side_effect=AssertionError("CLI method must not call token adapter"))
    enrich = Mock(side_effect=AssertionError("preview must not invoke a model"))
    monkeypatch.setattr(notion_cli_source, "read", cli)
    monkeypatch.setattr(notion_source, "read", token)
    monkeypatch.setattr(main, "_enrich", enrich)
    response = client.post("/api/notion/preview", json={"url": PAGE, "method": "cli"})
    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is True and result["preview_id"]
    cli.assert_called_once_with(PAGE)
    token.assert_not_called()
    enrich.assert_not_called()


def test_default_token_method_remains_available_and_credentials_are_not_in_snapshot(client, monkeypatch):
    token = Mock(return_value=snapshot())
    monkeypatch.setattr(notion_source, "read", token)
    monkeypatch.setattr(notion_cli_source, "read", Mock(side_effect=AssertionError("default must not use CLI")))
    response = client.post("/api/notion/preview", json={"url": PAGE, "token": "synthetic-notion-token"})
    assert response.status_code == 200 and response.json()["ok"] is True
    token.assert_called_once_with("synthetic-notion-token", PAGE)
    assert "synthetic-notion-token" not in repr(main._source_previews)


def test_cli_ignores_unused_token_and_does_not_store_it(client, monkeypatch):
    cli = Mock(return_value=snapshot())
    monkeypatch.setattr(notion_cli_source, "read", cli)
    response = client.post("/api/notion/preview", json={"url": PAGE, "method": "cli", "token": "synthetic-unused-token"})
    assert response.status_code == 200 and response.json()["ok"] is True
    cli.assert_called_once_with(PAGE)
    assert "synthetic-unused-token" not in repr(main._source_previews)
    assert "synthetic-unused-token" not in response.text


def test_start_enriches_only_reviewed_snapshot_without_rereading_or_resending_credentials(client, monkeypatch):
    cli = Mock(return_value=snapshot())
    enriched = []
    def enrich(value):
        enriched.append(deepcopy(value))
        return {**value, "greeting": "Synthetic greeting after explicit confirmation"}
    monkeypatch.setattr(notion_cli_source, "read", cli)
    monkeypatch.setattr(main, "_enrich", enrich)
    preview = client.post("/api/notion/preview", json={"url": PAGE, "method": "cli"}).json()
    assert enriched == []
    monkeypatch.setattr(notion_cli_source, "read", Mock(side_effect=AssertionError("start must not reread CLI")))
    monkeypatch.setattr(notion_source, "read", Mock(side_effect=AssertionError("start must not use token")))
    response = client.post("/api/notion/start", json={"preview_id": preview["preview_id"]})
    assert response.status_code == 200
    result = response.json()
    assert len(enriched) == 1
    assert enriched[0]["items"] == preview["items"]
    assert result["context"]["items"] == preview["items"]
    assert result["session"]["source_label"] == "Notion · 已连接"
    assert client.post("/api/notion/start", json={"preview_id": preview["preview_id"]}).status_code == 400
    assert len(enriched) == 1


def test_cli_snapshot_can_attach_to_current_source_free_conversation(client, monkeypatch):
    current = core.create_session("empty")
    sid = current["session"]["id"]
    user_message = core.add_message(sid, "user", "Synthetic existing conversation")
    monkeypatch.setattr(notion_cli_source, "read", lambda url: snapshot())
    monkeypatch.setattr(main, "_enrich", lambda value: value)
    preview = client.post("/api/notion/preview", json={"url": PAGE, "method": "cli"}).json()
    response = client.post("/api/notion/start", json={"preview_id": preview["preview_id"], "session_id": sid})
    assert response.status_code == 200
    result = response.json()
    assert result["session"]["id"] == sid
    assert any(message["id"] == user_message["id"] for message in result["messages"])
    assert result["context"]["connector_id"] == "notion"


@pytest.mark.parametrize("reason", ["missing", "auth", "access", "timeout", "rate_limit", "format", "network"])
def test_expected_cli_failures_are_actionable_without_preview_or_500(client, monkeypatch, reason):
    def fail(*args, **kwargs):
        raise notion_cli_source.ReadError(reason)
    monkeypatch.setattr(notion_cli_source, "_get", fail)
    monkeypatch.setattr(notion_source, "read", Mock(side_effect=AssertionError("CLI failure must not fall back to token")))
    monkeypatch.setattr(main, "_enrich", Mock(side_effect=AssertionError("failed preview must not invoke a model")))
    response = client.post("/api/notion/preview", json={"url": PAGE, "method": "cli"})
    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is False and result["error"] and result["hint"]
    assert "preview_id" not in result and main._source_previews == {}


def test_expired_cli_preview_never_enriches_or_rereads(client, monkeypatch):
    monkeypatch.setattr(notion_cli_source, "read", lambda url: snapshot())
    preview = client.post("/api/notion/preview", json={"url": PAGE, "method": "cli"}).json()
    created, source, value = main._source_previews[preview["preview_id"]]
    main._source_previews[preview["preview_id"]] = (created-main._PREVIEW_TTL-1, source, value)
    monkeypatch.setattr(main, "_enrich", Mock(side_effect=AssertionError("expired snapshot must not invoke model")))
    monkeypatch.setattr(notion_cli_source, "read", Mock(side_effect=AssertionError("expired snapshot must not reread")))
    assert client.post("/api/notion/start", json={"preview_id": preview["preview_id"]}).status_code == 400


def test_unknown_method_is_rejected_before_any_adapter(client, monkeypatch):
    monkeypatch.setattr(notion_cli_source, "read", Mock(side_effect=AssertionError("invalid method")))
    monkeypatch.setattr(notion_source, "read", Mock(side_effect=AssertionError("invalid method")))
    assert client.post("/api/notion/preview", json={"url": PAGE, "method": "unknown"}).status_code == 422
    assert main._source_previews == {}
