"""Browser-selected local files: no filesystem enumeration, reviewed content only."""
import pytest
from fastapi.testclient import TestClient
from server import core, local_source, real_sources, lark, git_source, github_source
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'test.db'))
    core.init_db()
    return TestClient(app)


def test_catalog_and_legacy_entry_do_not_scan_local_files(client, monkeypatch):
    monkeypatch.setattr(local_source, 'list_files', lambda *a: (_ for _ in ()).throw(AssertionError('must not enumerate')))
    monkeypatch.setattr(lark, 'auth_status', lambda: {'ok': False})
    monkeypatch.setattr(git_source, 'repos', lambda: [])
    monkeypatch.setattr(github_source, 'status', lambda: {'ok': False})
    real_sources._CACHE = None
    assert next(s for s in client.get('/api/onboarding/sources').json()['sources'] if s['id'] == 'local_files')['status'] == 'ready'
    r = client.post('/api/onboarding/read', json={'connector_id': 'local_files'}).json()
    assert r['ok'] is False and '选择' in r['error']
    r = client.post('/api/onboarding/real/read', json={'source_id': 'local_files'}).json()
    assert r['ok'] is False
    assert client.post('/api/onboarding/start', json={'connector_id': 'local_files'}).status_code == 400


def test_confirm_attaches_reviewed_text_without_losing_chat_and_revoke_keeps_existing_memory(client):
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    core.add_message(sid, 'user', '之前的聊天')
    own = core.add_memory(sid, 'fact', '原有记忆', status='confirmed')
    data = {'session_id': sid, 'files': [{'name': 'fixture.md', 'text': '选择的一段合成资料。'}]}
    res = client.post('/api/local-files/confirm', json=data)
    assert res.status_code == 200
    result = res.json()
    assert result['session']['id'] == sid and result['context']['connector_id'] == 'local_files'
    assert any(m['text'] == '之前的聊天' for m in result['messages'])
    assert result['context']['items'][0]['title'] == 'fixture.md'
    assert client.post('/api/local-files/confirm', json=data).status_code == 409
    client.post('/api/source/revoke', json={'session_id': sid})
    assert [m['id'] for m in core.list_memories(sid)] == [own['id']]
    assert core.get_session_context(sid) is None


def test_new_session_uses_only_selected_content(client):
    res = client.post('/api/local-files/confirm', json={'files': [
        {'name': 'one.txt', 'text': '这是第一份合成材料。'}, {'name': 'two.md', 'text': '这是第二份合成材料。'}]})
    assert res.status_code == 200
    assert [i['title'] for i in res.json()['context']['items']] == ['one.txt', 'two.md']
    assert res.json()['session']['source_label'] == '已接入 2 份资料'
    assert [s['title'] for s in res.json()['context']['sources']] == ['one.txt', 'two.md']


@pytest.mark.parametrize('file', [
    {'name': '/Users/test/secret.txt', 'text': 'x'},
    {'name': r'C:\\test\\secret.txt', 'text': 'x'},
    {'name': 'bad.exe', 'text': 'x'},
    {'name': 'bad.txt', 'text': '\x00'},
    {'name': 'bad.txt', 'text': ' '},
])
def test_invalid_file_cannot_be_attached(client, file):
    assert client.post('/api/local-files/confirm', json={'files': [file]}).status_code == 400


def test_limits_and_extra_fields_rejected(client):
    assert client.post('/api/local-files/confirm', json={'files': [{'name': 'x.txt', 'text': 'a' * 4001}]}).status_code == 422
    assert client.post('/api/local-files/confirm', json={'files': [{'name': 'x.txt', 'text': 'a'}] * 4}).status_code == 422
    assert client.post('/api/local-files/confirm', json={'files': [{'name': 'x.txt', 'text': 'a', 'path': '/secret'}]}).status_code == 422
