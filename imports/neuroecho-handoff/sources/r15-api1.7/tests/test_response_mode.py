"""Real user goals: keep listening, permit help, and preserve intent on reopen."""
import pytest
from fastapi.testclient import TestClient

from server import core
from server.conversation_intent import requested_response_mode
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'dialogue.db'))
    core.init_db()
    return TestClient(app)


@pytest.mark.parametrize('text, expected', [
    ('先听我说，我今天有点乱', 'listen'),
    ('我希望你先听我说完。', 'listen'),
    ('先不要给建议，我想把经过说完', 'listen'),
    ('今天只想吐槽一下', 'listen'),
    ('帮我梳理一下这件事', 'reflect'),
    ('现在可以给建议了', 'reflect'),
    ('请你帮我回邮件', 'reflect'),
    ('不用只听我说，帮我一起想想', 'auto'),
    ('同事说「先听我说」，然后又打断我', None),
    ('“帮我分析”是他发来的消息', None),
    ('我想起上次你给我的建议', None),
])
def test_only_direct_opening_requests_change_mode(text, expected):
    assert requested_response_mode(text) == expected


def test_listen_survives_many_turns_and_reopen_then_explicit_help_switches(client, monkeypatch):
    captured = []
    class Fake:
        model = 'isolated-test'
        def complete(self, system, prompt):
            captured.append((system, prompt))
            return '我在听，慢慢说。'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    client.post('/api/chat', json={'session_id': sid, 'text': '先别给建议，我想说完'})
    for n in range(5):
        client.post('/api/chat', json={'session_id': sid, 'text': f'补充第{n}件事'})
    assert '用户明确选择先听他说' in captured[-1][1]
    reopened = client.get(f'/api/session/{sid}').json()
    assert reopened['session']['response_mode'] == 'listen'
    # Mode is a session control; do not silently save it as a personal memory.
    assert reopened['memories'] == []
    client.post('/api/chat', json={'session_id': sid, 'text': '帮我梳理一下，哪些是我能决定的'})
    assert '用户明确邀请一起梳理或帮助' in captured[-1][1]
    assert core.get_session(sid)['response_mode'] == 'reflect'
    other = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    assert core.get_session(other)['response_mode'] == 'auto'


def test_listening_fallback_does_not_push_source_actions_on_ordinary_complaint(client):
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    core.set_session_context(sid, 'test', [{'title': '项目会议', 'summary': '讨论进展'}],
                             [{'type': 'opportunity', 'title': '开会', 'text': '安排周会'}])
    client.post('/api/chat', json={'session_id': sid, 'text': '先听我说'})
    reply = client.post('/api/chat', json={'session_id': sid, 'text': '这周老有人给建议，我听累了'}).json()['reply']
    assert '模型' in reply  # transparent failure remains visible
    assert '我在听' in reply
    assert '候选下一步' not in reply and '书签' not in reply and '安排周会' not in reply
    assert not core.list_actions(sid)


def test_help_after_listening_reenables_source_assistance(client):
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    core.set_session_context(sid, 'test', [{'title': '交付', 'summary': '最后检查'}], [])
    client.post('/api/chat', json={'session_id': sid, 'text': '先听我说'})
    result = client.post('/api/chat', json={'session_id': sid, 'text': '下一步怎么办'}).json()
    assert result['action'] == 'context.reply'
    assert core.get_session(sid)['response_mode'] == 'reflect'


def test_continue_stays_in_current_conversation_without_forcing_bookmark(client, monkeypatch):
    seen = []
    class Fake:
        model = 'isolated-test'
        def complete(self, system, prompt):
            seen.append(prompt)
            return '我们接着刚才那件事聊。'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    result = client.post('/api/chat', json={'session_id': sid, 'text': '继续'}).json()
    assert result['action'] == 'model.reply' and seen
    assert '书签' not in result['reply']
    bookmark = client.post('/api/chat', json={'session_id': sid, 'text': '回到书签'}).json()
    assert '书签' in bookmark['reply']


def test_no_tool_completion_or_future_reminder_promise_in_model_contract(client, monkeypatch):
    sent = []
    class Fake:
        model = 'isolated-test'
        def complete(self, system, prompt):
            sent.append(system)
            return '我可以先拟一份文字草稿，你再决定。'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    client.post('/api/chat', json={'session_id': sid, 'text': '明天提醒我早点休息'})
    assert '没有任何可执行工具' in sent[-1]
    assert '实际工具回执' in sent[-1]
    assert not core.list_actions(sid)


def test_legacy_session_migration_keeps_words_and_defaults_to_auto(client, legacy_schema_without_changes):
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    original = core.add_message(sid, 'user', '以前说过的话')
    conn = core.get_db()
    legacy_schema_without_changes(conn)
    conn.execute('ALTER TABLE sessions DROP COLUMN response_mode')
    conn.commit()
    conn.close()
    core.init_db()
    core.init_db()
    assert core.get_session(sid)['response_mode'] == 'auto'
    assert any(m['id'] == original['id'] for m in core.get_messages(sid))
