"""Malformed/failed CLI responses must not break real connector buttons.

All subprocess results and databases are synthetic; no account or network calls.
"""
import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from server import core, lark, main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "connectors.db"))
    monkeypatch.setattr(main, "_source_previews", {})
    monkeypatch.setattr(main, "_schedule_preview_expiry_locked", lambda: None)
    monkeypatch.setattr(lark.faults, "active", lambda *_: False)
    monkeypatch.setattr(lark, "cli_env", lambda: {})
    core.init_db()
    return TestClient(main.app)


def reply(monkeypatch, value, code=0):
    monkeypatch.setattr(lark.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess([], code, json.dumps(value), "synthetic-private-stderr"))


@pytest.mark.parametrize("value", [None, [], "unexpected", {"ok": True, "data": []},
    {"ok": True, "data": {"items": {"unexpected": "object"}}},
    {"ok": True, "data": {"items": [None]}},
    {"ok": True, "data": {"items": [{"title": "Chosen", "url": ["not-a-url"]}]}}])
def test_search_unexpected_response_returns_recoverable_failure(client, monkeypatch, value):
    reply(monkeypatch, value)
    response = client.post("/api/lark/docs", json={"q": "synthetic search"})
    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is False and result["error"] and result["hint"]
    assert "items" not in result
    assert "synthetic-private" not in response.text


def test_search_failed_cli_cannot_return_successful_items(client, monkeypatch):
    reply(monkeypatch, {"ok": True, "data": {"items": [{"title": "Not actually read", "url": "https://example.invalid/docx/x"}]}}, code=7)
    result = client.post("/api/lark/docs", json={"q": "synthetic search"}).json()
    assert result["ok"] is False and "items" not in result


@pytest.mark.parametrize("value", [{"ok": False, "error": "unexpected"},
    {"ok": True, "data": []}, {"ok": True, "data": {"document": []}},
    {"ok": True, "data": {"document": {"content": {"unexpected": "object"}}}}])
def test_document_unexpected_response_has_no_preview_or_500(client, monkeypatch, value):
    reply(monkeypatch, value)
    response = client.post("/api/lark/preview", json={"url": "https://example.invalid/docx/chosen"})
    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is False and result["error"]
    assert "preview_id" not in result and not main._source_previews


@pytest.mark.parametrize("endpoint,payload", [("/api/lark/docs", {"q": "synthetic"}),
    ("/api/lark/preview", {"url": "https://example.invalid/docx/chosen"})])
def test_cli_launch_failure_is_actionable_without_exposing_exception(client, monkeypatch, endpoint, payload):
    def fail(*args, **kwargs):
        raise OSError("synthetic-private-launch-details")
    monkeypatch.setattr(lark.subprocess, "run", fail)
    response = client.post(endpoint, json=payload)
    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is False and result["error"] and result["hint"]
    assert "synthetic-private" not in response.text
