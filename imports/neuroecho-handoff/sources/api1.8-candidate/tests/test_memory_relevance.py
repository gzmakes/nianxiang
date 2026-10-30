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


@pytest.mark.parametrize('query', [
    '别再提之前我失眠的事', '这件事暂时先不要再聊了',
    '我不想再跟你谈睡眠', '先不说咖啡，换个话题',
])
def test_topic_decline_omits_retrieved_cards_for_current_turn(session, monkeypatch, query):
    from server.memory_retrieval import user_declines_recall
    assert user_declines_recall(query)
    core.add_memory(session, 'fact', '容易失眠', status='confirmed')
    core.add_memory(session, 'fact', '喜欢咖啡', status='confirmed')
    assert core._memory_groups(session, query) == ([], [], [], [])
    # A temporary request does not delete or globally mute the memories.
    assert '容易失眠' in core._memory_groups(session, '最近又失眠了')[0]


def test_unrelated_negative_verbs_do_not_disable_recall():
    from server.memory_retrieval import user_declines_recall
    assert not user_declines_recall('别提醒我喝咖啡')
    assert not user_declines_recall('不要提前喝咖啡')


def test_declining_topic_omits_previous_chat_and_connected_sources_for_that_turn(session, monkeypatch):
    sent = []

    class Fake:
        model = 'fake'

        def complete(self, system, user):
            sent.append((system, user))
            return '好，我们换个话题。'

    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    monkeypatch.setattr(core, '_active_source_context', lambda _: {
        'items': [{'title': '旧来源蓝色鲸鱼', 'summary': '旧来源摘要'}],
        'insights': [{'type': 'note', 'title': '旧来源洞察', 'text': '鲸鱼内容'}],
    })
    monkeypatch.setattr(core, '_source_excerpts', lambda *_: ['旧来源检索片段鲸鱼'])
    core.add_memory(session, 'fact', '失眠时喜欢蓝色鲸鱼', status='confirmed')
    core.add_message(session, 'assistant', '旧对话蓝色鲸鱼')
    core.generate_reply(session, '别再提之前我失眠的事，换个话题')
    system, user = sent[-1]
    assert '尊重这条要求' in system
    assert '别再提之前我失眠的事' in user  # The current request still reaches the model.
    assert '蓝色鲸鱼' not in user
    assert '旧来源' not in user
    assert '【最近对话】' not in user

    core.generate_reply(session, '最近又失眠了')
    assert '蓝色鲸鱼' in sent[-1][1]
    assert '旧来源检索片段鲸鱼' in sent[-1][1]


def test_topic_decline_does_not_offer_source_search_even_with_a_reminder_request(session, monkeypatch):
    offered = []

    class Fake:
        model = 'fake'

        def complete_tools(self, messages, tools):
            offered.extend(spec['function']['name'] for spec in tools)
            return {'content': '好，先不聊这个。你可以确认提醒草稿。'}

    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    monkeypatch.setattr(core, '_active_source_context', lambda _: pytest.fail('source context was read'))
    monkeypatch.setattr(core, '_source_excerpts', lambda *_: pytest.fail('source search was used'))
    result = core.generate_reply(session, '别再提失眠，提醒我喝水')
    assert result['action'] == 'model.reply'
    assert offered == ['propose_reminder']


def test_topic_decline_does_not_fall_back_to_source_summary_if_model_is_unavailable(session, monkeypatch):
    monkeypatch.setattr(core.model, 'from_env', lambda: None)
    monkeypatch.setattr(core, '_active_source_context', lambda _: pytest.fail('fallback read source context'))
    result = core.generate_reply(session, '别再提失眠，下一步怎么办')
    assert result['action'] != 'context.reply'
    assert '失眠' not in result['reply']


def test_decline_general_memory_suppresses_previous_context(session, monkeypatch):
    sent = []
    class Fake:
        model = 'fake'
        def complete(self, system, user):
            sent.append((system, user))
            return '好，我们聊咖啡。'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    core.add_memory(session, 'fact', '鲸鱼喜欢咖啡', status='confirmed')
    core.add_message(session, 'assistant', '旧对话鲸鱼')
    monkeypatch.setattr(core, '_active_source_context', lambda _: pytest.fail('source context was read'))
    monkeypatch.setattr(core, '_source_excerpts', lambda *_: pytest.fail('source search was used'))
    core.generate_reply(session, '别提我的记忆，聊聊咖啡')
    assert '鲸鱼' not in sent[-1][1]
    assert '别提我的记忆' in sent[-1][1]


def test_source_revoke_during_decline_discards_model_response(session, monkeypatch):
    core.attach_source_to_empty_session(session, '临时资料', '资料原文', {'facts': ['资料记忆']}, [], [], [], 'local')
    source_id = core.list_sources(session)[0]['id']
    class Fake:
        model = 'fake'
        def complete(self, system, user):
            assert core.revoke_source(session, source_id)['ok']
            return '这条生成期间来源已撤回的回复不应显示'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    result = core.generate_reply(session, '别再提失眠，换个话题')
    assert result['action'] == 'model.stale'
    assert '不应显示' not in result['reply']
    assert all('不应显示' not in m['text'] for m in result['messages'])
