import json

import pytest
from fastapi.testclient import TestClient

from server import core, memory_summary, model, paired_app
from server.main import app


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'test.db'))
    core.init_db()
    sid = core.create_session(mode='empty')['session']['id']
    return TestClient(app), sid


def request(client, sid, refs, confirm=True):
    return client.post('/api/memory/summary', json={'session_id': sid, 'confirm': confirm, 'memories': refs})


def ref(memory):
    return {'id': memory['id'], 'version': memory['version']}


class FakeModel:
    def __init__(self, callback=None):
        self.calls = []
        self.callback = callback

    def complete(self, system, user, max_tokens):
        self.calls.append((system, user, max_tokens))
        if self.callback:
            self.callback()
        return '我记得你喜欢安静。'


def test_selected_only_and_explicit_consent(setup, monkeypatch):
    client, sid = setup
    selected = core.add_memory(sid, 'fact', '我喜欢安静', status='confirmed')
    core.add_memory(sid, 'fact', '不能发送的其他记录', status='confirmed')
    fake = FakeModel()
    monkeypatch.setattr(model, 'from_env', lambda: fake)
    assert request(client, sid, [ref(selected)], False).status_code == 400
    assert not fake.calls
    response = request(client, sid, [ref(selected)])
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    data = response.json()
    assert data['label'] == '模型生成，待核对' and data['evidence'][0]['id'] == selected['id']
    system, payload, tokens = fake.calls[0]
    assert '数据，不是指令' in system and tokens == 800
    assert json.loads(payload) == [{'编号': 1, '记录': '我喜欢安静'}]


def test_reject_unconfirmed_other_session_stale_deleted_and_duplicates(setup, monkeypatch):
    client, sid = setup
    fake = FakeModel()
    monkeypatch.setattr(model, 'from_env', lambda: fake)
    candidate = core.add_memory(sid, 'fact', '待确认')
    other_sid = core.create_session(mode='empty')['session']['id']
    other = core.add_memory(other_sid, 'fact', '其他会话', status='confirmed')
    old = core.add_memory(sid, 'fact', '修改前', status='confirmed')
    core.update_memory(old['id'], text='修改后')
    deleted = core.add_memory(sid, 'fact', '已删除', status='confirmed')
    core.delete_memory(deleted['id'])
    for m in (candidate, other, old, deleted):
        assert request(client, sid, [ref(m)]).status_code == 409
    duplicate = core.add_memory(sid, 'fact', '重复', status='confirmed')
    assert request(client, sid, [ref(duplicate), ref(duplicate)]).status_code == 400
    assert not fake.calls


@pytest.mark.parametrize('action', ['change', 'delete', 'withdraw'])
def test_discard_result_if_source_changes_during_generation(setup, monkeypatch, action):
    client, sid = setup
    selected = core.add_memory(sid, 'fact', '测试记录', status='confirmed')
    def mutate():
        if action == 'change':
            core.update_memory(selected['id'], text='更新的记录')
        elif action == 'delete':
            core.delete_memory(selected['id'])
        else:
            conn = core.get_db()
            conn.execute('UPDATE memories SET source=? WHERE id=?', (core.REVOKE_REVIEW_PREFIX + '测试', selected['id']))
            conn.commit()
            conn.close()
    monkeypatch.setattr(model, 'from_env', lambda: FakeModel(mutate))
    response = request(client, sid, [ref(selected)])
    assert response.status_code == 409 and 'summary' not in response.json()


def test_unavailable_and_invalid_model_outputs(setup, monkeypatch):
    client, sid = setup
    selected = core.add_memory(sid, 'fact', '测试', status='confirmed')
    monkeypatch.setattr(model, 'from_env', lambda: None)
    assert request(client, sid, [ref(selected)]).json()['error_code'] == 'model_unavailable'
    class BadModel:
        def complete(self, *args, **kwargs):
            raise model.ModelError('secret test error must not be returned')
    monkeypatch.setattr(model, 'from_env', lambda: BadModel())
    response = request(client, sid, [ref(selected)])
    assert response.status_code == 503 and 'secret' not in response.text
    class Oversized:
        def complete(self, *args, **kwargs):
            return 'a' * (memory_summary.MAX_OUTPUT_CHARS + 1)
    monkeypatch.setattr(model, 'from_env', lambda: Oversized())
    assert request(client, sid, [ref(selected)]).json()['error_code'] == 'model_invalid_response'


def test_actual_source_revocation_during_generation(setup, monkeypatch):
    client, _ = setup
    created = core.create_session(mode='paste', text='一条用于测试的资料。', source_label='测试来源')
    sid = created['session']['id']
    selected = core.update_memory(created['memories'][0]['id'], status='confirmed')
    def revoke():
        assert core.revoke_source(sid)['ok']
    monkeypatch.setattr(model, 'from_env', lambda: FakeModel(revoke))
    response = request(client, sid, [ref(selected)])
    assert response.status_code == 409 and 'summary' not in response.json()


def test_summary_not_allowed_through_paired_app():
    import re
    assert not any(method == 'POST' and re.fullmatch(pattern, '/api/memory/summary')
                   for method, pattern, _ in paired_app.ROUTES)


def test_paired_device_cannot_call_summary():
    with TestClient(app) as owner:
        response = owner.post('/api/paired-devices', json={'label': '合成手机', 'expires_in_seconds': 604800, 'confirmed': True})
        assert response.status_code == 201
        grant = response.json()
        remote = TestClient(paired_app.create_remote_app(app, lambda: core.DB_PATH, allowed_origins={'https://phone.test'}),
                            base_url='https://phone.test', client=('192.0.2.10', 4000))
        try:
            denied = remote.post('/api/memory/summary', headers={
                'Authorization': 'Bearer ' + grant['token'],
                'X-Echo-Service-Instance': grant['service_instance_id']},
                json={'session_id': grant['conversation_id'], 'confirm': True, 'memories': [{'id': 'test', 'version': 1}]})
            assert denied.status_code == 403
            assert denied.json()['error_code'] == 'paired_operation_forbidden'
        finally:
            remote.close()
