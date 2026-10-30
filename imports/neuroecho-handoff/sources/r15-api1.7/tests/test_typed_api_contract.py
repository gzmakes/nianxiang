"""Public response contracts preserve legacy/extension fields and expose honest capabilities."""
from fastapi.testclient import TestClient
import pytest
from types import SimpleNamespace

from server import api_contract, apple_source, core, main, real_sources


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'contracts.db'))
    core.init_db()
    return TestClient(main.app)


def test_core_responses_are_typed_including_pending_and_cas_error(client):
    schema = client.get('/openapi.json').json()
    critical = [('/api/conversation','get'),('/api/chat','post'),('/api/chat/turn/{request_id}','get'),
                ('/api/memory','post'),('/api/memory/{mid}','patch'),('/api/memory/{mid}','delete'),
                ('/api/local-files/confirm','post'),('/api/lark/preview','post'),('/api/source/revoke','post'),
                ('/api/action','post'),('/api/actions','get'),('/api/action/{aid}/commit','post')]
    for path, method in critical:
        response_schema = schema['paths'][path][method]['responses']['200']['content']['application/json']['schema']
        assert response_schema.get('$ref'), (method, path)
    assert schema['paths']['/api/chat']['post']['responses']['202']['content']['application/json']['schema']['$ref'].endswith('/ChatTurnResponse')
    assert schema['paths']['/api/memory/{mid}']['patch']['responses']['409']['content']['application/json']['schema']['$ref'].endswith('/ErrorResponse')
    assert 'expected_version' in schema['components']['schemas']['MemoryPatch']['properties']
    assert schema['components']['schemas']['ActionResponse']['additionalProperties'] is True


def test_conversation_schema_does_not_drop_or_invent_fields_at_any_depth(client, monkeypatch):
    sid = core.conversation_id()
    core.add_memory(sid, 'fact', '合成偏好', source='用户手动添加')
    original_session, original_messages, original_memories = core.get_session, core.get_messages, core.list_memories
    monkeypatch.setattr(core, 'get_session', lambda value: {**original_session(value), 'future_session': {'enabled': False, 'value': 0}})
    monkeypatch.setattr(core, 'get_messages', lambda value: [{**item, 'future_message': {'nested': None}} for item in original_messages(value)])
    monkeypatch.setattr(core, 'list_memories', lambda value: [{**item, 'future_memory': ['kept']} for item in original_memories(value)])
    monkeypatch.setattr(core, 'get_session_context', lambda value: {'connector_id':'synthetic', 'future_context':False,
                         'sources':[{'id':'synthetic-source', 'stale':False, 'future_source':{'value':0}}]})
    assert client.get('/api/conversation').json() == main.conversation()


def test_attach_and_revoke_preserve_existing_source_payload_fields(client):
    sid = client.get('/api/conversation').json()['session']['id']
    result = client.post('/api/local-files/confirm', json={'session_id':sid,'files':[{'name':'合成资料.txt','text':'这是一份合成资料。'}]})
    assert result.status_code == 200
    data = result.json()
    assert 'insights' in data and 'context' in data
    source = data['context']['sources'][0]
    assert source['items'][0]['title'] == '合成资料.txt' and source['stale'] is False
    result = client.post('/api/source/revoke',json={'session_id':sid,'source_id':source['id']})
    assert result.status_code == 200 and result.json()['revoked_source_ids'] == [source['id']]
    assert result.json()['remaining_sources'] == 0


def test_chat_turn_contract_covers_same_id_pending_completion_and_conflict(client):
    sid = client.get('/api/conversation').json()['session']['id']
    body = {'session_id':sid,'text':'记住：合成的咖啡偏好','request_id':'contract-turn-completed'}
    result = client.post('/api/chat',json=body)
    assert result.status_code == 200 and result.json()['request_id'] == body['request_id']
    turn = client.get(f"/api/chat/turn/{body['request_id']}?session_id={sid}").json()
    assert turn['status'] == 'completed' and turn['result']['messages'] == result.json()['messages']
    assert client.post('/api/chat',json=body).json() == turn['result']
    conflict = client.post('/api/chat',json={**body,'text':'另一个不同的合成输入'})
    assert conflict.status_code == 409 and conflict.json()['error_code'] == 'request_id_conflict'
    pending = {**body,'request_id':'contract-turn-pending'}
    main._turn_store().claim(sid,pending['request_id'],pending['text'],options={'memory_proposals':False})
    result = client.post('/api/chat',json=pending)
    assert result.status_code == 202 and result.json()['status'] == 'running'
    assert result.json()['request_id'] == pending['request_id']


def test_action_contract_preserves_fields_and_future_state_without_claiming_success(client, monkeypatch):
    sid = client.get('/api/conversation').json()['session']['id']
    original = core.create_action
    monkeypatch.setattr(core,'create_action',lambda *args: {**original(*args),'future_action':{'value':False}})
    result = client.post('/api/action',json={'session_id':sid,'kind':'message','title':'合成草稿','detail':'尚未发送的内容'})
    assert result.status_code == 200 and result.json()['future_action'] == {'value':False}
    aid = result.json()['id']
    committed = client.post(f'/api/action/{aid}/commit',json={'real':False}).json()
    assert committed['status'] == 'committed' and committed['real'] == 0
    assert committed == {**core.list_actions(sid)[0], 'error':''}
    with core.get_db() as connection:
        connection.execute("UPDATE actions SET status='future_state_v2' WHERE id=?",(aid,))
    assert client.get(f'/api/actions?session_id={sid}').json()['actions'][0]['status'] == 'future_state_v2'


def test_capabilities_do_not_access_accounts_hardware_or_database(client, monkeypatch):
    def forbidden(*args,**kwargs):
        raise AssertionError('Capability metadata must not probe or authorize anything')
    monkeypatch.setattr(real_sources,'sources',forbidden)
    monkeypatch.setattr(apple_source,'_run',forbidden)
    monkeypatch.setattr(core,'get_db',forbidden)
    result = client.get('/api/capabilities')
    assert result.status_code == 200
    data = result.json()
    assert data['contract_version'] == api_contract.CONTRACT_VERSION
    assert data['features']['memory_expected_version_patch'] is True
    assert data['features']['memory_expected_version_delete'] is True
    assert data['features']['remote_user_authentication'] is False
    assert data['features']['realtime_multi_device_sync'] is False
    assert data['connection_status'] == 'not_probed'


def test_platform_capabilities_and_catalog_do_not_offer_apple_permissions_on_windows(client, monkeypatch):
    monkeypatch.setattr(api_contract,'sys',SimpleNamespace(platform='win32'))
    monkeypatch.setattr(apple_source,'platform_supported',lambda:False)
    monkeypatch.setattr(real_sources,'_lark_ready',lambda:(False,'合成未授权'))
    monkeypatch.setattr(real_sources.git_source,'repos',lambda:[])
    monkeypatch.setattr(real_sources.github_source,'status',lambda:{'ok':False,'status':'needs_install'})
    monkeypatch.setattr(real_sources.notion_cli_source,'status',lambda:{'hint':'合成未配置'})
    data = client.get('/api/capabilities').json()
    assert data['platform_status']['apple_calendar'] == 'platform_unsupported'
    assert data['features']['service_apple_calendar_reminders'] is False
    sources = client.get('/api/onboarding/sources?force=true').json()['sources']
    for item in sources:
        if item['id'] in ('apple_calendar','apple_reminders'):
            assert item['status'] == 'platform_unsupported' and 'macOS' in item['hint']
    monkeypatch.setattr(apple_source,'_run',lambda script:pytest.fail('Do not launch osascript on unsupported hosts'))
    for read in (apple_source.read_calendar,apple_source.read_reminders):
        assert read()['error_code'] == 'platform_unsupported'


def test_source_failure_and_preview_expiry_have_codes_without_losing_legacy_messages(client, monkeypatch):
    monkeypatch.setattr(real_sources,'read',lambda value:{'ok':False,'error':'合成来源不可用','hint':'核对条件','future_source':False})
    result = client.post('/api/onboarding/real/read',json={'source_id':'synthetic'})
    assert result.json()['error_code'] == 'source_unavailable' and result.json()['future_source'] is False
    assert result.json()['error'] == '合成来源不可用' and 'preview_id' not in result.json()
    result = client.post('/api/onboarding/real/start',json={'source_id':'synthetic','preview_id':'missing'})
    assert result.status_code == 400 and result.json()['error_code'] == 'source_preview_expired'
    assert isinstance(result.json()['detail'],str)
