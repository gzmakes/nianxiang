"""Synthetic end-to-end source preview, approval, storage and revocation."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from server import apple_source, core, main, public_source


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "public-source.db"))
    monkeypatch.setattr(main, "_source_previews", {})
    monkeypatch.setattr(main, "_schedule_preview_expiry_locked", lambda: None)
    monkeypatch.setattr(main, "_enrich", lambda value: value)
    core.init_db()
    return TestClient(main.app)


def snapshot(platform, text):
    return {
        "ok": True, "synthetic": False, "source": platform,
        "title": "合成公开页面", "text": text,
        "url": "https://example.invalid/synthetic", "length": len(text),
        "connector": {"id": platform, "name": "合成公开页面"},
        "items": [{"title": "合成公开页面", "summary": text[:30]}],
        "understanding": {"facts": [text[:30]], "inferences": [], "questions": []},
        "insights": [], "starters": [],
    }


def session(client):
    return client.post("/api/session", json={"mode": "empty"}).json()["session"]["id"]


def saved_source_text(source_id):
    conn = core.get_db()
    try:
        row = conn.execute("SELECT source_text FROM source_attachments WHERE id=?", (source_id,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


@pytest.mark.parametrize("platform", ["waytoagi", "jike"])
def test_approved_public_snapshot_stores_full_reviewed_body_and_revokes_only_it(client, monkeypatch, platform):
    sid = session(client)
    other = client.post("/api/local-files/confirm", json={"session_id": sid,
        "files": [{"name": "其他合成文件.txt", "text": "其他资料应当保留。"}]})
    assert other.status_code == 200, other.text
    other_id = other.json()["context"]["sources"][0]["id"]

    initial_text = "合成原文开头。" + "资料正文" * 180 + "原文结尾标记"
    current = {"data": snapshot(platform, initial_text)}
    calls = []
    def read(url, *, expected_source=None):
        assert expected_source == platform
        calls.append(url)
        return deepcopy(current["data"])
    monkeypatch.setattr(public_source, "read", read)
    link = "https://example.invalid/synthetic"
    preview = client.post("/api/onboarding/real/read", json={"source_id": platform, "url": link})
    assert preview.status_code == 200, preview.text
    assert preview.json()["text"] == initial_text
    preview_id = preview.json()["preview_id"]

    # The origin changes after review. Confirmation must use the approved
    # snapshot, never silently re-fetch or substitute the short summary.
    current["data"] = snapshot(platform, "发生变更的合成远程正文。")
    body = {"source_id": platform, "preview_id": preview_id, "session_id": sid}
    attached = client.post("/api/onboarding/real/start", json=body)
    assert attached.status_code == 200, attached.text
    assert attached.json()["session"]["id"] == sid
    assert calls == [link]
    sources = attached.json()["context"]["sources"]
    assert len(sources) == 2 and sources[0]["id"] == other_id
    new_id = sources[1]["id"]
    assert saved_source_text(new_id) == initial_text
    assert client.post("/api/onboarding/real/start", json=body).status_code == 400

    assert client.post("/api/source/revoke", json={"session_id": sid, "source_id": new_id}).status_code == 200
    assert saved_source_text(new_id) is None
    assert [source["id"] for source in core.list_sources(sid)] == [other_id]
    assert saved_source_text(other_id) == "其他资料应当保留。"


def test_platform_mismatch_is_rejected_without_preview(client, monkeypatch):
    calls = []
    monkeypatch.setattr(public_source, "_fetch", lambda *args: calls.append(args))
    result = client.post("/api/onboarding/real/read", json={"source_id": "waytoagi", "url": "https://m.okjike.com/originalPosts/67a4126c887087ba04e42f71"})
    assert result.status_code == 400
    assert result.json()["error_code"] == "source_url_mismatch"
    assert calls == []
    assert main._source_previews == {}


def test_failed_public_read_never_has_preview_or_attachment(client, monkeypatch):
    monkeypatch.setattr(public_source, "read", lambda _, **kwargs: {"ok": False, "error": "合成读取失败"})
    result = client.post("/api/onboarding/real/read", json={"source_id": "jike", "url": "https://example.invalid/"})
    assert result.status_code == 200
    assert result.json()["ok"] is False
    assert "preview_id" not in result.json()
    assert main._source_previews == {}


def test_successfully_read_empty_reminders_can_be_reviewed_and_attached(client, monkeypatch):
    sid = session(client)
    monkeypatch.setattr(apple_source, "_run", lambda _: "")
    response = client.post("/api/onboarding/real/read", json={"source_id": "apple_reminders"})
    assert response.status_code == 200 and response.json()["ok"] is True
    assert response.json()["items"] == []
    attached = client.post("/api/onboarding/real/start", json={"source_id": "apple_reminders",
        "preview_id": response.json()["preview_id"], "session_id": sid})
    assert attached.status_code == 200, attached.text
    assert attached.json()["session"]["id"] == sid
    sources = attached.json()["context"]["sources"]
    assert len(sources) == 1 and sources[0]["connector_id"] == "apple_reminders"
    # An empty list must not invent reminder items or unrelated content.
    assert sources[0]["items"] == []
    fact, = response.json()["understanding"]["facts"]
    assert response.json()["read_at"] in fact
    assert "未完成提醒" in fact and "0 条" in fact
    assert saved_source_text(sources[0]["id"]) == fact
