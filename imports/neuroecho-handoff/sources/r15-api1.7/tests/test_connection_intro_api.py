"""API integration checks with synthetic fixtures; no external credentials/read calls."""
import pytest
from fastapi.testclient import TestClient
from server import core, main, connection_intro, feishu_account, apple_source


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'intro-api.db'))
    monkeypatch.setattr(main, '_source_previews', {})
    monkeypatch.setattr(main, '_schedule_preview_expiry_locked', lambda: None)
    core.init_db()
    return TestClient(main.app)


def snapshot(cid='apple_calendar'):
    return {'ok': True, 'connector': {'id': cid, 'name': '合成日历'},
            'text': '合成的过去七天日历，没有真实个人资料。',
            'items': [{'title': '合成会议', 'summary': '仅单元测试'}],
            'understanding': {'facts': ['合成会议'], 'inferences': [], 'questions': []},
            'insights': [], 'starters': [],
            'scope': {'kind': 'last_7_days', 'since': '2026-10-24', 'until': '2026-10-31', 'label': '过去7天'}}


def fake_start(calls):
    def start(sid, source_id, receipt=None):
        calls.append((sid, source_id, receipt))
        return {'id': 'intro_fixture', 'session_id': sid, 'source_id': source_id,
                'status': 'running', 'message_id': None, 'error': None}
    return start


def test_recent_read_skips_model_then_attaches_exact_preview_once(client, monkeypatch):
    calls = []
    reads = []
    monkeypatch.setattr(apple_source, 'read_calendar_recent', lambda: reads.append('recent') or snapshot())
    monkeypatch.setattr(main, '_enrich', lambda value: pytest.fail('No model before connection commits'))
    monkeypatch.setattr(connection_intro, 'start', fake_start(calls))
    sid = client.get('/api/conversation').json()['session']['id']
    before = core.get_messages(sid)
    read = client.post('/api/onboarding/real/read', json={
        'source_id': 'apple_calendar', 'read_window': 'recent7', 'start_intro': True}).json()
    assert read['ok'] and reads == ['recent']
    # Confirmation must consume the accepted snapshot, not re-read the source.
    monkeypatch.setattr(apple_source, 'read_calendar_recent', lambda: pytest.fail('Must not read twice'))
    payload = {'source_id': 'apple_calendar', 'preview_id': read['preview_id'], 'start_intro': True}
    response = client.post('/api/onboarding/real/start', json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['session']['id'] == sid and len(core.list_sessions()) == 1
    assert data['intro']['status'] == 'running' and core.get_messages(sid) == before
    sources = core.list_sources(sid)
    assert calls == [(sid, 'apple_calendar', [sources[0]['id']])]
    with core.get_db() as conn:
        assert 'last_7_days' in conn.execute('SELECT read_scope FROM source_attachments').fetchone()[0]
    assert client.post('/api/onboarding/real/start', json=payload).status_code == 400
    assert len(calls) == 1


def test_local_file_batch_receipt_contains_only_new_files_and_no_new_conversation(client, monkeypatch):
    calls = []
    monkeypatch.setattr(connection_intro, 'start', fake_start(calls))
    sid = client.get('/api/conversation').json()['session']['id']
    old = client.post('/api/local-files/confirm', json={'session_id': sid,
        'files': [{'name': '旧合成.txt', 'text': '旧合成资料'}]}).json()['context']['sources'][0]['id']
    result = client.post('/api/local-files/confirm', json={'start_intro': True,
        'files': [{'name': '新合成甲.txt', 'text': '新合成甲资料'}, {'name': '新合成乙.txt', 'text': '新合成乙资料'}]})
    assert result.status_code == 200, result.text
    assert result.json()['session']['id'] == sid and len(core.list_sessions()) == 1
    assert len(calls) == 1 and len(calls[0][2]) == 2 and old not in calls[0][2]


def test_failed_auth_does_not_start_intro_and_success_commits_before_worker(client, monkeypatch):
    sid = client.get('/api/conversation').json()['session']['id']
    calls = []
    monkeypatch.setattr(connection_intro, 'start', fake_start(calls))
    monkeypatch.setattr(feishu_account, 'verify_access', lambda: {'ok': False, 'error': '合成权限不足'})
    body = {'session_id': sid, 'start_intro': True}
    assert client.post('/api/lark/account/connect', json=body).json()['ok'] is False
    assert not calls
    monkeypatch.setattr(feishu_account, 'verify_access', lambda: {'ok': True, 'account_key': 'a' * 64})
    def connected_start(sid, source_id, receipt=None):
        with core.get_db() as conn:
            assert feishu_account.snapshot(conn, sid)['enabled']
        return fake_start(calls)(sid, source_id, receipt)
    monkeypatch.setattr(connection_intro, 'start', connected_start)
    result = client.post('/api/lark/account/connect', json=body)
    assert result.status_code == 200 and result.json()['intro']['id'] == 'intro_fixture'
    assert calls == [(sid, 'feishu', None)]


def test_intro_failure_does_not_undo_successful_connection_or_expose_error(client, monkeypatch):
    sid = client.get('/api/conversation').json()['session']['id']
    monkeypatch.setattr(feishu_account, 'verify_access', lambda: {'ok': True, 'account_key': 'a' * 64})
    def broken(*args, **kwargs):
        raise RuntimeError('private-provider-output')
    monkeypatch.setattr(connection_intro, 'start', broken)
    response = client.post('/api/lark/account/connect', json={'session_id': sid, 'start_intro': True})
    assert response.status_code == 200
    data = response.json()
    assert data['ok'] and data['enabled'] and data['intro']['status'] == 'failed'
    assert 'private-provider-output' not in response.text


def test_job_status_cannot_read_another_conversation_and_missing_connection_is_not_success(client):
    a = client.get('/api/conversation').json()['session']['id']
    b = core.create_session('empty')['session']['id']
    stamp = core.now()
    with core.get_db() as conn:
        conn.execute("INSERT INTO connection_intro_jobs(id,session_id,source_id,dedupe_key,selection,last_user_rowid,status,created_at,updated_at) VALUES(?,?,?,?,?,0,'completed',?,?)",
                     ('intro_other', b, 'local_files', 'unit-dedupe', '{}', stamp, stamp))
    response = client.get('/api/connections/intro/intro_other', params={'session_id': a})
    assert response.status_code == 404 and response.headers['cache-control'] == 'no-store'
    assert client.get('/api/connections/intro/intro_other', params={'session_id': b}).status_code == 200
    response = client.post('/api/connections/intro', json={'session_id': a, 'source_id': 'feishu'})
    assert response.status_code == 409 and response.json()['error_code'] == 'connection_unavailable'
    assert client.post('/api/connections/intro', json={'session_id': 'missing', 'source_id': 'feishu'}).status_code == 404
