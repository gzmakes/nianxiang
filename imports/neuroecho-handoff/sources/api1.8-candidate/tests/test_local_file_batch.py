"""Reviewed local files have independent lineage and atomic batch commits."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from server import core, main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'files.db'))
    monkeypatch.setattr(core.model, 'from_env', lambda: None)
    core.init_db()
    return TestClient(main.app)


def session(client):
    return client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']


def test_batch_saves_exact_reviewed_text_and_withdraws_one_file(client, monkeypatch):
    sid = session(client)
    personal = core.add_memory(sid, 'fact', '我自己的记忆', status='confirmed')
    message = core.add_message(sid, 'user', '我之前说过的话')
    files = [{'name': 'alpha.txt', 'text': 'ALPHA_TOKEN 对应合成苹果。'},
             {'name': 'beta.md', 'text': 'BETA_TOKEN 对应合成香蕉。' + '🙂' * 3960}]
    response = client.post('/api/local-files/confirm', json={'session_id': sid, 'files': files})
    assert response.status_code == 200, response.text
    sources = response.json()['context']['sources']
    assert [s['title'] for s in sources] == ['alpha.txt', 'beta.md']
    assert [s['label'] for s in sources] == ['本地文件 · alpha.txt', '本地文件 · beta.md']
    conn = core.get_db()
    try:
        stored = conn.execute('SELECT id,source_text FROM source_attachments WHERE session_id=? ORDER BY rowid', (sid,)).fetchall()
        assert [row['source_text'] for row in stored] == [file['text'] for file in files]
    finally:
        conn.close()
    original_memories = core.list_memories(sid)
    assert {m['source_attachment_id'] for m in original_memories if m['source_attachment_id']} == {s['id'] for s in sources}
    result = client.post('/api/source/revoke', json={'session_id': sid, 'source_id': sources[0]['id']})
    assert result.status_code == 200 and result.json()['remaining_sources'] == 1
    assert [s['id'] for s in core.list_sources(sid)] == [sources[1]['id']]
    remaining = core.list_memories(sid)
    assert personal['id'] in [m['id'] for m in remaining]
    assert not any(m['source_attachment_id'] == sources[0]['id'] for m in remaining)
    assert any(m['source_attachment_id'] == sources[1]['id'] for m in remaining)
    assert message['id'] in [m['id'] for m in core.get_messages(sid)]
    assert not core._source_excerpts(sid, 'ALPHA_TOKEN')
    assert any('BETA_TOKEN' in item for item in core._source_excerpts(sid, 'BETA_TOKEN'))
    core.init_db()
    assert [s['id'] for s in core.list_sources(sid)] == [sources[1]['id']]


def test_batch_duplicate_and_capacity_rejections_leave_everything_unchanged(client):
    sid = session(client)
    existing = {'name': 'existing.txt', 'text': '已经接入的合成内容。'}
    assert client.post('/api/local-files/confirm', json={'session_id': sid, 'files': [existing]}).status_code == 200
    before_sources, before_memories = core.list_sources(sid), core.list_memories(sid)
    fresh = {'name': 'fresh.txt', 'text': '新选择的合成内容。'}
    for files in ([fresh, existing], [fresh, fresh]):
        result = client.post('/api/local-files/confirm', json={'session_id': sid, 'files': files})
        assert result.status_code == 409
        assert core.list_sources(sid) == before_sources
        assert core.list_memories(sid) == before_memories
    for i in range(6):
        assert client.post('/api/local-files/confirm', json={'session_id': sid, 'files': [
            {'name': f'fixture{i}.txt', 'text': f'第{i}份合成内容。'}]}).status_code == 200
    before_sources, before_memories = core.list_sources(sid), core.list_memories(sid)
    result = client.post('/api/local-files/confirm', json={'session_id': sid, 'files': [fresh,
        {'name': 'another.txt', 'text': '另一份合成内容。'}]})
    assert result.status_code == 409
    assert core.list_sources(sid) == before_sources
    assert core.list_memories(sid) == before_memories


def test_database_failure_during_second_file_rolls_back_all_sources_memories_and_audit(client):
    sid = session(client)
    before_audit = core.audit_list(sid)
    conn = core.get_db()
    conn.execute("""CREATE TRIGGER synthetic_fail_second BEFORE INSERT ON source_attachments
                 WHEN NEW.label='本地文件 · second.txt' BEGIN SELECT RAISE(ABORT,'synthetic'); END""")
    conn.commit(); conn.close()
    with pytest.raises(sqlite3.IntegrityError, match='synthetic'):
        client.post('/api/local-files/confirm', json={'session_id': sid, 'files': [
            {'name': 'first.txt', 'text': '第一份合成内容。'},
            {'name': 'second.txt', 'text': '第二份合成内容。'}]})
    assert core.list_sources(sid) == []
    assert core.list_memories(sid) == []
    assert core.audit_list(sid) == before_audit


def test_legacy_combined_attachment_is_not_silently_split(client):
    sid = session(client)
    core.attach_source_to_empty_session(sid, '本地文件 · 用户选择', '【旧一.txt】\n旧资料一\n\n【旧二.txt】\n旧资料二',
        {'facts': ['旧资料一', '旧资料二']}, [{'title': '旧一.txt'}, {'title': '旧二.txt'}], [], [], 'local_files')
    old = core.list_sources(sid)[0]
    assert client.post('/api/local-files/confirm', json={'session_id': sid, 'files': [
        {'name': '新资料.txt', 'text': '新的合成资料。'}]}).status_code == 200
    core.init_db()
    assert [s['id'] for s in core.list_sources(sid)][0] == old['id']
    assert len(core.list_sources(sid)[0]['items']) == 2


def test_old_single_file_is_not_silently_added_twice(client):
    sid = session(client)
    core.attach_source_to_empty_session(sid, '本地文件 · 用户选择', '【旧资料.txt】\n原有合成资料。',
        {'facts': ['原有合成资料。']}, [{'title': '旧资料.txt', 'summary': '原有合成资料。'}], [], [], 'local_files')
    before = core.list_sources(sid)
    result = client.post('/api/local-files/confirm', json={'session_id': sid, 'files': [
        {'name': '旧资料.txt', 'text': '原有合成资料。'}]})
    assert result.status_code == 409
    assert core.list_sources(sid) == before


def test_competing_batches_cannot_exceed_capacity_or_partially_commit(client):
    sid = session(client)
    for i in range(6):
        result = client.post('/api/local-files/confirm', json={'session_id': sid, 'files': [
            {'name': f'fixture{i}.txt', 'text': f'第{i}份合成内容。'}]})
        assert result.status_code == 200
    previous_memories = len(core.list_memories(sid))
    def submit(index):
        try:
            core.attach_sources_to_session(sid, [
                {'connector_id': 'local_files', 'label': f'{index}-{j}', 'text': f'{index}-{j}',
                 'understanding': {'facts': [f'{index}-{j}']}, 'items': [{'title': f'{index}-{j}'}],
                 'insights': [], 'starters': []} for j in range(2)])
            return index
        except core.SourceConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(submit, [1, 2]))
    assert outcomes.count(None) == 1
    winner = next(value for value in outcomes if value is not None)
    loser = 3 - winner
    sources = core.list_sources(sid)
    assert len(sources) == 8
    assert {source['label'] for source in sources if source['label'].startswith(f'{winner}-')} == {f'{winner}-0', f'{winner}-1'}
    assert not any(source['label'].startswith(f'{loser}-') for source in sources)
    memories = core.list_memories(sid)
    assert len(memories) == previous_memories + 2
    assert {m['text'] for m in memories if m['text'].startswith(f'{winner}-')} == {f'{winner}-0', f'{winner}-1'}
    assert not any(m['text'].startswith(f'{loser}-') for m in memories)


def test_revoke_during_model_completion_discards_late_reply_and_keeps_other_file(client, monkeypatch):
    sid = session(client)
    result = client.post('/api/local-files/confirm', json={'session_id': sid, 'files': [
        {'name': 'one.txt', 'text': 'PRIVATE_ALPHA 独立资料。'},
        {'name': 'two.txt', 'text': 'PUBLIC_BETA 保留资料。'}]}).json()
    a, b = (source['id'] for source in result['context']['sources'])
    class Fake:
        model = 'synthetic'
        def complete(self, system, prompt):
            assert core.revoke_source(sid, a)['ok']
            return 'PRIVATE_ALPHA 不应提交的迟到结果'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    output = core.generate_reply(sid, 'PRIVATE_ALPHA')
    assert output['action'] == 'model.stale'
    assert 'PRIVATE_ALPHA' not in output['reply']
    assert not any(m['role'] == 'assistant' and 'PRIVATE_ALPHA' in m['text'] for m in core.get_messages(sid))
    assert [source['id'] for source in core.list_sources(sid)] == [b]


def test_revoke_after_model_check_before_commit_discards_reply(client, monkeypatch):
    sid = session(client)
    result = client.post('/api/local-files/confirm', json={'session_id': sid, 'files': [
        {'name': 'one.txt', 'text': 'PRIVATE_ALPHA 独立资料。'},
        {'name': 'two.txt', 'text': 'PUBLIC_BETA 保留资料。'}]}).json()
    a, b = (source['id'] for source in result['context']['sources'])
    class Fake:
        model = 'synthetic'
        def complete(self, system, prompt):
            return 'PRIVATE_ALPHA 不应提交的迟到结果'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    original = core.audit
    def audit(session_id, action, detail='', reason=''):
        if action == 'model.success':
            core.revoke_source(sid, a)
        return original(session_id, action, detail, reason)
    monkeypatch.setattr(core, 'audit', audit)
    output = core.generate_reply(sid, 'PRIVATE_ALPHA')
    assert output['action'] == 'model.stale'
    assert 'PRIVATE_ALPHA' not in output['reply']
    assert not any(m['role'] == 'assistant' and 'PRIVATE_ALPHA' in m['text'] for m in core.get_messages(sid))
    assert [source['id'] for source in core.list_sources(sid)] == [b]
