"""Multisource consent and independent removal use synthetic snapshots only."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from server import core, main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "multi-api.db"))
    monkeypatch.setattr(main, "_source_previews", {})
    monkeypatch.setattr(main, "_schedule_preview_expiry_locked", lambda: None)
    monkeypatch.setattr(main, "_enrich", lambda value: value)
    core.init_db()
    return TestClient(main.app)


def snapshot(cid, title=None):
    title = title or cid + " 合成条目"
    return {"ok": True, "connector": {"id": cid, "name": cid}, "title": title,
            "items": [{"title": title, "summary": cid + " 合成摘要", "meta": "fixture"}],
            "understanding": {"facts": [cid + " 合成事实"], "inferences": [], "questions": []},
            "insights": [], "starters": []}


def empty(client):
    return client.post("/api/session", json={"mode": "empty"}).json()["session"]["id"]


def connect(client, cid, sid=None, title=None):
    preview = main._save_preview(cid, snapshot(cid, title))
    payload = {"preview_id": preview}
    if sid: payload["session_id"] = sid
    endpoint = "/api/" + cid + "/start" if cid in ("gmail", "notion") else "/api/onboarding/real/start"
    if cid not in ("gmail", "notion"): payload["source_id"] = cid
    return client.post(endpoint, json=payload)


@pytest.mark.parametrize("first", ["gmail", "notion", "git"])
def test_new_source_session_can_add_another_source_and_remove_only_first(client, first):
    initial = connect(client, first)
    assert initial.status_code == 200, initial.text
    sid = initial.json()["session"]["id"]
    first_id = initial.json()["context"]["sources"][0]["id"]
    prior = core.add_message(sid, "user", "我想在这段对话里继续说")
    personal = core.add_memory(sid, "fact", "自己确认过的偏好", "用户手动添加", "confirmed")
    second = client.post("/api/local-files/confirm", json={"session_id": sid,
                        "files": [{"name": "合成计划.txt", "text": "第二份资料的代号是合成银杏。"}]})
    assert second.status_code == 200, second.text
    sources = second.json()["context"]["sources"]
    assert len(sources) == 2 and sources[0]["id"] == first_id
    second_id = sources[1]["id"]
    removed = client.post("/api/source/revoke", json={"session_id": sid, "source_id": first_id})
    assert removed.status_code == 200, removed.text
    after = client.get("/api/session/" + sid).json()
    assert [s["id"] for s in after["context"]["sources"]] == [second_id]
    assert after["context"]["connector_id"] == "local_files"
    assert prior["id"] in [m["id"] for m in after["messages"]]
    assert personal["id"] in [m["id"] for m in after["memories"]]
    assert any("合成银杏" in m["text"] for m in after["memories"])
    assert not any(first + " 合成事实" == m["text"] for m in after["memories"])
    assert client.post("/api/source/revoke", json={"session_id": sid}).status_code == 200
    assert client.get("/api/session/" + sid).json()["context"] is None
    assert [m["id"] for m in core.list_memories(sid)] == [personal["id"]]


def test_source_id_is_scoped_to_its_session(client):
    a = connect(client, "git").json(); b = connect(client, "gmail").json()
    sid = a["session"]["id"]
    wrong_id = b["context"]["sources"][0]["id"]
    before = client.get("/api/session/" + sid).json()
    assert client.post("/api/source/revoke", json={"session_id": sid, "source_id": wrong_id}).status_code == 404
    assert client.get("/api/session/" + sid).json() == before
    assert client.post("/api/source/revoke", json={"session_id": "missing"}).status_code == 404


def test_source_limit_rejection_keeps_preview_for_a_later_explicit_confirmation(client):
    sid = empty(client)
    for i in range(8):
        result = client.post("/api/local-files/confirm", json={"session_id": sid,
                "files": [{"name": f"fixture{i}.txt", "text": f"合成项目第{i}份计划，单独保存。"}]})
        assert result.status_code == 200, result.text
    pending = main._save_preview("gmail", snapshot("gmail"))
    body = {"session_id": sid, "preview_id": pending}
    assert client.post("/api/gmail/start", json=body).status_code == 409
    assert pending in main._source_previews
    source_id = core.list_sources(sid)[0]["id"]
    client.post("/api/source/revoke", json={"session_id": sid, "source_id": source_id})
    assert client.post("/api/gmail/start", json=body).status_code == 200
    assert pending not in main._source_previews


def test_feishu_attaches_second_reviewed_snapshot_without_reading_it_twice(client, monkeypatch):
    sid = connect(client, "git").json()["session"]["id"]
    doc = {"ok": True, "title": "合成飞书资料", "text": "合成飞书资料的日期是周五。",
           "identity": "synthetic", "length": 17}
    reads = []
    def read_doc(url): reads.append(url); return deepcopy(doc)
    monkeypatch.setattr(main.lark, "read_doc", read_doc)
    url = "https://example.feishu.cn/docx/synthetic"
    preview = client.post("/api/lark/preview", json={"url": url}).json()
    attached = client.post("/api/lark/attach", json={"session_id": sid, "url": url,
                           "preview_id": preview["preview_id"]})
    assert attached.status_code == 200, attached.text
    assert len(reads) == 1
    assert len(attached.json()["context"]["sources"]) == 2
    assert attached.json()["context"]["sources"][1]["label"] == "飞书文档 · 合成飞书资料"
    assert client.post("/api/lark/attach", json={"session_id": sid, "url": url,
                        "preview_id": preview["preview_id"]}).status_code == 400


@pytest.mark.parametrize("length", [599, 601, 12000, 12001])
def test_feishu_preview_is_exactly_the_snapshot_confirmed_and_revoke_is_scoped(client, monkeypatch, length):
    sid = connect(client, "git").json()["session"]["id"]
    first_id = core.list_sources(sid)[0]["id"]
    original = "合" * (length - 1) + "尾"
    reads = []
    def read_doc(url):
        reads.append(url)
        return {"ok": True, "title": "合成飞书资料", "text": original,
                "identity": "synthetic", "length": len(original)}
    monkeypatch.setattr(main.lark, "read_doc", read_doc)
    url = "https://example.invalid/docx/synthetic"
    preview = client.post("/api/lark/preview", json={"url": url}).json()
    expected = original[:main.lark.MAX_CHARS]
    assert preview["preview"] == expected
    assert preview["length"] == len(expected)
    assert preview["extracted_length"] == len(original)
    assert preview["truncated"] is (length > main.lark.MAX_CHARS)
    attached = client.post("/api/lark/attach", json={"session_id": sid, "url": url,
                           "preview_id": preview["preview_id"]})
    assert attached.status_code == 200
    assert reads == [url]
    source_id = attached.json()["context"]["sources"][1]["id"]
    conn = core.get_db()
    try:
        saved = conn.execute("SELECT source_text FROM source_attachments WHERE id=?", (source_id,)).fetchone()[0]
        assert saved == preview["preview"]
    finally:
        conn.close()
    assert client.post("/api/source/revoke", json={"session_id": sid, "source_id": source_id}).status_code == 200
    assert [source["id"] for source in core.list_sources(sid)] == [first_id]


def test_expired_feishu_preview_never_fetches_again_or_attaches(client, monkeypatch):
    sid = empty(client)
    url = "https://example.invalid/docx/synthetic"
    reads = []
    def read_doc(value):
        reads.append(value)
        return {"ok": True, "title": "合成资料", "text": "合成正文", "identity": "synthetic", "length": 4}
    monkeypatch.setattr(main.lark, "read_doc", read_doc)
    preview = client.post("/api/lark/preview", json={"url": url}).json()
    created, key, snapshot = main._source_previews[preview["preview_id"]]
    main._source_previews[preview["preview_id"]] = (created - main._PREVIEW_TTL - 1, key, snapshot)
    result = client.post("/api/lark/attach", json={"session_id": sid, "url": url,
                         "preview_id": preview["preview_id"]})
    assert result.status_code == 400
    assert reads == [url]
    assert core.list_sources(sid) == []


def test_new_reviewed_sources_have_stable_provenance_after_restart(client):
    initial = connect(client, "notion").json()
    sid = initial["session"]["id"]
    original = initial["context"]["sources"][0]["id"]
    core.init_db(); core.init_db()
    assert core.list_sources(sid)[0]["id"] == original
    assert client.post("/api/source/revoke", json={"session_id": sid, "source_id": original}).status_code == 200
    core.init_db()
    assert core.list_sources(sid) == []
    assert core.get_session_context(sid) is None
    assert core.list_memories(sid) == []


def test_concurrent_restores_migrate_one_legacy_snapshot(client):
    from concurrent.futures import ThreadPoolExecutor
    # Reconstruct the pre-registry shape; both surfaces must see the same
    # newly migrated source when restoring this old conversation together.
    sid = core.create_session('paste', text='原有合成资料中的独立计划。')['session']['id']
    conn = core.get_db()
    conn.execute('DELETE FROM source_attachments WHERE session_id=?', (sid,))
    conn.execute('UPDATE sessions SET source_attachment_id=NULL WHERE id=?', (sid,))
    conn.commit()
    conn.close()
    with ThreadPoolExecutor(max_workers=6) as pool:
        restored = list(pool.map(lambda _: core.list_sources(sid), range(12)))
    assert all(len(sources) == 1 for sources in restored)
    assert len({sources[0]['id'] for sources in restored}) == 1
