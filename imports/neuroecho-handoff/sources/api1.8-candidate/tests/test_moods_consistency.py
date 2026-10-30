"""Mood persistence boundaries use synthetic clocks and temporary SQLite only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from server import companion_boundary, core, followups, moods, proactive_policy
from server.main import app


@pytest.fixture()
def client():
    with TestClient(app) as value:
        yield value


def create(client, sid, day='2026-10-30', **overrides):
    body = dict(session_id=sid, x=.3, y=-.4, note='合成手记', confirmed=True, expected_updated_at=None)
    body.update(overrides)
    return client.put('/api/moods/' + day, json=body)


def fixed_clock(monkeypatch, initial):
    clock = [initial]

    class SyntheticDatetime:
        fromisoformat = staticmethod(datetime.fromisoformat)

        @staticmethod
        def now(zone):
            return clock[0]

    monkeypatch.setattr(moods, 'datetime', SyntheticDatetime)
    return clock


@pytest.mark.parametrize('rollback_days', [0, 10])
def test_deleted_day_recreation_never_reuses_version_after_clock_repeat_or_rollback(client, monkeypatch, rollback_days):
    clock = fixed_clock(monkeypatch, datetime(2030, 1, 1, tzinfo=timezone.utc))
    sid = client.get('/api/conversation').json()['session']['id']
    first = create(client, sid).json()
    deleted = client.delete('/api/moods/2026-10-30', params={
        'session_id': sid, 'expected_updated_at': first['updated_at']})
    assert deleted.json() == {'deleted': True}
    clock[0] -= timedelta(days=rollback_days)
    second = create(client, sid, note='新记录').json()
    assert datetime.fromisoformat(second['updated_at']) > datetime.fromisoformat(first['updated_at'])
    old_update = create(client, sid, expected_updated_at=first['updated_at'])
    old_delete = client.delete('/api/moods/2026-10-30', params={
        'session_id': sid, 'expected_updated_at': first['updated_at']})
    for response in (old_update, old_delete):
        assert response.status_code == 409
        assert response.json()['error_code'] == 'mood_conflict'
        assert response.json()['current_updated_at'] == second['updated_at']
    assert client.get('/api/moods', params={'session_id': sid}).json()['moods'] == [second]


def test_legacy_mood_schema_seeds_global_clock_without_rewriting_rows(tmp_path, monkeypatch):
    path = tmp_path / 'legacy-mood.db'
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE sessions(id TEXT PRIMARY KEY)')
    conn.execute("INSERT INTO sessions VALUES('synthetic')")
    conn.execute('''CREATE TABLE mood_entries(session_id TEXT,date TEXT,x REAL,y REAL,note TEXT,
                    created_at TEXT,updated_at TEXT,PRIMARY KEY(session_id,date))''')
    legacy = ('synthetic', '2026-10-30', .2, -.2, 'legacy synthetic',
              '2035-01-01T00:00:00.000000+00:00', '2035-01-01T00:00:00.000000+00:00')
    conn.execute('INSERT INTO mood_entries VALUES(?,?,?,?,?,?,?)', legacy)
    moods.init_schema(conn)
    moods.init_schema(conn)
    assert conn.execute('SELECT * FROM mood_entries').fetchone() == legacy
    conn.commit()
    conn.close()
    fixed_clock(monkeypatch, datetime(2026, 10, 30, tzinfo=timezone.utc))
    new = moods.save(path, 'synthetic', '2026-10-31', .1, .1, 'new synthetic', None)
    assert datetime.fromisoformat(new['updated_at']) > datetime.fromisoformat(legacy[-1])


@pytest.mark.parametrize('other_operation', ['update', 'delete'])
def test_same_version_competing_writes_have_one_winner(client, other_operation):
    sid = client.get('/api/conversation').json()['session']['id']
    first = create(client, sid).json()
    barrier = Barrier(2)

    def write(operation):
        barrier.wait(timeout=5)
        if operation == 'delete':
            return client.delete('/api/moods/2026-10-30', params={
                'session_id': sid, 'expected_updated_at': first['updated_at']})
        return create(client, sid, note=operation, expected_updated_at=first['updated_at'])

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ['first-update', other_operation]))
    assert sorted(response.status_code for response in results) == [200, 409]
    winner = next(response.json() for response in results if response.status_code == 200)
    current = client.get('/api/moods', params={'session_id': sid}).json()['moods']
    assert current == ([] if winner.get('deleted') else [winner])


def test_export_and_delete_preserve_other_session_and_existing_f5_boundary(client):
    first = client.get('/api/conversation').json()['session']['id']
    second = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    create(client, first, day='2026-10-29', note='first synthetic')
    remaining = create(client, second, day='2026-10-30', note='second synthetic').json()
    companion_boundary.put(core.DB_PATH, first, expected_revision=0, mode='paused', until=None, time_zone='UTC')
    exported = core.export_data(first)
    assert [row['session_id'] for row in exported['mood_entries']] == [first]
    assert exported['companion_boundary'][0]['mode'] == 'paused'
    assert 'mood_version_clock' not in exported
    deleted = core.delete_session(first)['deleted']
    assert deleted['mood_entries'] == deleted['companion_boundaries'] == 1
    assert client.get('/api/moods', params={'session_id': first}).status_code == 404
    assert client.get('/api/moods', params={'session_id': second}).json()['moods'] == [remaining]
    with core.get_db() as conn:
        columns = [row['name'] for row in conn.execute('PRAGMA table_info(mood_version_clock)')]
        assert columns == ['singleton', 'last_issued_at']
        assert conn.execute('SELECT COUNT(*) FROM mood_version_clock').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM mood_entries WHERE session_id=?', (first,)).fetchone()[0] == 0


def test_source_withdrawal_keeps_manual_diary_and_invalidates_f5_contact(client, monkeypatch):
    clock = [datetime(2026, 10, 30, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr(followups, '_current', lambda callback: callback() if callback else clock[0])
    sid = client.get('/api/conversation').json()['session']['id']
    saved = create(client, sid).json()
    core.attach_source_to_empty_session(sid, '合成来源', '合成资料', core.build_understanding('合成资料', 'paste'), [], [], [])
    source = core.list_sources(sid)[0]['id']
    item = followups.create(core.DB_PATH, sid, '合成约定', (clock[0] + timedelta(minutes=1)).isoformat(),
                            'mood-source-boundary-request', allow_contact=True)
    clock[0] += timedelta(minutes=1)
    claim = proactive_policy.claim(core.DB_PATH, sid, item['id'], item['due_at'], channel='in_app')
    assert claim['claimed']
    core.revoke_source(sid, source)
    assert not proactive_policy.recheck(core.DB_PATH, sid, claim['claim_id'])['allowed']
    assert client.get('/api/moods', params={'session_id': sid}).json()['moods'] == [saved]


def test_diary_and_opt_in_draft_never_enter_chat_memory_or_model(client, monkeypatch):
    monkeypatch.setattr(core.model, 'from_env', lambda: pytest.fail('mood must not invoke a model'))
    sid = client.get('/api/conversation').json()['session']['id']
    before = client.get('/api/conversation').json()
    saved = create(client, sid, note='独立的合成心情笔记').json()
    response = client.post('/api/mood-suggestions', json={
        'session_id': sid, 'text': '我今天很开心', 'consent': True})
    assert response.json()['suggestion']['y'] is None
    assert response.headers['cache-control'] == 'no-store'
    assert client.get('/api/conversation').json() == before
    assert client.get('/api/moods', params={'session_id': sid}).json()['moods'] == [saved]
    assert client.get('/api/moods', params={'session_id': sid}).headers['cache-control'] == 'no-store'


def test_lost_write_receipts_are_reconciled_by_reads_without_new_writes(client):
    sid = client.get('/api/conversation').json()['session']['id']
    committed = create(client, sid).json()  # Simulate the caller losing this success response.
    stale_retry = create(client, sid)
    assert stale_retry.status_code == 409
    assert client.get('/api/moods', params={'session_id': sid}).json()['moods'] == [committed]
    client.delete('/api/moods/2026-10-30', params={'session_id': sid, 'expected_updated_at': committed['updated_at']})
    lost_delete_retry = client.delete('/api/moods/2026-10-30', params={
        'session_id': sid, 'expected_updated_at': committed['updated_at']})
    assert lost_delete_retry.status_code == 409 and lost_delete_retry.json()['current_updated_at'] is None
    assert client.get('/api/moods', params={'session_id': sid}).json()['moods'] == []


def test_mood_capabilities_are_additive_and_old_f5_flags_remain(client):
    response = client.get('/api/capabilities').json()
    assert response['contract_version'] == '1.8.0'
    for name in ['daily_mood_entries', 'mood_self_report_suggestions', 'companion_boundaries',
                 'bounded_followup_contact', 'unified_contact_claim', 'chat_delivery_targeted_stop',
                 'memory_expected_version_patch', 'memory_expected_version_delete']:
        assert response['features'][name] is True


@pytest.mark.parametrize('number', ['1e999', '-1e999', 'NaN'])
def test_non_finite_coordinate_is_422_not_serialization_failure(client, number):
    sid = client.get('/api/conversation').json()['session']['id']
    body = json.dumps(dict(session_id=sid, y=0, confirmed=True, expected_updated_at=None))
    body = body[:-1] + ',"x":' + number + '}'
    response = client.put('/api/moods/2026-10-30', content=body, headers={'Content-Type': 'application/json'})
    assert response.status_code == 422
    assert response.json()['error_code'] == 'validation_error'
    assert all('input' not in item for item in response.json()['detail'])
    assert client.get('/api/moods', params={'session_id': sid}).json()['moods'] == []


def test_non_finite_validation_fallback_keeps_old_chat_contract_and_normal_errors(client, monkeypatch):
    monkeypatch.setattr(core.model, 'from_env', lambda: pytest.fail('invalid input must not reach a model'))
    sid = client.get('/api/conversation').json()['session']['id']
    before = client.get('/api/conversation').json()
    body = json.dumps({'session_id': sid, 'text': '合成无效请求'})[:-1] + ',"memory_proposals":NaN}'
    invalid = client.post('/api/chat', content=body, headers={'Content-Type': 'application/json'})
    assert invalid.status_code == 422 and invalid.json()['error_code'] == 'validation_error'
    assert invalid.json()['detail'][0]['loc'] == ['body', 'memory_proposals']
    assert all('input' not in item for item in invalid.json()['detail'])
    normal = create(client, sid, x='not-a-number')
    assert normal.status_code == 422 and normal.json()['detail'][0]['input'] == 'not-a-number'
    assert client.get('/api/conversation').json() == before
