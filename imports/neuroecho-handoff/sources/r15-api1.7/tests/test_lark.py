"""飞书只读冷启动（PRD F21/F22/F23）。"""
import pytest
from fastapi.testclient import TestClient

from server import core, lark, main
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    core.init_db()
    return TestClient(app)


FAKE_DOC = {
    "ok": True,
    "title": "团队周报",
    "text": "本周完成了理解卡原型。下周要给团队演示最小闭环。我卡在记忆分寸上。",
    "length": 34,
    "identity": "user",
    "source": "feishu",
}


def test_lark_preview_ok(client, monkeypatch):
    monkeypatch.setattr(lark, "read_doc", lambda url: dict(FAKE_DOC))
    r = client.post("/api/lark/preview", json={"url": "https://example.feishu.cn/docx/abc"})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] and d["title"] == "团队周报"
    assert "理解卡" in d["preview"]
    assert "text" not in d  # 预览不返回全文


def test_lark_start_creates_session_and_audit(client, monkeypatch):
    monkeypatch.setattr(lark, "read_doc", lambda url: dict(FAKE_DOC))
    url = "https://example.feishu.cn/docx/abc"
    preview = client.post("/api/lark/preview", json={"url": url}).json()
    monkeypatch.setattr(lark, "read_doc", lambda url: pytest.fail("must not reread"))
    r = client.post("/api/lark/start", json={"url": url, "preview_id": preview["preview_id"]})
    assert r.status_code == 200
    d = r.json()
    sid = d["session"]["id"]
    assert d["session"]["source_label"].startswith("飞书文档 · 团队周报")
    assert len(d["memories"]) >= 3
    audit = client.get(f"/api/audit?session_id={sid}").json()["events"]
    assert any(e["action"] == "lark.read" for e in audit)
    assert client.post("/api/lark/start", json={"url": url, "preview_id": preview["preview_id"]}).status_code == 400


def test_lark_preview_auth_error_is_actionable(client, monkeypatch):
    monkeypatch.setattr(lark, "read_doc", lambda url: {
        "ok": False, "error": "need_user_authorization", "hint": "run: lark-cli auth login"
    })
    r = client.post("/api/lark/preview", json={"url": "https://example.feishu.cn/docx/abc"})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is False
    assert "auth login" in d["hint"]


def test_lark_rejects_bad_url():
    out = lark.read_doc("not-a-url")
    assert out["ok"] is False
    assert "https" in out["error"]


def test_attach_reviewed_document_preserves_chat_and_revokes_only_its_memories(client, monkeypatch):
    monkeypatch.setattr(lark, 'read_doc', lambda url: dict(FAKE_DOC))
    monkeypatch.setattr(main, '_enrich', lambda data: data)
    url = 'https://example.feishu.cn/docx/abc'
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    original = core.add_memory(sid, 'fact', '喜欢散步', source='用户手动添加', status='confirmed')
    core.add_message(sid, 'user', '今天走了很远')
    original_bookmark = core.create_bookmark(sid, '散步', '', '')
    before = core.get_messages(sid)
    preview = client.post('/api/lark/preview', json={'url': url}).json()
    monkeypatch.setattr(lark, 'read_doc', lambda url: pytest.fail('attach must not reread'))
    body = {'session_id': sid, 'url': url, 'preview_id': preview['preview_id']}
    response = client.post('/api/lark/attach', json=body)
    assert response.status_code == 200
    result = response.json()
    assert result['session']['id'] == sid and result['messages'] == before
    assert result['context']['items'][0]['summary'] == FAKE_DOC['text']
    assert any(m['id'] == original['id'] for m in result['memories'])
    new = [m for m in result['memories'] if m['id'] != original['id']]
    assert new and all(m['status'] == 'candidate' for m in new)
    source_bookmark = core.create_bookmark(sid, '文档里的理解卡', '', '', source_memory_id=new[0]['id'])
    # A consumed preview cannot be replayed or silently read again.
    assert client.post('/api/lark/attach', json=body).status_code == 400
    assert client.post('/api/source/revoke', json={'session_id': sid}).json()['cleaned'] == len(new)
    assert [m['id'] for m in core.list_memories(sid)] == [original['id']]
    assert core.memory_history(original['id'])
    assert core.get_messages(sid) == before
    assert core.get_session_context(sid) is None
    assert core.latest_bookmark(sid)['id'] == original_bookmark['id']
    assert any(b['id'] == source_bookmark['id'] for b in core.export_data(sid)['bookmarks'])
    assert client.post('/api/source/revoke', json={'session_id': sid}).json()['cleaned'] == 0
    assert [m['id'] for m in core.list_memories(sid)] == [original['id']]
    assert client.post('/api/lark/attach', json=body).status_code == 400
    monkeypatch.setattr(lark, 'read_doc', lambda url: dict(FAKE_DOC))
    second_preview = client.post('/api/lark/preview', json={'url': url}).json()['preview_id']
    reattached = client.post('/api/lark/attach', json={**body, 'preview_id': second_preview}).json()
    assert reattached['session']['state'] == 'listening'
    assert reattached['session']['source_revoked'] == 0
    assert reattached['session']['id'] == sid


@pytest.mark.parametrize('mode,text', [('sample', ''), ('paste', '这是一段原有资料。')])
def test_attach_adds_to_legacy_source_without_replacing_it(client, monkeypatch, mode, text):
    monkeypatch.setattr(lark, 'read_doc', lambda url: dict(FAKE_DOC))
    monkeypatch.setattr(main, '_enrich', lambda data: data)
    url = 'https://example.feishu.cn/docx/abc'
    # Old sample data is a migration fixture only; production cannot create it.
    sid = core.create_session(mode=mode, text=text)['session']['id']
    prior = core.get_messages(sid)
    preview = client.post('/api/lark/preview', json={'url': url}).json()['preview_id']
    result = client.post('/api/lark/attach', json={'session_id': sid, 'url': url, 'preview_id': preview})
    assert result.status_code == 200, result.text
    assert len(result.json()['context']['sources']) == 2
    assert core.get_messages(sid) == prior


def test_attach_rejects_wrong_url_and_expired_or_unknown_preview(client, monkeypatch):
    monkeypatch.setattr(lark, 'read_doc', lambda url: dict(FAKE_DOC))
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    url = 'https://example.feishu.cn/docx/abc'
    p = client.post('/api/lark/preview', json={'url': url}).json()['preview_id']
    assert client.post('/api/lark/attach', json={'session_id': sid, 'url': url + 'x', 'preview_id': p}).status_code == 400
    p = client.post('/api/lark/preview', json={'url': url}).json()['preview_id']
    created, source, snapshot = main._source_previews[p]
    main._source_previews[p] = (created - main._PREVIEW_TTL - 1, source, snapshot)
    assert client.post('/api/lark/attach', json={'session_id': sid, 'url': url, 'preview_id': p}).status_code == 400
    assert core.get_session_context(sid) is None
    assert client.post('/api/lark/attach', json={'session_id': 'missing', 'url': url, 'preview_id': p}).status_code == 404


def test_concurrent_different_attachments_are_both_preserved(client):
    from concurrent.futures import ThreadPoolExecutor
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    def attach(label):
        try:
            core.attach_source_to_empty_session(sid, label, label, {'facts': [], 'inferences': [], 'questions': []},
                                                [{'title': label}], [], [])
            return 'ok'
        except core.SourceConflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(attach, ['first', 'second']))
    assert sorted(result) == ['ok', 'ok']
    assert {s['label'] for s in core.list_sources(sid)} == {'first', 'second'}
