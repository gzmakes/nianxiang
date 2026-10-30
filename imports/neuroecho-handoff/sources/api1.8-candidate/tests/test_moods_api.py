"""End-to-end mood behaviour uses only an isolated temporary database."""
from fastapi.testclient import TestClient
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest

from server import core
from server.main import app


def test_daily_user_judgement_is_confirmed_editable_and_deletable():
    with TestClient(app) as client:
        sid = client.get('/api/conversation').json()['session']['id']
        other = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
        path = '/api/moods/2026-10-30'
        body = {'session_id': sid, 'x': 0.3, 'y': -0.4, 'note': '合成的一天', 'confirmed': False, 'expected_updated_at': None}
        assert client.put(path, json=body).status_code == 400
        assert client.get('/api/moods', params={'session_id': sid}).json()['moods'] == []
        assert client.put(path, json={**body, 'confirmed': True}, headers={'Origin': 'https://evil.invalid'}).status_code == 403
        saved = client.put(path, json={**body, 'confirmed': True})
        assert saved.status_code == 200 and saved.json()['x'] == .3
        assert client.put('/api/moods/2026-02-30', json={**body, 'confirmed': True}).status_code == 400
        assert client.put(path, json={**body, 'confirmed': True, 'x': 1.1}).status_code == 422
        assert client.put(path, json={**body, 'confirmed': True, 'x': True}).status_code == 422
        stale = saved.json()['updated_at']
        changed = client.put(path, json={**body, 'confirmed': True, 'expected_updated_at': stale, 'x': -.5})
        assert changed.json()['x'] == -.5
        latest = changed.json()['updated_at']
        assert latest != stale
        assert client.put(path, json={**body, 'confirmed': True, 'expected_updated_at': stale}).status_code == 409
        assert client.delete(path, params={'session_id': sid, 'expected_updated_at': stale}).status_code == 409
        assert len(client.get('/api/moods', params={'session_id': sid}).json()['moods']) == 1
        assert client.get('/api/moods', params={'session_id': other}).json()['moods'] == []
        assert len(core.export_data(sid)['mood_entries']) == 1
        assert client.delete(path, params={'session_id': other, 'expected_updated_at': latest}).status_code == 409
        assert client.delete(path, params={'session_id': sid, 'expected_updated_at': latest}).json()['deleted'] is True
        assert core.export_data(sid)['mood_entries'] == []
        recreated = client.put(path, json={**body, 'confirmed': True})
        assert recreated.status_code == 200 and recreated.json()['updated_at'] != latest
        assert client.put(path, json={**body, 'confirmed': True, 'expected_updated_at': latest}).status_code == 409
        assert client.delete(path, params={'session_id': sid, 'expected_updated_at': latest}).status_code == 409
        assert core.delete_session(sid)['deleted']['mood_entries'] == 1


def test_concurrent_creation_allows_one_writer_and_preserves_its_record():
    with TestClient(app) as client:
        sid = client.get('/api/conversation').json()['session']['id']
        barrier = Barrier(2)
        def create(x):
            barrier.wait(timeout=5)
            return client.put('/api/moods/2026-10-30', json={'session_id': sid, 'x': x, 'y': 0,
                              'confirmed': True, 'expected_updated_at': None})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, [-.5, .5]))
        assert sorted(item.status_code for item in results) == [200, 409]
        winner = next(item.json() for item in results if item.status_code == 200)
        assert client.get('/api/moods', params={'session_id': sid}).json()['moods'][0] == winner


def test_suggestions_are_opt_in_ephemeral_and_leave_unknown_axis_unset():
    with TestClient(app) as client:
        sid = client.get('/api/conversation').json()['session']['id']
        body = {'session_id': sid, 'text': '我今天很开心', 'consent': False}
        assert client.post('/api/mood-suggestions', json=body).status_code == 400
        response = client.post('/api/mood-suggestions', json={**body, 'consent': True})
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        assert response.json()['suggestion']['x'] == .6
        assert response.json()['suggestion']['y'] is None
        assert response.json()['suggestion']['evidence'] == ['我今天很开心']
        assert client.get('/api/moods', params={'session_id': sid}).json()['moods'] == []
        assert core.export_data(sid)['mood_entries'] == []
        both = client.post('/api/mood-suggestions', json={**body, 'consent': True, 'text': '我今天很开心，而且很累'}).json()
        assert both['suggestion']['x'] == .6 and both['suggestion']['y'] == -.6
        assert '专注度不能直接推断情绪' in both['limitations'][1]
        assert client.post('/api/mood-suggestions', json={**body, 'session_id': 'missing', 'consent': True}).status_code == 404


@pytest.mark.parametrize('text', [
    '我今天不开心', '我今天开心吗？', '他说“我今天开心”', '我今天开心，但是后来很难过',
    '我今天开心，难过', '我今天心情还好', '设备显示我今天很开心', '我今天很开心和很累',
])
def test_ambiguous_negated_quoted_or_mixed_statements_abstain(text):
    with TestClient(app) as client:
        sid = client.get('/api/conversation').json()['session']['id']
        response = client.post('/api/mood-suggestions', json={'session_id': sid, 'text': text, 'consent': True})
        assert response.status_code == 200 and response.json()['suggestion'] is None
