from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import sqlite3
import pytest
from fastapi.testclient import TestClient
from server import core, followups
from server.main import app

NOW = datetime(2026, 10, 30, 1, tzinfo=timezone.utc)

@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'synthetic.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE sessions(id TEXT PRIMARY KEY)')
        conn.execute('CREATE TABLE audit(id TEXT PRIMARY KEY,session_id TEXT,action TEXT,detail TEXT,reason TEXT,created_at TEXT)')
        conn.execute('INSERT INTO sessions VALUES(?)', ('one',))
        followups.init_schema(conn)
    return path


def test_daily_once_per_occurrence_and_restart(database):
    item = followups.create(database, 'one', '喝水', (NOW + timedelta(hours=1)).isoformat(), 'request',
                            repeat_rule='daily', time_zone='Asia/Shanghai', clock=lambda: NOW)
    clock = lambda: NOW + timedelta(hours=2)
    due = followups.list_for_session(database, 'one', clock=clock)[0]
    assert due['review_available']
    def complete(_):
        return followups.transition(database, 'one', item['id'], 'done', occurrence_at=due['due_at'], clock=clock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(complete, range(2)))
    assert first['due_at'] == second['due_at'] and first['last_occurrence_at'] == due['due_at']
    assert first['status'] == 'pending' and not first['due']
    assert datetime.fromisoformat(first['due_at']) == NOW + timedelta(days=1, hours=1)
    assert followups.create(database, 'one', '喝水', item['created_due_at'], 'request', repeat_rule='daily',
                            time_zone='Asia/Shanghai', clock=clock)['id'] == item['id']
    assert followups.list_for_session(database, 'one', clock=lambda: NOW + timedelta(days=2))[0]['review_available']


def test_pause_quiet_resume_and_cancel(database):
    item = followups.create(database, 'one', '走走', (NOW + timedelta(hours=1)).isoformat(), 'q',
                            repeat_rule='daily', time_zone='Asia/Shanghai', quiet_start='09:00', quiet_end='11:00', clock=lambda: NOW)
    assert followups.transition(database, 'one', item['id'], 'paused', clock=lambda: NOW)['paused']
    assert followups.transition(database, 'one', item['id'], 'paused', clock=lambda: NOW)['paused']
    clock = lambda: NOW + timedelta(hours=1, minutes=30)
    resumed = followups.transition(database, 'one', item['id'], 'resumed', clock=clock)
    assert resumed['due'] and resumed['quiet'] and not resumed['available'] and 'delivered' not in resumed
    # Quiet hours suppress interruptions, but do not prevent a manual completion.
    clock = lambda: NOW + timedelta(hours=3)
    assert followups.list_for_session(database, 'one', clock=clock)[0]['review_available']
    cancelled = followups.transition(database, 'one', item['id'], 'cancelled', clock=clock)
    assert cancelled['status'] == 'cancelled' and not cancelled['available']


def test_invalid_and_cross_session(database):
    due = (NOW + timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError):
        followups.create(database, 'one', 'x', due, 'a', time_zone='not/a-zone', clock=lambda: NOW)
    with pytest.raises(ValueError):
        followups.create(database, 'one', 'x', due, 'b', quiet_start='22:00', quiet_end=None, clock=lambda: NOW)
    item = followups.create(database, 'one', 'x', due, 'c', clock=lambda: NOW)
    with pytest.raises(LookupError):
        followups.transition(database, 'other', item['id'], 'paused', clock=lambda: NOW)


def test_dst_uses_wall_time():
    zone = followups._zone('America/New_York')
    initial = datetime.fromisoformat('2026-03-07T09:00:00-05:00').astimezone(timezone.utc)
    assert followups._next_daily(initial, initial + timedelta(hours=1), zone).astimezone(zone).isoformat() == '2026-03-08T09:00:00-04:00'


def test_http_consent_and_daily_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'isolated.db'))
    monkeypatch.setattr(followups, '_current', lambda clock: NOW)
    with TestClient(app) as client:
        sid = client.get('/api/conversation').json()['session']['id']
        body = {'session_id': sid, 'content': '散步', 'due_at': (NOW + timedelta(hours=1)).isoformat(),
                'request_id': 'daily-test-1234', 'repeat_rule': 'daily', 'time_zone': 'Asia/Shanghai', 'confirmed': False}
        assert client.post('/api/followups', json=body).status_code == 400
        body['confirmed'] = True
        item = client.post('/api/followups', json=body).json()
        assert item['repeat_rule'] == 'daily' and not item['due']
        assert client.patch('/api/followups/' + item['id'], json={'session_id':sid,'status':'paused'}).json()['paused']
        monkeypatch.setattr(followups, '_current', lambda clock: NOW + timedelta(hours=2))
        assert client.get('/api/followups', params={'session_id':sid}).json()['followups'][0]['paused']
        client.patch('/api/followups/' + item['id'], json={'session_id':sid,'status':'resumed'})
        change = {'session_id':sid,'status':'done','occurrence_at':item['due_at']}
        first = client.patch('/api/followups/' + item['id'], json=change)
        second = client.patch('/api/followups/' + item['id'], json=change)
        assert first.status_code == 200 and first.json() == second.json()
        assert first.json()['last_occurrence_at'] == item['due_at']


def test_manual_completion_allowed_during_quiet_hours(database):
    item = followups.create(database, 'one', '读书', (NOW + timedelta(hours=1)).isoformat(), 'quiet-manual',
                            repeat_rule='daily', time_zone='Asia/Shanghai', quiet_start='09:00', quiet_end='11:00', clock=lambda: NOW)
    clock = lambda: NOW + timedelta(hours=1, minutes=30)
    assert not followups.list_for_session(database, 'one', clock=clock)[0]['review_available']
    result = followups.transition(database, 'one', item['id'], 'done', occurrence_at=item['due_at'], clock=clock)
    assert result['last_occurrence_at'] == item['due_at'] and result['status'] == 'pending'
