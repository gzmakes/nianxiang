from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from server import core, followups
from server.main import app


def test_followup_consent_idempotency_restart_and_removal(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'isolated.db'))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(followups, '_current', lambda clock: now)
    with TestClient(app) as client:
        sid = client.get('/api/conversation').json()['session']['id']
        other = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
        body = {'session_id': sid, 'content': '聊聊今天', 'due_at': (now + timedelta(minutes=5)).isoformat(),
                'request_id': 'request-0001', 'confirmed': False}
        assert client.post('/api/followups', json=body).status_code == 400
        assert client.get('/api/followups', params={'session_id': sid}).json()['followups'] == []
        body['confirmed'] = True
        response = client.post('/api/followups', json=body)
        assert response.status_code == 200
        item = response.json()
        assert not item['due'] and item['status'] == 'pending'
        assert client.post('/api/followups', json=body).json()['id'] == item['id']
        assert client.post('/api/followups', json={**body, 'content': '不同内容'}).status_code == 409
        assert client.post('/api/followups', json={**body, 'request_id': 'request-0002', 'due_at': '2026-01-01T12:00:00'}).status_code == 400
        assert client.post('/api/followups', json=body, headers={'Origin': 'https://example.com'}).status_code == 403
        assert client.patch('/api/followups/' + item['id'], json={'session_id': other, 'status': 'done'}).status_code == 404
        assert len(core.export_data(sid)['followups']) == 1

    monkeypatch.setattr(followups, '_current', lambda clock: now + timedelta(minutes=6))
    with TestClient(app) as client:
        item = client.get('/api/followups', params={'session_id': sid}).json()['followups'][0]
        assert item['due'] is True
        assert client.post('/api/followups', json=body).json()['id'] == item['id']
        done = client.post('/api/followups/' + item['id'] + '/transition', json={'session_id': sid, 'status': 'done'})
        assert done.json()['status'] == 'done' and done.json()['due'] is False
        assert client.patch('/api/followups/' + item['id'], json={'session_id': sid, 'status': 'cancelled'}).status_code == 409
        assert core.delete_session(sid)['deleted']['followups'] == 1
        assert core.export_data(sid)['followups'] == []
        assert core.get_session(other)


def test_missing_session_and_future_time_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'isolated.db'))
    now = datetime.now(timezone.utc)
    with TestClient(app) as client:
        body = {'session_id': 'missing', 'content': '跟进', 'due_at': (now + timedelta(hours=1)).isoformat(),
                'request_id': 'request-0003', 'confirmed': True}
        assert client.post('/api/followups', json=body).status_code == 404
        sid = client.get('/api/conversation').json()['session']['id']
        assert client.post('/api/followups', json={**body, 'session_id': sid, 'due_at': (now - timedelta(hours=1)).isoformat()}).status_code == 400
        assert client.get('/api/followups', params={'session_id': 'missing'}).status_code == 404


@pytest.mark.parametrize('method,suffix', [('PATCH',''), ('POST','/transition')])
def test_transition_alias_preserves_session_origin_validation_and_idempotency(tmp_path, monkeypatch, method, suffix):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'transition-contract.db'))
    now = datetime.now(timezone.utc)
    with TestClient(app) as client:
        sid = client.get('/api/conversation').json()['session']['id']
        other = client.post('/api/session', json={'mode':'empty'}).json()['session']['id']
        created = client.post('/api/followups', json={'session_id':sid,'content':'合成跟进',
                              'due_at':(now+timedelta(hours=1)).isoformat(),'request_id':'transition-test-0001','confirmed':True}).json()
        path = '/api/followups/' + created['id'] + suffix
        body = {'session_id':sid,'status':'cancelled'}
        assert client.request(method,path,json={**body,'session_id':other}).status_code == 404
        invalid = client.request(method,path,json={**body,'status':'delivered'})
        assert invalid.status_code == 422 and invalid.json()['error_code'] == 'validation_error'
        assert client.request(method,path,json=body,headers={'Origin':'https://example.invalid'}).status_code == 403
        assert client.get('/api/followups',params={'session_id':sid}).json()['followups'][0]['status'] == 'pending'
        first = client.request(method,path,json=body)
        assert first.status_code == 200 and first.json()['status'] == 'cancelled' and first.json()['due'] is False
        assert client.request(method,path,json=body).json() == first.json()
        conflict = client.request(method,path,json={**body,'status':'done'})
        assert conflict.status_code == 409 and conflict.json()['error_code'] == 'followup_conflict'
        with core.get_db() as connection:
            assert connection.execute("SELECT COUNT(*) FROM audit WHERE session_id=? AND action='followup.cancelled'",(sid,)).fetchone()[0] == 1
