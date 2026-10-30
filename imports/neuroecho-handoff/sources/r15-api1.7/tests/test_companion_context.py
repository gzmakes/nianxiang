"""Regression tests for consented memory, honest failure, and grounded replies."""
import pytest
from fastapi.testclient import TestClient

from server import core, model
from server.main import app


def test_listening_request_stays_listening_when_model_unavailable(client):
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    reply = client.post('/api/chat', json={'session_id': sid, 'text': '我希望你先听我说'}).json()['reply']
    assert '先听你说' in reply
    assert '？' not in reply


def test_mixed_do_not_remind_and_emotional_expression_reaches_model(client, monkeypatch):
    captured = []

    class Fake:
        model = 'fake'

        def complete(self, system, user):
            captured.append(user)
            return '我听见你今天很难受，我们可以慢慢说。'

    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    text = '不用提醒，我今天心里很难受，想聊聊。'
    result = client.post('/api/chat', json={'session_id': sid, 'text': text}).json()
    assert result['action'] == 'model.reply'
    from server import companion_boundary
    assert companion_boundary.get(core.DB_PATH,sid)['mode']=='paused'
    assert text in captured[-1]
    assert '难受' in result['reply']


def test_explicit_memory_with_reminder_words_is_not_misrouted(client):
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    result = client.post('/api/chat', json={'session_id': sid, 'text': '记住：我不喜欢提醒我上次的事情'}).json()
    assert result['action'] == 'memory.candidate'
    assert any('不喜欢提醒' in m['text'] and m['status'] == 'candidate' for m in result['memories'])


def test_direct_reminder_refusal_persists_boundary_without_model(client, monkeypatch):
    monkeypatch.setattr(core, '_model_reply', lambda *args: pytest.fail('quiet must not call model'))
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    result = client.post('/api/chat', json={'session_id': sid, 'text': '不用提醒。'}).json()
    assert result['state'] == 'quiet'
    assert result['action'] == 'boundary.changed'


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    core.init_db()
    return TestClient(app)


def test_only_confirmed_memory_is_described_as_confirmed_and_correction_wins(client, monkeypatch):
    prompts = []

    class Fake:
        model = "fake"

        def complete(self, system, user):
            prompts.append((system, user))
            return "我记得你说过喜欢散步。"

    monkeypatch.setattr(core.model, "from_env", lambda: Fake())
    first = client.post("/api/session", json={"mode": "empty"}).json()["session"]["id"]
    confirmed = core.add_memory(first, "fact", "喜欢跑步", status="confirmed")
    core.add_memory(first, "fact", "住在火星", status="candidate")
    core.update_memory(confirmed["id"], text="喜欢散步", status="confirmed")
    client.post("/api/chat", json={"session_id": first, "text": "你还记得我吗"})
    system, prompt = prompts[-1]
    assert "用户已纠正的记忆优先" in system
    assert "【用户已确认的记忆】\n- 喜欢散步" in prompt
    assert "【待用户确认的内容，不当作事实】\n- 住在火星" in prompt
    assert "喜欢跑步" not in prompt

    second = client.post("/api/session", json={"mode": "empty"}).json()["session"]["id"]
    client.post("/api/chat", json={"session_id": second, "text": "你还记得我吗"})
    assert "喜欢散步" not in prompts[-1][1]  # no cross-session import without consent
    imported = client.post("/api/carryover/import", json={"session_id": second, "ids": [confirmed["id"]]}).json()
    assert imported["imported"] == 1
    client.post("/api/chat", json={"session_id": second, "text": "你还记得我吗"})
    assert "【用户已确认的记忆】\n- 喜欢散步" in prompts[-1][1]
    audit = client.get(f"/api/audit?session_id={second}").json()["events"]
    assert not any("我记得你说过喜欢散步" in event["detail"] for event in audit)


def test_failure_is_disclosed_and_no_fabricated_source_details(client, monkeypatch):
    class Broken:
        model = "fake"

        def complete(self, system, user):
            raise model.ModelError("timeout")

    monkeypatch.setattr(core.model, "from_env", lambda: Broken())
    sid = client.post("/api/session", json={"mode": "empty"}).json()["session"]["id"]
    core.set_session_context(sid, "gmail", [{"title": "一封关于旅行的邮件", "summary": "计划周末出行"}], [])
    result = client.post("/api/chat", json={"session_id": sid, "text": "帮我回邮件"}).json()
    assert "模型暂时不可用" in result["reply"]
    assert "投资人" not in result["reply"]
    assert result["messages"][-1]["citations"] == []


def test_explicit_commands_work_without_model(client, monkeypatch):
    def model_must_not_be_called():
        raise AssertionError("commands must not call the model")

    monkeypatch.setattr(core.model, "from_env", model_must_not_be_called)
    sid = client.post("/api/session", json={"mode": "empty"}).json()["session"]["id"]
    remembered = client.post("/api/chat", json={"session_id": sid, "text": "记住：我喜欢散步"}).json()
    assert any(m["text"] == "我喜欢散步" and m["status"] == "candidate" for m in remembered["memories"])
    quiet = client.post("/api/chat", json={"session_id": sid, "text": "安静"}).json()
    assert quiet["state"] == "quiet"


@pytest.mark.parametrize(('command', 'fact'), [
    ('请记住这句：在这次合成测试里，我喜欢你先听我说，再问我要不要建议。',
     '在这次合成测试里，我喜欢你先听我说，再问我要不要建议'),
    ('请记住：我喜欢散步。', '我喜欢散步'),
    ('帮我记住我喜欢散步', '我喜欢散步'),
    ('请帮我记住：我喜欢散步', '我喜欢散步'),
    ('请你记住这句话：我喜欢散步', '我喜欢散步'),
    ('记住：我喜欢散步', '我喜欢散步'),
    ('请记住这句：我不喜欢被叫停，也不希望你回到上次的书签。',
     '我不喜欢被叫停，也不希望你回到上次的书签'),
])
def test_direct_memory_command_creates_candidate_during_today_quiet_without_auto_proposals(
        client, monkeypatch, command, fact):
    def no_model():
        pytest.fail('an explicit memory command must use the real candidate receipt, not a model claim')

    monkeypatch.setattr(core.model, 'from_env', no_model)
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    quiet = client.post('/api/chat', json={
        'session_id': sid, 'text': '今天先别问了', 'time_zone': 'Asia/Shanghai'}).json()
    assert quiet['companion_boundary']['mode'] == 'until'
    response = client.post('/api/chat', json={
        'session_id': sid, 'text': command, 'memory_proposals': False})
    assert response.status_code == 200
    result = response.json()
    assert result['action'] == 'memory.candidate'
    assert '待确认' in result['reply']
    assert '没有' not in result['reply']
    assert len(result['memories']) == 1
    memory = result['memories'][0]
    assert (memory['text'], memory['status'], memory['source']) == (
        fact, 'candidate', '对话中用户要求')
    assert core.list_memories(sid)[0]['id'] == memory['id']
    boundary = client.get('/api/companion-boundary', params={'session_id': sid}).json()
    assert boundary['mode'] == 'until'


@pytest.mark.parametrize('text', [
    '“请记住这句：我喜欢散步”，朋友这样说。',
    '朋友说帮我记住我喜欢散步。',
    '资料摘录：请记住这句：我喜欢散步。',
    '请记住是什么意思？',
    '请记住：我喜欢散步吗？',
    '帮我记住这句话可以吗？',
    '我想知道你是否可以帮我记住我喜欢散步。',
])
def test_quoted_or_question_memory_text_does_not_create_candidate(client, monkeypatch, text):
    called = []

    def reply(*args, **kwargs):
        called.append(True)
        return '这是合成回应。', 'ok'

    monkeypatch.setattr(core, '_model_reply', reply)
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    result = client.post('/api/chat', json={
        'session_id': sid, 'text': text, 'memory_proposals': False}).json()
    assert called == [True]
    assert result['action'] != 'memory.candidate'
    assert result['memories'] == core.list_memories(sid) == []


def test_polite_memory_command_replays_candidate_without_confirming_or_duplicating(client, monkeypatch):
    monkeypatch.setattr(core.model, 'from_env', lambda: pytest.fail('direct command called model'))
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    body = {'session_id': sid, 'text': '请记住这句：我喜欢散步。',
            'memory_proposals': False, 'request_id': 'explicit-memory-command-replay'}
    first = client.post('/api/chat', json=body).json()
    replay = client.post('/api/chat', json=body).json()
    assert replay['reply'] == first['reply']
    assert replay['user_message_id'] == first['user_message_id']
    assert replay['memories'] == first['memories']
    assert [message['id'] for message in replay['messages']] == [message['id'] for message in first['messages']]
    again = client.post('/api/chat', json={**body, 'request_id': 'same-memory-new-request'}).json()
    assert len(again['memories']) == 1
    assert again['memories'][0]['id'] == first['memories'][0]['id']
    assert again['memories'][0]['status'] == 'candidate'
    assert again['memories'][0]['version'] == 1
    assert '待确认' in again['reply']


def test_empty_polite_memory_command_asks_for_content_without_saving(client, monkeypatch):
    monkeypatch.setattr(core.model, 'from_env', lambda: pytest.fail('direct command called model'))
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    result = client.post('/api/chat', json={'session_id': sid, 'text': '请记住这句：'}).json()
    assert result['reply'] == '你想让我记住什么？'
    assert result['memories'] == []


def test_revoked_source_is_not_sent_again_even_after_multiple_turns(client, monkeypatch):
    sent = []

    class Fake:
        model = "fake"

        def complete(self, system, user):
            sent.append(user)
            return "收到。"

    monkeypatch.setattr(core.model, "from_env", lambda: Fake())
    sid = client.post("/api/session", json={"mode": "empty"}).json()["session"]["id"]
    core.set_session_context(sid, "local_files", [{"title": "私人来源内容", "summary": "私密细节"}], [])
    core.add_memory(sid, "fact", "私人来源内容", status="confirmed")
    core.add_message(sid, "assistant", "私人来源内容的总结")
    client.post("/api/source/revoke", json={"session_id": sid})
    assert core.get_session_context(sid) is None
    # Unlabeled legacy entries cannot be safely attributed: retain their
    # revisions for review, while excluding the memory from model context.
    retained = core.list_memories(sid)
    assert len(retained) == 1 and retained[0]['source'].startswith(core.REVOKE_REVIEW_PREFIX)
    assert core.export_data(sid)["memory_revisions"]
    for text in ("你好", "我又来了"):
        client.post("/api/chat", json={"session_id": sid, "text": text})
        assert "私人来源内容" not in sent[-1]
        assert "私密细节" not in sent[-1]


@pytest.mark.parametrize('message', [
    '不用提醒，我今晚要自杀',
    '记住：我今晚要自杀',
    '别安排，我现在想伤害自己',
    '继续上次，我要杀了他',
])
def test_safety_precedes_command_shortcuts_and_model_outage(client, monkeypatch, message):
    def unavailable():
        raise AssertionError('safety response must not depend on the model')
    monkeypatch.setattr(core.model, 'from_env', unavailable)
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    result = client.post('/api/chat', json={'session_id': sid, 'text': message}).json()
    assert result['action'] == 'safety'
    assert '立即危险' in result['reply'] and '信任的人' in result['reply']
    assert not result['memories']


def test_correction_suppresses_original_source_and_other_derived_candidates(client, monkeypatch):
    sent = []

    class Fake:
        model = 'fake'
        def complete(self, system, user):
            sent.append(user)
            return '收到'

    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    core.set_session_context(sid, 'test', [{'title': '饮食', 'summary': '我喜欢绿茶'}],
                             [{'type': 'observation', 'title': '喜欢绿茶', 'text': '用户喜欢绿茶'}])
    fact = core.add_memory(sid, 'fact', '我喜欢绿茶', source='来源', status='candidate')
    core.add_memory(sid, 'inference', '推测喜欢绿茶', source='来源', status='candidate')
    core.add_memory(sid, 'fact', '我住在海边', source='对话中用户要求', status='candidate')
    core.update_memory(fact['id'], text='我喜欢红茶', status='confirmed')
    client.post('/api/chat', json={'session_id': sid, 'text': '你记得我的偏好吗'})
    assert '我喜欢红茶' in sent[-1]
    assert '绿茶' not in sent[-1]
    assert '我住在海边' in sent[-1]
    assert core.get_session_context(sid)['items'][0]['summary'] == '我喜欢绿茶'
    # Rule-based fallback must not repeat stale insights either.
    monkeypatch.setattr(core.model, 'from_env', lambda: None)
    result = client.post('/api/chat', json={'session_id': sid, 'text': '下一步怎么办'}).json()
    assert '绿茶' not in result['reply']


def test_confirmation_without_text_change_keeps_source_available(client, monkeypatch):
    sent = []
    class Fake:
        model = 'fake'
        def complete(self, system, user):
            sent.append(user)
            return '收到'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    core.set_session_context(sid, 'test', [{'title': '日记', 'summary': '天气晴朗'}], [])
    card = core.add_memory(sid, 'fact', '天气晴朗', source='来源')
    core.update_memory(card['id'], status='confirmed')
    client.post('/api/chat', json={'session_id': sid, 'text': '你好'})
    assert '【读取到的具体条目】' in sent[-1]


def test_corrected_candidate_remains_visible_as_unconfirmed(client, monkeypatch):
    sent = []
    class Fake:
        model = 'fake'
        def complete(self, system, user):
            sent.append(user)
            return '收到'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    core.set_session_context(sid, 'test', [{'title': '饮食', 'summary': '绿茶'}], [])
    card = core.add_memory(sid, 'fact', '我喜欢绿茶', source='来源')
    core.update_memory(card['id'], text='我喜欢红茶')
    client.post('/api/chat', json={'session_id': sid, 'text': '我喜欢什么'})
    assert '【待用户确认的内容，不当作事实】\n- 我喜欢红茶' in sent[-1]
    assert '绿茶' not in sent[-1]


def test_deleted_card_does_not_return_via_source_summary(client, monkeypatch):
    sent = []
    class Fake:
        model = 'fake'
        def complete(self, system, user):
            sent.append(user)
            return '收到'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    core.set_session_context(sid, 'test', [{'title': '饮食', 'summary': '绿茶'}], [])
    card = core.add_memory(sid, 'fact', '我喜欢绿茶', source='来源')
    core.delete_memory(card['id'])
    client.post('/api/chat', json={'session_id': sid, 'text': '你好'})
    assert '绿茶' not in sent[-1]
