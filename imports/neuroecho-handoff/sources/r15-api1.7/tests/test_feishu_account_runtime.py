"""Isolated synthetic tests of the account tools, provenance and revocation races."""
import json

import pytest

from server import agent_runtime, core, feishu_account, lark


ACCOUNT = 'a' * 64
DOC_A = 'https://example.feishu.cn/docx/SyntheticAlpha'
DOC_B = 'https://example.feishu.cn/docx/SyntheticBeta'


def tool(name, arguments, ident):
    return {'id': ident, 'type': 'function', 'function': {
        'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'account-runtime.db'))
    monkeypatch.setattr(core.model, 'from_env', lambda: None)
    status = {'ok': True, 'user_status': 'ready', 'token_status': 'valid',
              'account_key': ACCOUNT, 'scopes': list(lark.ACCOUNT_READ_SCOPES)}
    monkeypatch.setattr(lark, 'auth_status', lambda: dict(status))
    monkeypatch.setattr(lark, 'search_docs', lambda query, limit=8: {
        'ok': True, 'items': [{'title': '合成甲资料', 'url': DOC_A, 'type': 'docx'},
                               {'title': '合成乙资料', 'url': DOC_B, 'type': 'docx'}]})
    def read_doc(url, *, identity):
        assert identity == 'user'
        return {'ok': True, 'title': '合成甲资料' if url == DOC_A else '合成乙资料',
                'text': 'SYNTHETIC_ACCOUNT_ALPHA' if url == DOC_A else 'SYNTHETIC_ACCOUNT_BETA'}
    monkeypatch.setattr(lark, 'read_doc', read_doc)
    core.init_db()
    return status


def session(*, connected=True):
    sid = core.create_session('empty')['session']['id']
    if connected:
        with core.get_db() as conn:
            feishu_account.set_enabled(conn, sid, True, ACCOUNT)
    return sid


class TwoDocumentClient:
    model = 'synthetic-account-tools'

    def __init__(self):
        self.steps = []

    def complete_tools(self, messages, tools):
        self.steps.append((list(messages), tools))
        names = {spec['function']['name'] for spec in tools}
        assert names == {'search_feishu_documents', 'read_feishu_document'}
        assert '无需让用户先选一篇' in messages[0]['content']
        if len(self.steps) == 1:
            return {'tool_calls': [tool('search_feishu_documents', {'query': '演示重点'}, 'search')]}
        if len(self.steps) == 2:
            assert '合成甲资料' in messages[-1]['content']
            return {'tool_calls': [tool('read_feishu_document', {'url': DOC_A}, 'read-a'),
                                   tool('read_feishu_document', {'url': DOC_B}, 'read-b')]}
        assert 'SYNTHETIC_ACCOUNT_ALPHA' in messages[-2]['content']
        assert 'SYNTHETIC_ACCOUNT_BETA' in messages[-1]['content']
        return {'content': '综合本轮两篇资料：SYNTHETIC_ACCOUNT_ALPHA 和 SYNTHETIC_ACCOUNT_BETA。'}


def test_connected_account_without_attached_document_reads_multiple_sources(monkeypatch):
    sid = session()
    client = TwoDocumentClient()
    monkeypatch.setattr(core.model, 'from_env', lambda: client)
    result = core.generate_reply(sid, '这场演示有哪些重点？')
    assert result['action'] == 'model.reply'
    assert len(client.steps) == 3
    assert core.list_sources(sid) == []
    assert core.list_memories(sid) == [], 'account reads must not become derived memories'
    reply = next(row for row in result['messages'] if row['id'] == result['assistant_message_id'])
    assert reply['citations'] == [
        {'kind': 'feishu_document', 'title': '合成甲资料', 'url': DOC_A, 'text': '合成甲资料'},
        {'kind': 'feishu_document', 'title': '合成乙资料', 'url': DOC_B, 'text': '合成乙资料'}]
    with core.get_db() as conn:
        assert 'SYNTHETIC_ACCOUNT_ALPHA' not in str([tuple(row) for row in conn.execute('SELECT * FROM audit')])


def test_ordinary_companionship_can_answer_without_search(monkeypatch):
    sid = session()
    monkeypatch.setattr(lark, 'search_docs', lambda *args, **kwargs: pytest.fail('ordinary chat searched documents'))
    class Companion:
        model = 'synthetic'
        def complete_tools(self, messages, tools):
            assert {t['function']['name'] for t in tools} == {'search_feishu_documents', 'read_feishu_document'}
            return {'content': '我在，今天可以慢慢说。'}
    monkeypatch.setattr(core.model, 'from_env', lambda: Companion())
    result = core.generate_reply(sid, '想有人陪我聊聊')
    assert result['action'] == 'model.reply'
    assert next(m for m in result['messages'] if m['id'] == result['assistant_message_id'])['citations'] == []


@pytest.mark.parametrize('failure', ['expired', 'unavailable'])
def test_unavailable_account_does_not_block_ordinary_companionship(monkeypatch, isolated, failure):
    sid = session()
    isolated.update({'token_status': 'expired'} if failure == 'expired' else {'ok': False})
    monkeypatch.setattr(lark, 'search_docs', lambda *args, **kwargs: pytest.fail('ordinary chat searched Feishu'))
    monkeypatch.setattr(lark, 'read_doc', lambda *args, **kwargs: pytest.fail('ordinary chat read Feishu'))
    class Companion:
        model = 'synthetic'
        def complete_tools(self, messages, tools):
            return {'content': '我在，今天想怎么聊都可以。'}
    monkeypatch.setattr(core.model, 'from_env', lambda: Companion())
    result = core.generate_reply(sid, '今天想有人陪我说说话')
    assert result['action'] == 'model.reply'
    assert result['reply'] == '我在，今天想怎么聊都可以。'
    assert next(m for m in result['messages'] if m['id'] == result['assistant_message_id'])['citations'] == []
    assert not any(a['action'] in ('model.stale', 'model.fallback') for a in core.audit_list(sid))


@pytest.mark.parametrize('failure', ['expired', 'unavailable'])
def test_unavailable_account_tool_error_reaches_model_without_fake_data(monkeypatch, isolated, failure):
    sid = session()
    isolated.update({'token_status': 'expired'} if failure == 'expired' else {'ok': False})
    monkeypatch.setattr(lark, 'search_docs', lambda *args, **kwargs: pytest.fail('unauthorized real search was attempted'))
    monkeypatch.setattr(lark, 'read_doc', lambda *args, **kwargs: pytest.fail('unauthorized real read was attempted'))
    class Client:
        model = 'synthetic'
        step = 0
        def complete_tools(self, messages, tools):
            self.step += 1
            if self.step == 1:
                return {'tool_calls': [tool('search_feishu_documents', {'query': '演示安排'}, 'search')]}
            result = json.loads(messages[-1]['content'])
            assert not result['ok']
            assert result['error_code'] == ('authorization_not_ready' if failure == 'expired' else 'authorization_unavailable')
            assert not result.get('items') and not result.get('text')
            return {'content': '飞书授权暂时不可用，我还没读到文档。重新连接后可以再查。'}
    client = Client()
    monkeypatch.setattr(core.model, 'from_env', lambda: client)
    result = core.generate_reply(sid, '帮我查查飞书里的演示安排')
    assert client.step == 2
    assert result['action'] == 'model.reply' and '还没读到文档' in result['reply']
    assert next(m for m in result['messages'] if m['id'] == result['assistant_message_id'])['citations'] == []
    assert not any(a['action'] in ('model.stale', 'model.fallback') for a in core.audit_list(sid))


def test_database_disconnect_still_invalidates_reply_without_account_context(monkeypatch):
    sid = session()
    class Companion:
        model = 'synthetic'
        def complete_tools(self, messages, tools):
            with core.get_db() as conn:
                feishu_account.set_enabled(conn, sid, False)
                core._invalidate_history(conn, {sid})
            return {'content': 'SYNTHETIC_OLD_REPLY'}
    monkeypatch.setattr(core.model, 'from_env', lambda: Companion())
    result = core.generate_reply(sid, '陪我聊聊')
    assert result['action'] == 'model.stale'
    assert 'SYNTHETIC_OLD_REPLY' not in result['reply']


def test_search_titles_and_fabricated_read_never_become_document_citations(monkeypatch):
    sid = session()
    class Client:
        model = 'synthetic'
        step = 0
        def complete_tools(self, messages, tools):
            self.step += 1
            if self.step == 1:
                return {'tool_calls': [tool('read_feishu_document', {'url': DOC_A}, 'not-searched')]}
            if self.step == 2:
                assert 'document_not_in_search' in messages[-1]['content']
                return {'tool_calls': [tool('search_feishu_documents', {'query': '测试'}, 'titles-only')]}
            return {'content': '只找到了标题，还没有读取正文。'}
    monkeypatch.setattr(core.model, 'from_env', lambda: Client())
    result = core.generate_reply(sid, '帮我查一下文档')
    assert result['action'] == 'model.reply'
    assert next(m for m in result['messages'] if m['id'] == result['assistant_message_id'])['citations'] == []


def test_long_document_keyword_read_reaches_model_as_disclosed_excerpt(monkeypatch):
    sid = session()
    def read_doc(url, *, identity, keyword=''):
        assert (url, identity, keyword) == (DOC_A, 'user', '验收指标')
        return {'ok': True, 'title': '合成长文后段', 'text': 'SYNTHETIC_LATE_SECTION',
                'partial': True, 'excerpt': True, 'read_scope': 'keyword'}
    monkeypatch.setattr(lark, 'read_doc', read_doc)
    class Client:
        model = 'synthetic'
        step = 0
        def complete_tools(self, messages, tools):
            self.step += 1
            if self.step == 1:
                return {'tool_calls': [tool('search_feishu_documents', {'query': '演示方案'}, 'search')]}
            if self.step == 2:
                return {'tool_calls': [tool('read_feishu_document', {'url': DOC_A, 'query': '验收指标'}, 'read')]}
            result = json.loads(messages[-1]['content'])
            assert result['partial'] and result['excerpt'] and result['read_scope'] == 'keyword'
            assert result['text'] == 'SYNTHETIC_LATE_SECTION'
            return {'content': '我核对了与验收指标相关的正文节选：SYNTHETIC_LATE_SECTION。'}
    monkeypatch.setattr(core.model, 'from_env', lambda: Client())
    result = core.generate_reply(sid, '演示方案里的验收指标是什么？')
    assert result['action'] == 'model.reply' and 'SYNTHETIC_LATE_SECTION' in result['reply']
    reply = next(m for m in result['messages'] if m['id'] == result['assistant_message_id'])
    assert reply['citations'][0]['url'] == DOC_A


@pytest.mark.parametrize('boundary', ['during_model', 'after_model'])
def test_disconnect_invalidates_in_flight_reply_and_real_read_links(monkeypatch, boundary):
    sid = session()
    base = TwoDocumentClient()
    def disconnect():
        with core.get_db() as conn:
            feishu_account.set_enabled(conn, sid, False)
            core._invalidate_history(conn, {sid})
    class Client:
        model = 'synthetic'
        def complete_tools(self, messages, tools):
            answer = base.complete_tools(messages, tools)
            if len(base.steps) == 3 and boundary == 'during_model':
                disconnect()
            return answer
    monkeypatch.setattr(core.model, 'from_env', lambda: Client())
    original_audit = core.audit
    def audit(sid, action, detail='', reason=''):
        if action == 'model.success' and boundary == 'after_model':
            disconnect()
        return original_audit(sid, action, detail, reason)
    monkeypatch.setattr(core, 'audit', audit)
    result = core.generate_reply(sid, '帮我总结演示资料')
    assert result['action'] == 'model.stale'
    assert 'SYNTHETIC_ACCOUNT' not in result['reply']
    reply = next(m for m in result['messages'] if m['id'] == result['assistant_message_id'])
    assert reply['citations'] == []


def test_external_cli_account_switch_after_model_is_blocked_before_commit(monkeypatch, isolated):
    sid = session()
    monkeypatch.setattr(core.model, 'from_env', lambda: TwoDocumentClient())
    original_audit = core.audit
    def audit(sid, action, detail='', reason=''):
        if action == 'model.success':
            isolated['account_key'] = 'b' * 64
        return original_audit(sid, action, detail, reason)
    monkeypatch.setattr(core, 'audit', audit)
    result = core.generate_reply(sid, '帮我总结演示资料')
    assert result['action'] == 'model.stale'
    assert 'SYNTHETIC_ACCOUNT' not in result['reply']
    assert next(m for m in result['messages'] if m['id'] == result['assistant_message_id'])['citations'] == []


@pytest.mark.parametrize('change', ['disconnect', 'cli_switch'])
def test_account_change_after_read_stops_next_model_send(monkeypatch, isolated, change):
    sid = session()
    base_access = feishu_account.TurnAccess
    read_completed = []
    class Access(base_access):
        def read(self, url, query=''):
            result = super().read(url, query=query)
            assert result['ok']
            read_completed.append(url)
            # The document has returned to the runtime, so its tool response
            # would be sent to the model unless the next round checks access.
            if url == DOC_B:
                if change == 'disconnect':
                    with core.get_db() as conn:
                        feishu_account.set_enabled(conn, sid, False)
                        core._invalidate_history(conn, {sid})
                else:
                    isolated['account_key'] = 'b' * 64
            return result
    monkeypatch.setattr(feishu_account, 'TurnAccess', Access)
    client = TwoDocumentClient()
    monkeypatch.setattr(core.model, 'from_env', lambda: client)
    result = core.generate_reply(sid, '帮我总结演示资料')
    assert read_completed == [DOC_A, DOC_B]
    assert len(client.steps) == 2, 'account tool bodies must not be sent after revocation or CLI account switch'
    assert result['action'] == 'model.stale'
    assert 'SYNTHETIC_ACCOUNT' not in result['reply']
    assert next(m for m in result['messages'] if m['id'] == result['assistant_message_id'])['citations'] == []


def test_connection_state_changes_model_and_reminder_stamps():
    sid = session(connected=False)
    stamp = core._model_context_stamp(sid)
    with core.get_db() as conn:
        draft_stamp = agent_runtime.context_stamp(conn, sid)
        feishu_account.set_enabled(conn, sid, True, ACCOUNT)
    assert core._model_context_stamp(sid) != stamp
    with core.get_db() as conn:
        assert agent_runtime.context_stamp(conn, sid) != draft_stamp


def test_disconnect_omits_old_account_history_but_preserves_visible_messages(monkeypatch):
    sid = session()
    core.add_message(sid, 'assistant', 'SYNTHETIC_ACCOUNT_HISTORY')
    with core.get_db() as conn:
        feishu_account.set_enabled(conn, sid, False)
        core._invalidate_history(conn, {sid})
    class Client:
        model = 'synthetic'
        def complete(self, system, user):
            assert 'SYNTHETIC_ACCOUNT_HISTORY' not in user
            return '只根据你现在的问题来聊。'
        def complete_tools(self, *args):
            pytest.fail('disconnected account offered tools')
    monkeypatch.setattr(core.model, 'from_env', lambda: Client())
    result = core.generate_reply(sid, '继续说说')
    assert result['action'] == 'model.reply'
    assert any(m['text'] == 'SYNTHETIC_ACCOUNT_HISTORY' for m in result['messages'])


def test_deleted_conversation_does_not_retain_account_connection():
    sid = session()
    core.delete_session(sid)
    with core.get_db() as conn:
        assert not conn.execute('SELECT 1 FROM feishu_account_connections WHERE session_id=?', (sid,)).fetchone()
