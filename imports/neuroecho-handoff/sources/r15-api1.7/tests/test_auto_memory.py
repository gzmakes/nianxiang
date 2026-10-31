"""Automatic memory: literal statements, provenance, erasure and commit semantics."""
import pytest
from fastapi.testclient import TestClient
from server import auto_memory, core, model
from server.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'auto.db'))
    monkeypatch.setattr(model, 'from_env', lambda: None)
    core.init_db()
    with TestClient(app) as client:
        yield client


def session(client):
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    assert client.put(f'/api/session/{sid}/auto-memory', json={'enabled': True}).status_code == 200
    return sid


def say(client, sid, text, **extra):
    response = client.post('/api/chat', json={'session_id': sid, 'text': text, **extra})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize('text', ['我喜欢喝红茶', '我住在上海', '我是产品经理', '我正在做念响项目', '我偏好简洁的回答'])
def test_local_exact_user_statement_saved_once_with_real_provenance(client, text):
    sid = session(client)
    result = say(client, sid, text)
    record = result['memories'][0]
    assert (record['text'], record['status'], record['source']) == (text, 'auto', auto_memory.SOURCE)
    assert record['source_message_id'] == result['user_message_id']
    assert core._memory_groups(sid)[0] == []
    assert core._memory_groups(sid)[3] == []
    assert core._memory_groups(sid)[4] == [text]
    assert len(say(client, sid, text)['memories']) == 1


@pytest.mark.parametrize('text', [
    '我可能喜欢喝红茶', '我喜欢喝红茶吗？', '他说：我喜欢喝红茶',
    '我喜欢“我的工作”这个说法', '如果我是产品经理', '我喜欢喝红茶，但是现在不喜欢',
    '我喜欢喝红茶13800138000', '我喜欢银行卡密码123456', '我平时喜欢治疗抑郁的药物',
    '我喜欢喝咖啡。帮我想个建议', '我想象我是宇航员',
])
def test_ambiguous_quoted_sensitive_or_compound_not_auto_saved(client, text):
    sid = session(client)
    assert say(client, sid, text)['memories'] == []


def test_forget_does_not_resurrect_on_repetition_but_explicit_restore_is_allowed(client):
    sid = session(client)
    first = say(client, sid, '我喜欢散步')['memories'][0]
    assert client.delete('/api/memory/' + first['id']).status_code == 200
    assert not say(client, sid, '我喜欢散步')['memories']
    restored = say(client, sid, '记住：我喜欢散步')['memories']
    assert len(restored) == 1 and restored[0]['id'] != first['id'] and restored[0]['status'] == 'auto'


def test_correct_then_repeat_keeps_correction(client):
    sid = session(client)
    old = say(client, sid, '我喜欢散步')['memories'][0]
    updated = client.patch('/api/memory/' + old['id'], json={'text': '我喜欢跑步'}).json()
    assert updated['status'] == 'auto' and updated['version'] == 2
    assert [m['text'] for m in say(client, sid, '我喜欢散步')['memories']] == ['我喜欢跑步']
    assert len(core.memory_history(old['id'])) == 2


def test_legacy_candidate_does_not_block_new_explicit_auto_statement(client):
    sid = session(client)
    old = core.add_memory(sid, 'fact', '我喜欢散步', source='用户手动添加')
    result = say(client, sid, '我喜欢散步')
    assert {m['status'] for m in result['memories']} == {'candidate', 'auto'}
    assert next(m for m in result['memories'] if m['id'] == old['id'])['status'] == 'candidate'


def test_inference_always_has_separate_model_context(client):
    sid = session(client)
    core.add_memory(sid, 'inference', '可能喜欢安静', status='confirmed')
    facts, inferences, _, _, automatic = core._memory_groups(sid)
    assert not facts and not automatic and inferences == ['可能喜欢安静']


def test_cancelled_turn_never_saves_auto_memory(client):
    sid = session(client)
    result = core.generate_reply(sid, '我喜欢散步', should_cancel=lambda: True)
    assert result['cancelled'] and not core.list_memories(sid)


def test_manual_opt_in_and_legacy_candidate(client):
    sid = session(client)
    common = {'session_id': sid, 'kind': 'fact', 'text': '我喜欢安静'}
    assert client.post('/api/memory', json=common).json()['status'] == 'candidate'
    manual = client.post('/api/memory', json={**common, 'text': '我喜欢散步', 'user_asserted': True}).json()
    assert manual['status'] == 'auto' and manual['source'] == '用户手动添加'
    assert manual['text'] in core._memory_groups(sid)[4]
    assert client.post('/api/memory', json={**common, 'kind': 'inference', 'user_asserted': True}).status_code == 400


def test_summary_of_auto_record_requires_one_time_consent(client, monkeypatch):
    sid = session(client)
    record = say(client, sid, '我喜欢散步')['memories'][0]
    class Fake:
        def complete(self, *args, **kwargs): return '你喜欢散步。'
    monkeypatch.setattr(model, 'from_env', lambda: Fake())
    body = {'session_id': sid, 'confirm': False, 'memories': [{'id': record['id'], 'version': record['version']}]}
    assert client.post('/api/memory/summary', json=body).status_code == 400
    response = client.post('/api/memory/summary', json={**body, 'confirm': True})
    assert response.status_code == 200 and response.json()['evidence'][0]['id'] == record['id']


def test_preference_resets_old_mode_conflicts_and_new_requests_override(client, monkeypatch):
    calls = []
    class Fake:
        model = 'fake'
        def complete(self, system, prompt):
            calls.append(prompt)
            return '我在。'
    monkeypatch.setattr(model, 'from_env', lambda: Fake())
    sid = session(client)
    say(client, sid, '帮我梳理这件事')
    assert core.get_session(sid)['response_mode'] == 'reflect'
    say(client, sid, '我不希望你马上给建议')
    assert core.get_session(sid)['response_mode'] == 'auto'
    say(client, sid, '继续说')
    assert '这是来自用户明确表达的回应偏好' in calls[-1]
    assert '用户明确选择先听他说' in calls[-1]
    assert '我不希望你马上给建议' in calls[-1]
    say(client, sid, '帮我梳理一下')
    assert '用户明确邀请一起梳理或帮助' in calls[-1]
    say(client, sid, '我希望你直接给我建议')
    assert core.get_session(sid)['response_mode'] == 'auto'
    say(client, sid, '继续说')
    assert '跟随用户当前表达' in calls[-1]


def test_stale_reply_does_not_save_auto_memory(client, monkeypatch):
    sid = session(client)
    class Fake:
        model = 'fake'
        def complete(self, system, prompt):
            core.add_memory(sid, 'fact', '并发改动', source='用户手动添加')
            return '过时内容'
    monkeypatch.setattr(model, 'from_env', lambda: Fake())
    result = say(client, sid, '我喜欢散步')
    assert result['action'] == 'model.stale'
    assert [m['text'] for m in result['memories']] == ['并发改动']


def test_existing_source_not_misattributed_and_revision_not_resurrected(client):
    sid = session(client)
    unrelated = core.add_memory(sid, 'fact', '我喜欢散步', source='某份文档')
    record = say(client, sid, '我喜欢散步')['memories'][-1]
    assert record['source'] == auto_memory.SOURCE and unrelated['status'] == 'candidate'
    core.update_memory(record['id'], text='我喜欢跑步')
    core.delete_memory(record['id'])
    assert [m['id'] for m in say(client, sid, '我喜欢散步')['memories']] == [unrelated['id']]


def test_legacy_proposal_cannot_resurrect_deleted_auto_record(client):
    sid = session(client)
    result = say(client, sid, '我平时喜欢喝红茶')
    memory = result['memories'][0]
    core.delete_memory(memory['id'])
    response = client.post('/api/memory/proposal', json={'session_id': sid, 'message_id': result['user_message_id']})
    assert response.status_code == 409 and not core.list_memories(sid)


def test_forget_automatically_recorded_card_after_confirmation(client):
    sid = session(client)
    record = say(client, sid, '我喜欢散步')['memories'][0]
    core.update_memory(record['id'], status='confirmed')
    core.delete_memory(record['id'])
    assert not say(client, sid, '我喜欢散步')['memories']


def test_explicit_remember_nonpersonal_text_keeps_candidate(client):
    sid = session(client)
    result = say(client, sid, '记住：明早开会')
    assert result['memories'][0]['text'] == '明早开会'
    assert result['memories'][0]['status'] == 'candidate'
    assert '待整理' in result['reply']
    assert len(say(client, sid, '记住：明早开会')['memories']) == 1


def test_explicit_uncertain_record_is_inference(client):
    sid = session(client)
    result = say(client, sid, '记住：我可能喜欢散步')
    assert result['memories'][0]['kind'] == 'inference'
    assert core._memory_groups(sid)[1] == ['我可能喜欢散步']


def test_switch_defaults_off_persists_and_stops_prior_auto_context(client, monkeypatch):
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    url = f'/api/session/{sid}/auto-memory'
    assert client.get(url).json() == {'enabled': False}
    assert say(client, sid, '我喜欢茶')['memories'] == []
    assert client.put(url, json={'enabled': 'true'}).status_code == 422
    assert client.put(url, json={'enabled': True}).json() == {'enabled': True}
    record = say(client, sid, '我喜欢散步')['memories'][0]
    assert record['source'] == auto_memory.SOURCE
    assert client.put(url, json={'enabled': False}).json() == {'enabled': False}
    core.init_db()  # reopening the same database retains the setting
    assert client.get(url).json() == {'enabled': False}
    assert len(core.list_memories(sid)) == 1
    assert '我喜欢散步' not in core._memory_groups(sid)[4]
    assert not any(m['text'] == '我喜欢读书' for m in say(client, sid, '我喜欢读书')['memories'])
    assert core.update_memory(record['id'], status='confirmed')['status'] == 'confirmed'
    assert '我喜欢散步' in core._memory_groups(sid)[0]
    manual = say(client, sid, '记住：我喜欢跳舞')['memories'][-1]
    assert manual['source'] == '对话原话 · 用户选存'
    assert '我喜欢跳舞' in core._memory_groups(sid)[4]


def test_explicit_reaffirmation_of_automatic_record_survives_switch_off(client):
    sid = session(client)
    record = say(client, sid, '我喜欢散步')['memories'][0]
    assert client.put(f'/api/session/{sid}/auto-memory', json={'enabled': False}).status_code == 200
    restored = say(client, sid, '记住：我喜欢散步')['memories'][0]
    assert restored['id'] == record['id'] and restored['source'] == '对话原话 · 用户选存'
    assert '我喜欢散步' in core._memory_groups(sid)[4]


def test_switch_off_stops_existing_auto_memory_from_model_prompt(client, monkeypatch):
    prompts = []
    class Fake:
        model = 'fake'
        def complete(self, system, prompt):
            prompts.append(prompt)
            return '我在。'
    monkeypatch.setattr(model, 'from_env', lambda: Fake())
    sid = session(client)
    say(client, sid, '我喜欢散步')
    say(client, sid, '你还记得我吗')
    assert '我喜欢散步' in prompts[-1]
    client.put(f'/api/session/{sid}/auto-memory', json={'enabled': False})
    say(client, sid, '你还记得我吗')
    assert '我喜欢散步' not in prompts[-1]
    assert any(m['text'] == '我喜欢散步' for m in core.list_memories(sid))
