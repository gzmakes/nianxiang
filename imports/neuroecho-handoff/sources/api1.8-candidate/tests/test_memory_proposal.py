"""Only literal, user-selected proposals enter a temporary isolated database."""
import pytest
from fastapi.testclient import TestClient
from server import core, model
from server.main import app

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'test.db'))
    monkeypatch.setattr(model, 'from_env', lambda: None)
    core.init_db()
    with TestClient(app) as c:
        yield c

def session(c):
    return c.post('/api/session', json={'mode':'empty'}).json()['session']['id']

def chat(c, sid, text, enabled=True):
    return c.post('/api/chat', json={'session_id':sid, 'text':text, 'memory_proposals':enabled}).json()

def test_proposal_ephemeral_source_verified_confirmation_and_deletion(client):
    sid, other = session(client), session(client)
    result = chat(client, sid, '我平时喜欢喝红茶。')
    p = result['memory_proposal']
    assert p['quote'] == '我平时喜欢喝红茶'
    assert result['memories'] == []
    assert core._memory_groups(sid)[0] == []
    assert client.post('/api/memory/proposal', json={'session_id':other,'message_id':p['message_id']}).status_code == 409
    assistant = result['messages'][-1]['id']
    assert client.post('/api/memory/proposal', json={'session_id':sid,'message_id':assistant}).status_code == 409
    saved = client.post('/api/memory/proposal', json={'session_id':sid,'message_id':p['message_id']}).json()
    assert saved['source_message_id'] == p['message_id'] and saved['status'] == 'candidate'
    assert core._memory_groups(sid)[0] == [] and core._memory_groups(sid)[3] == []
    again = client.post('/api/memory/proposal', json={'session_id':sid,'message_id':p['message_id']}).json()
    assert again['id'] == saved['id'] and len(core.list_memories(sid)) == 1
    client.patch('/api/memory/'+saved['id'], json={'status':'confirmed'})
    assert core._memory_groups(sid)[0] == ['我平时喜欢喝红茶']
    assert chat(client, sid, '我平时喜欢喝红茶')['memory_proposal'] is None
    assert client.delete('/api/memory/'+saved['id']).status_code == 200
    assert core.list_memories(sid) == [] and core._memory_groups(sid)[0] == []

def test_proposal_off_and_session_deletion(client):
    sid = session(client)
    assert 'memory_proposal' not in chat(client, sid, '我平时喜欢喝红茶', False)
    p = chat(client, sid, '我平时喜欢喝红茶')['memory_proposal']
    assert client.delete('/api/session/'+sid).status_code == 200
    assert client.post('/api/memory/proposal', json={'session_id':sid,'message_id':p['message_id']}).status_code == 409

@pytest.mark.parametrize('text', [
    '我平时喜欢喝红茶，我现在想自杀', '我平时喜欢喝茶，因为我不想活',
    '我平时喜欢治疗抑郁的药物', '我平时喜欢银行卡密码123456',
    '我平时喜欢喝红茶吗？', '我平时可能喜欢喝红茶', '我平时喜欢喝红茶但是今天不喜欢',
    '记住我平时喜欢喝红茶', '我平时喜欢喝红茶。如果我想伤害自己怎么办',
    '我平时喜欢13800138000', '我平时习惯吃氟西汀', '我平时喜欢喝红茶13800138000',
    '我平时喜欢喝红茶，我正在服用舍曲林', '我平时喜欢银行卡6222021234567890123',
    '我平时喜欢赌博', '我平时习惯自虐', '我平时喜欢喝红茶，我的邮箱是a@example.com',
])
def test_sensitive_or_ambiguous_no_proposal(client,text):
    sid = session(client)
    result = chat(client, sid, text)
    assert not result.get('memory_proposal')
    if not text.startswith('记住'):
        assert not core.list_memories(sid)

def test_revoke_attached_source_cleans_its_memories_but_not_personal_quote(client):
    sid = session(client)
    core.attach_source_to_empty_session(sid, '文档', '资料内容', {'facts':['文档里的内容']}, [], [], [])
    p = chat(client, sid, '我平时喜欢喝红茶')['memory_proposal']
    saved = client.post('/api/memory/proposal', json={'session_id':sid,'message_id':p['message_id']}).json()
    core.revoke_source(sid)
    assert [m['id'] for m in core.list_memories(sid)] == [saved['id']]
    assert core.list_memories(sid)[0]['source_message_id'] == p['message_id']


def test_edit_does_not_misrepresent_original_quote(client):
    sid = session(client)
    p = chat(client, sid, '我平时喜欢喝红茶')['memory_proposal']
    saved = client.post('/api/memory/proposal', json={'session_id':sid,'message_id':p['message_id']}).json()
    edited = client.patch('/api/memory/'+saved['id'], json={'text':'我平时喜欢喝绿茶'}).json()
    assert edited['source'] == '对话原话 · 用户纠正'
    assert edited['source_message_id'] == p['message_id']
    assert not core._memory_groups(sid)[3]


def test_concurrent_requests_keep_each_own_message_and_proposal(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    sid = session(client)
    first_saved, release_first = Event(), Event()
    original = core.add_message
    def coordinated(sid, role, text, *args, **kwargs):
        result = original(sid, role, text, *args, **kwargs)
        if role == 'user' and text == '我平时喜欢喝红茶':
            first_saved.set()
            assert release_first.wait(5)
        return result
    monkeypatch.setattr(core, 'add_message', coordinated)
    texts = ['我平时喜欢喝红茶', '我平时喜欢喝绿茶']
    def submit(text, request_id):
        return client.post('/api/chat', json={'session_id':sid, 'text':text,
                           'memory_proposals':True, 'request_id':request_id})
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(submit, texts[0], 'proposal-first-1')
        assert first_saved.wait(5)
        try:
            rejected = submit(texts[1], 'proposal-rejected-1')
            assert rejected.status_code == 409
            receipt = rejected.json()
            assert (receipt['session_id'], receipt['request_id'], receipt['status'], receipt['error_code']) == (
                sid, 'proposal-rejected-1', 'unknown', 'conversation_busy_not_accepted')
            assert 'memory_proposal' not in receipt
            assert not any(m['text'] == texts[1] for m in core.get_messages(sid))
            assert core.list_memories(sid) == []
        finally:
            release_first.set()
        first_response = first.result(timeout=5)
    assert first_response.status_code == 200
    # Replaying the rejected ID cannot execute once the first turn finishes.
    replay = submit(texts[1], 'proposal-rejected-1')
    assert replay.status_code == 409 and replay.json()['error_code'] == 'conversation_busy_not_accepted'
    assert not any(m['text'] == texts[1] for m in core.get_messages(sid))
    # The user chooses to send again, with a new request ID.
    second_response = submit(texts[1], 'proposal-manual-retry-1')
    assert second_response.status_code == 200
    results = [first_response.json(), second_response.json()]
    for text, result in zip(texts, results):
        proposal = result['memory_proposal']
        assert proposal['quote'] == text
        assert proposal['message_id'] == result['user_message_id']
        assert next(m for m in result['messages'] if m['id'] == result['user_message_id'])['text'] == text
    assert results[0]['user_message_id'] != results[1]['user_message_id']
    assert [m['text'] for m in core.get_messages(sid) if m['role'] == 'user'] == texts
    assert core.list_memories(sid) == []  # Proposals still require explicit confirmation.


def test_all_reply_branches_return_their_user_message_id(client, monkeypatch):
    from server import faults
    sid = session(client)
    normal = chat(client, sid, '我平时喜欢喝红茶')
    monkeypatch.setattr(faults, 'active', lambda kind: kind == 'model_timeout')
    timeout = chat(client, sid, '我平时喜欢喝绿茶')
    safety = chat(client, sid, '我不想活了')
    for result, text in [(normal, '我平时喜欢喝红茶'), (timeout, '我平时喜欢喝绿茶'), (safety, '我不想活了')]:
        assert next(m for m in result['messages'] if m['id'] == result['user_message_id'])['text'] == text


@pytest.mark.parametrize('text', [
    '我不喜欢被催', '我不喜欢被催促', '我不喜欢被打断',
    '我希望你先听我说', '我希望你先听我说完',
    '我不希望你马上给建议', '我不希望你立刻给建议',
])
def test_literal_companion_preferences_need_explicit_save_and_confirmation(client, text):
    sid = session(client)
    result = chat(client, sid, text)
    p = result['memory_proposal']
    assert p['quote'] == text
    assert core.list_memories(sid) == []
    saved = client.post('/api/memory/proposal', json={'session_id': sid, 'message_id': p['message_id']}).json()
    assert saved['text'] == text and saved['status'] == 'candidate'
    assert not core._memory_groups(sid)[0]
    client.patch('/api/memory/'+saved['id'], json={'status':'confirmed'})
    assert core._memory_groups(sid)[0] == [text]


@pytest.mark.parametrize('text', [
    '我不喜欢被催，我的手机号是13800138000',
    '我不喜欢被打断，我服用氟西汀',
    '我希望你先听我说，我不想活了',
    '我希望你先听我说，我银行卡号是6222021234567890123',
    '我不希望你马上给建议，我今天丢了工作',
    '我不希望你马上给建议吗？',
    '如果我不喜欢被催，你会怎么办',
])
def test_companion_preference_plus_other_topics_is_not_proposed(client, text):
    sid = session(client)
    result = chat(client, sid, text)
    assert not result.get('memory_proposal')
    assert not core.list_memories(sid)
