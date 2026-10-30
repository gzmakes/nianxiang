"""Notion 真实只读（内部集成 token）。"""
import pytest
from fastapi.testclient import TestClient

from server import core, notion_source
from server.main import app


def fake_get(path, token):
    if path.startswith("/databases/"):
        import urllib.error
        raise urllib.error.HTTPError("u", 404, "not a database", {}, None)
    if path.startswith("/pages/"):
        return {"properties": {"Name": {"type": "title", "title": [{"plain_text": "演示页面"}]}}}
    return {"results": [
        {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "先理解你，再决定怎样陪你。"}]}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "记忆分寸"}]}},
    ]}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(notion_source, "_get", fake_get)
    core.init_db()
    return TestClient(app)


def test_notion_preview_and_start(client, monkeypatch):
    r = client.post("/api/notion/preview", json={"token": "secret_x", "url": "https://www.notion.so/abc/1234567890abcdef1234567890abcdef"}).json()
    assert r["ok"] is True and r["synthetic"] is False
    assert r["title"] == "演示页面" and len(r["items"]) == 2

    monkeypatch.setattr(notion_source, "read", lambda *args: pytest.fail("start must use the preview snapshot"))
    s = client.post("/api/notion/start", json={"preview_id": r["preview_id"]}).json()
    assert s["session"]["source_label"] == "Notion · 已连接"
    assert "演示页面" in s["messages"][0]["text"] or "Notion" in s["messages"][0]["text"]
    assert s["context"]["connector_id"] == "notion"
    assert s["context"]["items"][0]["summary"] == r["items"][0]["summary"]
    assert client.post("/api/notion/start", json={"preview_id": r["preview_id"]}).status_code == 400


def test_notion_bad_token(client, monkeypatch):
    def boom(path, token):
        import urllib.error
        raise urllib.error.HTTPError("u", 401, "unauthorized", {}, None)
    monkeypatch.setattr(notion_source, "_get", boom)
    r = client.post("/api/notion/preview", json={"token": "bad", "url": "https://www.notion.so/1234567890abcdef1234567890abcdef"}).json()
    assert r["ok"] is False and "未授权" in r["error"]


def test_notion_database_read(client, monkeypatch):
    def fake_db_get(path, token):
        if path.startswith("/databases/"):
            return {"title": [{"plain_text": "演示项目库"}]}
        return fake_get(path, token)

    def fake_post(path, token, body):
        return {"results": [
            {"properties": {
                "名称": {"type": "title", "title": [{"plain_text": "接入飞书"}]},
                "状态": {"type": "status", "status": {"name": "进行中"}},
            }},
            {"properties": {
                "名称": {"type": "title", "title": [{"plain_text": "Notion 真实读"}]},
                "状态": {"type": "status", "status": {"name": "待办"}},
            }},
        ]}

    monkeypatch.setattr(notion_source, "_get", fake_db_get)
    monkeypatch.setattr(notion_source, "_post", fake_post)
    r = client.post("/api/notion/preview", json={"token": "t", "url": "https://www.notion.so/1234567890abcdef1234567890abcdef"}).json()
    assert r["ok"] is True
    assert r["title"] == "演示项目库"
    assert len(r["items"]) == 2 and r["items"][0]["title"] == "接入飞书"


def test_database_probe_network_failure_is_recoverable_not_500(client, monkeypatch):
    def timeout(path, token):
        raise TimeoutError("synthetic-private-error")
    monkeypatch.setattr(notion_source, "_get", timeout)
    response = client.post("/api/notion/preview", json={"token": "synthetic-token", "url": "https://www.notion.so/1234567890abcdef1234567890abcdef"})
    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is False and "超时" in result["error"]
    assert "synthetic-private" not in repr(result)


@pytest.mark.parametrize("status,expected", [(429, "频率受限"), (503, "服务暂不可用"), (403, "未授权")])
def test_database_errors_preserve_recovery_reason(client, monkeypatch, status, expected):
    import urllib.error
    calls = []
    def fail(path, token):
        calls.append(path)
        raise urllib.error.HTTPError("https://example.invalid/private-page", status, "synthetic-private-error", {}, None)
    monkeypatch.setattr(notion_source, "_get", fail)
    result = client.post("/api/notion/preview", json={"token": "synthetic-token", "url": "https://www.notion.so/1234567890abcdef1234567890abcdef"}).json()
    assert result["ok"] is False and expected in result["error"]
    assert len(calls) == 1
    assert "synthetic-private" not in repr(result)
