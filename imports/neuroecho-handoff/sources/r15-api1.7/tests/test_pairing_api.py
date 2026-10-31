"""Temporary DB, synthetic credentials, no model/CLI/OS/network permissions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import json
import sqlite3
from threading import Event

from fastapi.testclient import TestClient
import pytest

from server import core,main,paired_access,paired_app


@pytest.fixture
def clients():
    with TestClient(main.app) as owner:
        created=owner.post('/api/paired-devices',json={'label':'合成手机','expires_in_seconds':604800,'confirmed':True})
        assert created.status_code==201
        grant=created.json()
        remote=TestClient(paired_app.create_remote_app(main.app,lambda:core.DB_PATH,allowed_origins={'https://phone.test'}),base_url='https://phone.test',client=('192.0.2.10',4000))
        yield owner,remote,grant
        remote.close()


def headers(grant,**extra):
    return {'Authorization':'Bearer '+grant['token'],'X-Echo-Service-Instance':grant['service_instance_id'],**extra}


def test_owner_once_plaintext_hashed_storage_list_revoke_and_restart(clients):
    owner,remote,grant=clients
    assert paired_access.TOKEN.fullmatch(grant['token'])
    listed=owner.get('/api/paired-devices');assert listed.status_code==200
    assert listed.headers['cache-control']=='no-store'
    assert grant['token'] not in listed.text and 'token_hash' not in listed.text
    with sqlite3.connect(core.DB_PATH) as conn:
        stored=conn.execute('SELECT token_hash FROM paired_devices WHERE id=?',(grant['device']['id'],)).fetchone()[0]
    assert stored==hashlib.sha256(grant['token'].encode()).hexdigest()
    assert paired_access.authenticate(core.DB_PATH,'Bearer '+grant['token']) is not None
    paired_access.initialize(core.DB_PATH)
    assert paired_access.instance_id(core.DB_PATH)==grant['service_instance_id']
    body={'confirmed':True};path='/api/paired-devices/'+grant['device']['id']+'/revoke'
    assert owner.post(path,json=body).json()['in_flight_may_have_committed'] is True
    assert owner.post(path,json=body).json()['revoked'] is True
    assert remote.get('/api/paired-device',headers=headers(grant)).status_code==401
    assert 'paired_devices' not in core.export_data(grant['conversation_id'])


def test_verify_instance_header_tls_origin_and_token_errors_never_echo(clients):
    owner,remote,grant=clients;auth={'Authorization':'Bearer '+grant['token']}
    first=remote.get('/api/paired-device',headers=auth);assert first.status_code==200
    assert first.json()=={k:v for k,v in grant.items() if k!='token'}
    assert first.headers['cache-control']=='no-store'
    assert remote.get('/api/conversation',headers=auth).json()['error_code']=='service_instance_required'
    mismatch=remote.get('/api/paired-device',headers=headers(grant,**{'X-Echo-Service-Instance':'svc_other'}))
    assert mismatch.status_code==409 and mismatch.json()['error_code']=='service_instance_mismatch'
    for value in ('Bearer invalid',grant['token'],'bearer '+grant['token'],'Bearer '+grant['token']+'x'):
        response=remote.get('/api/paired-device',headers={'Authorization':value})
        assert response.status_code==401 and grant['token'] not in response.text
        assert response.headers['cache-control']=='no-store'
    assert remote.get('/api/paired-device',headers=headers(grant,Origin='https://evil.invalid')).status_code==403
    assert remote.get('/api/paired-device',headers=headers(grant,**{'X-Forwarded-Proto':'https'})).status_code==403
    assert remote.get('/api/paired-device?token='+grant['token'],headers=headers(grant)).status_code==403
    assert remote.get('http://phone.test/api/paired-device',headers=headers(grant)).json()['error_code']=='paired_https_required'


@pytest.mark.parametrize('method,path',[
    ('GET','/api/settings/model'),('POST','/api/settings/model/test'),('POST','/api/settings/model/clear'),
    ('GET','/api/lark/status'),('POST','/api/lark/preview'),('POST','/api/onboarding/real/read'),
    ('POST','/api/auth/lark/setup'),('POST','/api/notion/preview'),('POST','/api/action'),
    ('POST','/api/action/unknown/commit'),('POST','/api/mindlink/start'),('GET','/api/device/frame'),
    ('POST','/api/followups/unknown/contact/claim'),('GET','/api/followup-notification-settings'),
    ('GET','/api/paired-devices'),('POST','/api/paired-devices'),('GET','/api/export'),
    ('POST','/api/session'),('DELETE','/api/session/unknown'),('GET','/api/sessions'),
    ('GET','/download/source'),('GET','/docs'),('GET','/openapi.json'),('GET','/api/unknown'),
    ('POST','/api/conversation'),('GET','/api/%70aired-devices'),('GET','/api//conversation')])
def test_default_deny_privileged_methods_paths_and_aliases(clients,method,path):
    _,remote,grant=clients
    response=remote.request(method,path,headers=headers(grant),json={'real':False,'confirmed':True})
    assert response.status_code==403
    assert response.json()['error_code']=='paired_operation_forbidden'


def test_safe_capabilities_sources_without_any_probe_and_spoof_header_no_bypass(clients,monkeypatch):
    owner,remote,grant=clients
    monkeypatch.setattr(main.real_sources,'sources',lambda **_:pytest.fail('CLI/source probe forbidden'))
    cap=remote.get('/api/capabilities',headers=headers(grant)).json()
    assert cap['deployment_mode']=='paired_single_owner' and cap['features']['remote_user_authentication'] is True
    for key in ('service_apple_calendar_reminders','action_preview_confirmation','voice_clip_from_assistant_message','paired_device_management','bounded_followup_contact'):
        assert cap['features'][key] is False
    assert [r['id'] for r in remote.get('/api/onboarding/sources',headers=headers(grant)).json()['sources']]==['local_files']
    untrusted=TestClient(main.app,base_url='http://127.0.0.1:18787',client=('192.0.2.20',9999))
    try:
        response=untrusted.get('/api/conversation',headers={**headers(grant),'X-Remote-Principal':'true','X-Forwarded-For':'127.0.0.1'})
        assert response.status_code==403
    finally:untrusted.close()


def test_canonical_sid_and_resource_ownership_missing_upload_sid_are_denied(clients):
    owner,remote,grant=clients;sid=grant['conversation_id'];h=headers(grant)
    other=owner.post('/api/session',json={'mode':'empty'}).json()['session']['id']
    memory=owner.post('/api/memory',json={'session_id':other,'kind':'fact','text':'other synthetic memory'}).json()
    for method,path,body in [('GET','/api/memory?session_id='+other,None),('POST','/api/memory',{'session_id':other,'kind':'fact','text':'x'}),('GET','/api/session/'+other,None),('GET','/api/memory/'+memory['id']+'/history',None),('PATCH','/api/memory/'+memory['id'],{'text':'overwrite'}),('DELETE','/api/memory/'+memory['id'],None),('POST','/api/local-files/confirm',{'files':[{'name':'test.txt','text':'selected'}]})]:
        assert remote.request(method,path,headers=h,json=body).status_code==403
    assert remote.get('/api/conversation',headers=h).json()['session']['id']==sid
    assert remote.post('/api/chat',headers=h,json={'session_id':sid,'text':'x'}).status_code==400
    assert remote.post('/api/memory',headers=h,content='{"session_id":"'+other+'","session_id":"'+sid+'"}').status_code==400


def test_remote_core_real_db_memory_mood_ledger_upload_revoke_and_passive_followup(clients):
    _,remote,g=clients;h=headers(g);sid=g['conversation_id']
    row=remote.post('/api/memory',headers=h,json={'session_id':sid,'kind':'fact','text':'synthetic preference'}).json()
    changed=remote.patch('/api/memory/'+row['id'],headers=h,json={'text':'corrected','expected_version':row['version']});assert changed.status_code==200
    assert remote.patch('/api/memory/'+row['id'],headers=h,json={'text':'stale','expected_version':row['version']}).status_code==409
    raw=json.dumps({'kind':'save','date':'2026-10-30','expected_updated_at':None,'x':.2,'y':-.2,'note':'synthetic'},ensure_ascii=False)
    body={'session_id':sid,'request_id':'mood-remote-123','operation_json':raw,'confirmed':True}
    applied=remote.post('/api/mood-operations',headers=h,json=body);assert applied.status_code==200 and applied.json()['state']=='applied'
    assert remote.post('/api/mood-operations',headers=h,json=body).json()==applied.json()
    assert remote.get('/api/mood-operations/mood-remote-123',headers=h,params={'session_id':sid}).json()==applied.json()
    attached=remote.post('/api/local-files/confirm',headers=h,json={'session_id':sid,'files':[{'name':'selected.txt','text':'only selected synthetic content'}]})
    assert attached.status_code==200
    source=attached.json()['context']['sources'][0]
    assert remote.post('/api/source/revoke',headers=h,json={'session_id':sid,'source_id':source['id']}).status_code==200
    tasks=remote.get('/api/followups',headers=h,params={'session_id':sid});assert tasks.status_code==200
    assert remote.get('/api/companion-boundary',headers=h,params={'session_id':sid}).status_code==200


def test_remote_chat_idempotency_and_model_never_implicitly_executes_local_tools(clients,monkeypatch):
    _,remote,g=clients;calls=[]
    def reply(sid,text,**kwargs):
        calls.append(text)
        return {'reply':'synthetic bounded answer','action':'model.reply','state':'listening','user_message_id':'msg_synthetic','messages':[],'memories':[]}
    monkeypatch.setattr(core,'generate_reply',reply)
    body={'session_id':g['conversation_id'],'request_id':'remote-turn-001','text':'synthetic'}
    assert remote.post('/api/chat',headers=headers(g),json=body).status_code==200
    assert remote.post('/api/chat',headers=headers(g),json=body).status_code==200
    assert calls==['synthetic']
    assert remote.post('/api/chat',headers=headers(g),json={**body,'text':'changed'}).status_code==409


def test_revocation_during_inflight_discards_sensitive_response_but_does_not_fake_rollback(clients,monkeypatch):
    owner,remote,g=clients;entered=Event();release=Event()
    def reply(sid,text,**kwargs):
        core.add_memory(sid,'fact','committed before revoke')
        entered.set();assert release.wait(5)
        return {'reply':'SENSITIVE_SYNTHETIC_LATE','action':'model.reply','state':'listening','user_message_id':'msg_synthetic','messages':[],'memories':[]}
    monkeypatch.setattr(core,'generate_reply',reply)
    with ThreadPoolExecutor(1) as pool:
        future=pool.submit(remote.post,'/api/chat',headers=headers(g),json={'session_id':g['conversation_id'],'request_id':'inflight-remote-01','text':'synthetic'})
        assert entered.wait(5)
        response=owner.post('/api/paired-devices/'+g['device']['id']+'/revoke',json={'confirmed':True})
        assert response.json()['in_flight_may_have_committed'] is True
        release.set();response=future.result(timeout=5)
    assert response.status_code==401 and 'SENSITIVE' not in response.text
    assert any(m['text']=='committed before revoke' for m in core.list_memories(g['conversation_id']))


def test_expiry_and_deleted_canonical_do_not_follow_new_conversation(clients,monkeypatch):
    _,remote,g=clients
    monkeypatch.setattr(paired_access,'_now',lambda:__import__('datetime').datetime.fromisoformat(g['device']['expires_at'])+timedelta(seconds=1))
    assert remote.get('/api/paired-device',headers=headers(g)).status_code==401


def test_deleted_canonical_credentials_fail_even_after_new_canonical_created(clients):
    owner,remote,g=clients
    owner.delete('/api/session/'+g['conversation_id'])
    new=owner.get('/api/conversation').json()['session']['id'];assert new!=g['conversation_id']
    assert remote.get('/api/paired-device',headers=headers(g)).status_code==401


def test_pairing_errors_confirmation_and_oversize_are_private(clients):
    owner,remote,g=clients
    assert owner.post('/api/paired-devices',json={'label':'x','confirmed':False}).status_code==400
    response=owner.post('/api/paired-devices',json={'label':'x','confirmed':True,'token':g['token']})
    assert response.status_code==422 and g['token'] not in response.text
    assert remote.post('/api/local-files/preview-document',headers={**headers(g),'Content-Length':str(paired_app.MAX_REQUEST_BYTES+1)},content=b'{}').status_code==413
    assert remote.get('/api/paired-device',headers=[*headers(g).items(),('Authorization','Bearer invalid')]).status_code==401


def test_principal_never_follows_changed_instance_conversation_or_bad_expiry(clients):
    _,remote,g=clients
    principal=paired_access.authenticate(core.DB_PATH,'Bearer '+g['token']);assert paired_access.active(principal)
    with sqlite3.connect(core.DB_PATH) as conn:conn.execute("UPDATE paired_service SET instance_id='svc_replaced'")
    assert not paired_access.active(principal) and paired_access.public_principal(principal) is None
    with sqlite3.connect(core.DB_PATH) as conn:
        conn.execute('UPDATE paired_service SET instance_id=?',(g['service_instance_id'],))
        conn.execute("UPDATE paired_devices SET expires_at='invalid' WHERE id=?",(g['device']['id'],))
    assert not paired_access.active(principal) and paired_access.public_principal(principal) is None
    assert remote.get('/api/paired-device',headers=headers(g)).status_code==401
    other=core.create_session('empty')['session']['id']
    with sqlite3.connect(core.DB_PATH) as conn:
        conn.execute('UPDATE paired_devices SET expires_at=?,conversation_id=? WHERE id=?',(g['device']['expires_at'],other,g['device']['id']))
        conn.execute("UPDATE app_state SET value=? WHERE key='canonical_conversation'",(other,))
    assert not paired_access.active(principal) and paired_access.public_principal(principal) is None


def test_paired_chat_accepts_valid_image_over_three_mib_but_other_limits_remain(clients, monkeypatch):
    import base64
    import random
    from io import BytesIO
    from PIL import Image
    _, remote, grant = clients
    sid = grant['conversation_id']
    seen = []
    class Fake:
        model = 'synthetic'
        def complete(self, system, user, **kwargs):
            seen.append(kwargs.get('image_data_url'))
            return '合成图片。'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    pixels = random.Random(42).randbytes(1100 * 1100 * 3)
    output = BytesIO()
    Image.frombytes('RGB', (1100, 1100), pixels).save(output, format='PNG')
    raw = output.getvalue()
    assert 3 * 1024 * 1024 < len(raw) < 4 * 1024 * 1024
    image = 'data:image/png;base64,' + base64.b64encode(raw).decode()
    response = remote.post('/api/chat', headers=headers(grant), json={
        'session_id':sid, 'request_id':'synthetic-large-picture', 'text':'看看', 'image_data_url':image})
    assert response.status_code == 200 and seen == [image]
    too_large = remote.post('/api/chat', headers=headers(grant), content=b' ' * (6 * 1024 * 1024 + 1))
    assert too_large.status_code == 413
    other = remote.post('/api/memory', headers=headers(grant), content=b' ' * (3 * 1024 * 1024 + 1))
    assert other.status_code == 413
