"""Synthetic companion-preference lifecycle; no network, key, or real database."""
import pytest
from fastapi.testclient import TestClient

from server import core
from server.main import app


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'synthetic.db'))
    calls = []

    class Model:
        model = 'synthetic-only'
        def complete(self, system, prompt):
            calls.append((system, prompt))
            return '收到，我们接着聊。'

    monkeypatch.setattr(core.model, 'from_env', lambda: Model())
    core.init_db()
    with TestClient(app) as client:
        sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
        yield client, sid, calls


def say(client, sid, text):
    response = client.post('/api/chat', json={'session_id': sid, 'text': text, 'memory_proposals': True})
    assert response.status_code == 200
    return response.json()


def test_explicit_confirm_then_later_override_correct_and_forget(harness):
    client, sid, calls = harness
    # An old conversation mode must not defeat a newer confirmed preference.
    say(client, sid, '帮我梳理这件事')
    assert core.get_session(sid)['response_mode'] == 'reflect'
    p = say(client, sid, '我不希望你马上给建议')['memory_proposal']
    saved = client.post('/api/memory/proposal', json={'session_id': sid, 'message_id': p['message_id']}).json()
    say(client, sid, '今天有点累')
    assert '这是用户确认过的回应偏好' not in calls[-1][1]
    assert client.patch('/api/memory/' + saved['id'], json={'status': 'confirmed'}).status_code == 200
    say(client, sid, '今天有点累')
    prompt = calls[-1][1]
    assert '用户明确选择先听他说' in prompt
    assert '这是用户确认过的回应偏好' in prompt
    assert '我不希望你马上给建议' in prompt
    assert '没有任何可执行工具' in calls[-1][0]

    say(client, sid, '帮我梳理一下这件事')
    assert '用户明确邀请一起梳理或帮助' in calls[-1][1]
    assert '这是用户确认过的回应偏好' not in calls[-1][1]

    # A correction takes precedence over the previous confirmed preference and mode.
    edit = client.patch('/api/memory/' + saved['id'], json={'text': '我希望你直接给我建议'})
    assert edit.status_code == 200
    say(client, sid, '换个话题')
    assert '用户明确邀请一起梳理或帮助' in calls[-1][1]
    assert '我希望你直接给我建议' in calls[-1][1]
    assert '我不希望你马上给建议' not in calls[-1][1]

    assert client.delete('/api/memory/' + saved['id']).status_code == 200
    say(client, sid, '接着说')
    assert '跟随用户当前表达' in calls[-1][1]
    assert '我希望你直接给我建议' not in calls[-1][1]
    assert '这是用户确认过的回应偏好' not in calls[-1][1]


def test_quoted_or_unconfirmed_text_never_sets_preference(harness):
    client, sid, calls = harness
    core.add_memory(sid, 'fact', '我希望你先听我说', source='用户手动添加')
    core.add_memory(sid, 'fact', '我希望你先听我说', source='已读取的文档', status='confirmed')
    core.add_memory(sid, 'fact', '如果我希望你先听我说', source='用户手动添加', status='confirmed')
    say(client, sid, '继续聊')
    assert '跟随用户当前表达' in calls[-1][1]
    assert '这是用户确认过的回应偏好' not in calls[-1][1]


def test_conflicting_confirmed_preferences_do_not_choose_arbitrarily(harness):
    client, sid, calls = harness
    first = core.add_memory(sid, 'fact', '我希望你先听我说', source='用户手动添加')
    second = core.add_memory(sid, 'fact', '我希望你直接给我建议', source='用户手动添加')
    core.update_memory(first['id'], status='confirmed')
    core.update_memory(second['id'], status='confirmed')
    say(client, sid, '我今天很累')
    assert '跟随用户当前表达' in calls[-1][1]
    assert '这是用户确认过的回应偏好' not in calls[-1][1]
    assert '遇到冲突时不要自行选择' in calls[-1][0]
    core.delete_memory(second['id'])
    say(client, sid, '我还想再说说')
    assert '这是用户确认过的回应偏好' in calls[-1][1]
    assert '用户明确选择先听他说' in calls[-1][1]


def test_one_click_confirmation_resets_old_mode_and_explicit_auto_overrides_for_turn(harness):
    client, sid, calls = harness
    say(client, sid, '帮我梳理这件事')
    result = say(client, sid, '我不希望你马上给建议')
    saved = client.post('/api/memory/proposal', json={
        'session_id': sid, 'message_id': result['memory_proposal']['message_id'], 'confirm': True,
    }).json()
    assert saved['status'] == 'confirmed'
    assert core.get_session(sid)['response_mode'] == 'auto'
    say(client, sid, '不用只听我说，帮我一起想想')
    assert '跟随用户当前表达' in calls[-1][1]
    assert '这是用户确认过的回应偏好' not in calls[-1][1]
    say(client, sid, '又想说一件事')
    assert '这是用户确认过的回应偏好' in calls[-1][1]


def test_forgetting_preference_preserves_newer_explicit_session_mode(harness):
    client, sid, calls = harness
    result = say(client, sid, '我希望你先听我说')
    assert core.get_session(sid)['response_mode'] == 'listen'
    saved = client.post('/api/memory/proposal', json={
        'session_id': sid, 'message_id': result['memory_proposal']['message_id'], 'confirm': True,
    }).json()
    say(client, sid, '先听我说')
    assert core.get_session(sid)['response_mode'] == 'listen'
    assert client.delete('/api/memory/' + saved['id']).status_code == 200
    say(client, sid, '接着聊')
    assert '用户明确选择先听他说' in calls[-1][1]
    assert '这是用户确认过的回应偏好' not in calls[-1][1]
    assert '我希望你先听我说' not in calls[-1][1]


def test_delete_confirmed_preference_removes_default_without_overriding_session(harness):
    client, sid, calls = harness
    result = say(client, sid, '我希望你先听我说')
    saved = client.post('/api/memory/proposal', json={
        'session_id': sid, 'message_id': result['memory_proposal']['message_id'], 'confirm': True,
    }).json()
    assert core.get_session(sid)['response_mode'] == 'auto'
    say(client, sid, '接着聊')
    assert '这是用户确认过的回应偏好' in calls[-1][1]
    assert client.delete('/api/memory/' + saved['id']).status_code == 200
    say(client, sid, '另一件事')
    assert '跟随用户当前表达' in calls[-1][1]
    assert '这是用户确认过的回应偏好' not in calls[-1][1]


@pytest.mark.parametrize('operation', ['delete', 'edit'])
@pytest.mark.parametrize('source,status', [
    ('用户手动添加', 'candidate'),
    ('已读取的文档', 'candidate'),
    ('已读取的文档', 'confirmed'),
])
def test_unrelated_memory_change_keeps_explicit_mode(harness, operation, source, status):
    client, sid, calls = harness
    memory = core.add_memory(sid, 'fact', '我希望你先听我说', source=source, status=status)
    say(client, sid, '先听我说')
    if operation == 'delete':
        assert client.delete('/api/memory/' + memory['id']).status_code == 200
    else:
        assert client.patch('/api/memory/' + memory['id'], json={'text': '另一条材料'}).status_code == 200
    assert core.get_session(sid)['response_mode'] == 'listen'
    say(client, sid, '接着聊')
    assert '用户明确选择先听他说' in calls[-1][1]
