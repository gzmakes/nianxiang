"""Behavioral tests: topic-aware recall must respect consent and withdrawal."""
import pytest

from server import core
from server.memory_retrieval import relevant_memories


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'memory-relevance.db'))
    core.init_db()
    return core.create_session('empty')['session']['id']


def test_general_chat_does_not_recall_random_confirmed_fact_when_model_unavailable(session, monkeypatch):
    core.add_memory(session, 'fact', '我喜欢咖啡', status='confirmed')
    monkeypatch.setattr(core.model, 'from_env', lambda: None)
    reply = core.generate_reply(session, '今天想随便聊聊')['reply']
    assert '咖啡' not in reply
    assert '我在' in reply


def test_only_related_memories_are_offered_to_model_and_explicit_recall_can_see_more(session, monkeypatch):
    sent = []
    class Fake:
        model = 'fake'
        def complete(self, system, user):
            sent.append(user)
            return '收到。'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    core.add_memory(session, 'fact', '我喜欢咖啡', status='confirmed')
    core.add_memory(session, 'fact', '周末去爬山', status='confirmed')
    core.add_memory(session, 'fact', '想尝试咖啡', status='candidate')
    core.generate_reply(session, '今天有些事情想说')
    assert '我喜欢咖啡' not in sent[-1] and '周末去爬山' not in sent[-1]
    core.generate_reply(session, '我今天想喝咖啡')
    assert '我喜欢咖啡' in sent[-1]
    assert '周末去爬山' not in sent[-1]
    assert '【待用户确认的内容，不当作事实】\n- 想尝试咖啡' in sent[-1]
    core.generate_reply(session, '你记得我吗')
    assert '我喜欢咖啡' in sent[-1] and '周末去爬山' in sent[-1]


def test_correction_and_delete_cannot_reappear_via_memory_or_old_chat(session, monkeypatch):
    sent = []
    class Fake:
        model = 'fake'
        def complete(self, system, user):
            sent.append(user)
            return '收到。'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    card = core.add_memory(session, 'fact', '喜欢绿茶', status='confirmed')
    core.add_message(session, 'assistant', '你喜欢绿茶')
    core.update_memory(card['id'], text='喜欢红茶')
    core.generate_reply(session, '你记得我吗')
    assert '喜欢红茶' in sent[-1] and '喜欢绿茶' not in sent[-1]
    core.delete_memory(card['id'])
    core.generate_reply(session, '你记得我吗')
    assert '喜欢红茶' not in sent[-1] and '喜欢绿茶' not in sent[-1]


def test_revoked_source_is_not_recalled_and_other_source_is_retained(session, monkeypatch):
    sent = []
    class Fake:
        model = 'fake'
        def complete(self, system, user):
            sent.append(user)
            return '收到。'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    for name, memory in [('旧资料', '秘密绿茶'), ('保留资料', '喜欢咖啡')]:
        core.attach_source_to_empty_session(session, name, memory, {'facts': [memory]}, [], [], [], 'local')
    cards = core.list_memories(session)
    for card in cards:
        core.update_memory(card['id'], status='confirmed')
    sources = core.list_sources(session)
    core.revoke_source(session, next(s['id'] for s in sources if s['label'] == '旧资料'))
    core.generate_reply(session, '你记得我吗')
    assert '秘密绿茶' not in sent[-1]
    assert '喜欢咖啡' in sent[-1]


def test_filter_abstains_on_generic_or_negative_request_and_keeps_conflicting_matches():
    memories = [{'text': '喜欢咖啡'}, {'text': '不喜欢咖啡'}, {'text': '喜欢爬山'}]
    assert relevant_memories(memories, '今天想聊聊') == []
    assert relevant_memories(memories, '别提我的记忆，聊聊咖啡') == []
    assert [m['text'] for m in relevant_memories(memories, '我想喝咖啡')] == ['喜欢咖啡', '不喜欢咖啡']


def test_declining_memory_mentions_omits_preference_text_but_retains_response_mode(session):
    core.add_memory(session, 'fact', '我希望你先听我说', source='用户手动添加', status='confirmed')
    groups = core._memory_groups(session, '别提我的记忆，聊聊咖啡')
    assert groups == ([], [], [], [])
    assert core._effective_response_mode(session) == ('listen', True)


def test_small_topic_aliases_can_retrieve_related_memory_without_guessing_other_topics():
    memories = [{'text': '容易失眠'}, {'text': '喜欢咖啡'}, {'text': '喜欢爬山'}, {'text': '喜欢红茶'}]
    assert relevant_memories(memories, '又睡不着了') == [memories[0]]
    assert relevant_memories(memories, '想来一杯拿铁') == [memories[1]]
    assert relevant_memories(memories, '我们聊聊茶') == [memories[3]]


def test_recall_is_bounded_and_does_not_treat_latin_substrings_as_whole_names():
    memories = [{'text': 'Project Meta'}, {'text': 'Project Metadata'}] + [{'text': f'记忆{i}'} for i in range(20)]
    assert relevant_memories(memories, 'Meta 是什么') == [memories[0]]
    assert len(relevant_memories(memories, '你记得我吗')) == 8
