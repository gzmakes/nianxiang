"""Notifications are opt-in, bounded attempts, tested with synthetic data only."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from server import core, followups
from server.main import app


def test_config_claim_recheck_and_session_deletion(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'isolated.db'))
    clock = [datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)]  # 14:00 in Shanghai
    monkeypatch.setattr(followups, '_current', lambda _: clock[0])
    with TestClient(app) as client:
        sid = client.get('/api/conversation').json()['session']['id']
        other = client.post('/api/session', json={'mode':'empty'}).json()['session']['id']
        url = '/api/followup-notification-settings'
        response = client.get(url, params={'session_id':sid})
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        assert response.json()['enabled'] is False and response.json()['configured'] is False
        assert client.get(url, params={'session_id':'missing'}).status_code == 404
        due = (clock[0] + timedelta(minutes=1)).isoformat()
        item = client.post('/api/followups', json={'session_id':sid, 'content':'合成跟进', 'due_at':due,
                           'request_id':'synthetic-request-1', 'confirmed':True,'allow_contact':True}).json()
        clock[0] += timedelta(minutes=2)
        claim_url = '/api/followups/' + item['id'] + '/desktop-notification/claim'
        body = {'session_id':sid, 'occurrence_at':due}
        assert client.post(claim_url, json=body).json()['reason'] == 'disabled'
        settings = {'session_id':sid,'enabled':True,'time_zone':'Asia/Shanghai','quiet_start':'22:00',
                    'quiet_end':'08:00','cooldown_minutes':60,'daily_limit':3,'pause_until':None,'expected_revision':0}
        assert client.put(url,json=settings,headers={'Origin':'https://attacker.invalid'}).status_code == 403
        assert client.put(url,json={**settings,'daily_limit':4}).status_code == 422
        saved = client.put(url,json=settings)
        assert saved.status_code == 200 and saved.json()['configured'] is True
        assert saved.json()['revision'] == 1
        assert client.put(url,json={**settings,'quiet_start':'21:00'}).status_code == 409
        assert client.get(url,params={'session_id':sid}).json()['quiet_start'] == '22:00'
        assert client.post(claim_url,json={**body,'session_id':other}).status_code == 404
        claim = client.post(claim_url,json=body).json()
        assert claim['claimed'] is True
        assert client.post(claim_url,json=body).json()['claimed'] is False
        claim_id = claim['claim_id']
        check = '/api/followup-notifications/' + claim_id + '/recheck'
        finish = '/api/followup-notifications/' + claim_id + '/finish'
        assert client.post(check,json={'session_id':other}).json()['allowed'] is False
        assert client.post(check,json={'session_id':sid}).json()['allowed'] is True
        assert client.post(check,json={'session_id':sid}).json()['allowed'] is False
        assert client.post(finish,json={'session_id':sid,'state':'submitted'}).json()['state'] == 'submitted'
        assert client.get('/api/followups',params={'session_id':sid}).json()['followups'][0]['status'] == 'pending'
        exported = core.export_data(sid)
        assert len(exported['followup_notification_settings']) == 1
        assert len(exported['followup_notification_attempts']) == 1
        deleted = core.delete_session(sid)['deleted']
        assert deleted['notification_settings'] == 1 and deleted['notification_attempts'] == 1
        assert core.get_session(other)


def test_disable_or_item_cancel_before_recheck_prevents_invocation(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'isolated.db'))
    clock = [datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)]
    monkeypatch.setattr(followups, '_current', lambda _: clock[0])
    with TestClient(app) as client:
        sid = client.get('/api/conversation').json()['session']['id']
        settings = {'session_id':sid,'enabled':True,'time_zone':'Asia/Shanghai','quiet_start':'22:00',
                    'quiet_end':'08:00','cooldown_minutes':60,'daily_limit':3,'pause_until':None,'expected_revision':0}
        assert client.put('/api/followup-notification-settings',json=settings).status_code == 200
        due=(clock[0]+timedelta(minutes=1)).isoformat()
        item=client.post('/api/followups',json={'session_id':sid,'content':'合成跟进','due_at':due,
                         'request_id':'synthetic-request-2','confirmed':True,'allow_contact':True}).json()
        clock[0]+=timedelta(minutes=2)
        result=client.post('/api/followups/'+item['id']+'/desktop-notification/claim',json={'session_id':sid,'occurrence_at':due}).json()
        assert result['claimed'] is True
        assert client.put('/api/followup-notification-settings',json={**settings,'enabled':False,'expected_revision':1}).status_code == 200
        check=client.post('/api/followup-notifications/'+result['claim_id']+'/recheck',json={'session_id':sid}).json()
        assert check == {'allowed':False,'reason':'settings_changed'}
        assert client.post('/api/followup-notifications/'+result['claim_id']+'/finish',json={'session_id':sid,'state':'submitted'}).status_code == 409
