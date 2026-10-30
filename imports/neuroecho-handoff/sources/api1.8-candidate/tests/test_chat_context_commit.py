"""Synthetic checks at the final context-check/assistant-commit boundary."""
from pathlib import Path
import sqlite3
import pytest
from server import core


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'commit.db'))
    monkeypatch.setattr(core.model, 'from_env', lambda: None)
    core.init_db()


def setup(monkeypatch):
    sid = core.create_session('empty')['session']['id']
    for label, text in [('A资料', 'PRIVATE_A_ONLY'), ('B资料', 'B_STAYS_VALID')]:
        core.attach_source_to_empty_session(sid, label, text, {'facts': [text]},
            [{'title': label, 'summary': text}], [], [], connector_id='local_files')
    aid = core.list_sources(sid)[0]['id']
    class Fake:
        model = 'synthetic'
        def complete(self, system, prompt):
            # This also proves there is no database lock during remote work.
            with sqlite3.connect(core.DB_PATH, timeout=0) as conn:
                conn.execute('UPDATE sessions SET title=title WHERE id=?', (sid,))
            return 'PRIVATE_A_ONLY 旧模型回答'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    return sid, aid


@pytest.mark.parametrize('operation', ['revoke', 'correct', 'attach'])
def test_change_after_post_model_stamp_check_is_checked_again_before_commit(monkeypatch, operation):
    sid, aid = setup(monkeypatch)
    original_audit = core.audit
    def audit(sid, action, detail='', reason=''):
        if action == 'model.success':
            if operation == 'revoke':
                core.revoke_source(sid, aid)
            elif operation == 'correct':
                memory = next(m for m in core.list_memories(sid) if m['source_attachment_id'] == aid)
                core.update_memory(memory['id'], text='用户更正的新值', status='confirmed')
            else:
                core.attach_source_to_empty_session(sid, 'C资料', '新上下文', {'facts': []}, [], [], [])
        return original_audit(sid, action, detail, reason)
    monkeypatch.setattr(core, 'audit', audit)
    result = core.generate_reply(sid, '想聊一下这份资料')
    assert result['action'] == 'model.stale'
    assert 'PRIVATE_A_ONLY' not in result['reply']
    assert not any(m['role'] == 'assistant' and 'PRIVATE_A_ONLY' in m['text'] for m in core.get_messages(sid))
    assert any(s['label'] == 'B资料' and not s['stale'] for s in core.list_sources(sid))


def test_final_stamp_uses_the_same_write_transaction_as_message_commit(monkeypatch):
    sid, _ = setup(monkeypatch)
    original_stamp = core._model_context_stamp
    checks = []
    def stamp(sid, conn=None):
        if conn is not None:
            assert conn.in_transaction
            with sqlite3.connect(core.DB_PATH, timeout=0) as other:
                with pytest.raises(sqlite3.OperationalError, match='locked'):
                    other.execute("UPDATE source_attachments SET stale=1 WHERE session_id=?", (sid,))
            checks.append(True)
        return original_stamp(sid, conn)
    monkeypatch.setattr(core, '_model_context_stamp', stamp)
    result = core.generate_reply(sid, '继续说')
    assert checks == [True] and result['action'] == 'model.reply'
    assert result['assistant_message_id'] in [m['id'] for m in core.get_messages(sid)]


def test_failure_after_assistant_insert_rolls_back_message_state_and_turn_audit(monkeypatch):
    sid, _ = setup(monkeypatch)
    original_stamp, original_now = core._model_context_stamp, core.now
    final = {'active': False, 'calls': 0}
    def stamp(sid, conn=None):
        result = original_stamp(sid, conn)
        if conn is not None:
            final['active'] = True
        return result
    def now():
        if final['active']:
            final['calls'] += 1
            if final['calls'] == 2:
                raise RuntimeError('synthetic audit failure after assistant insert')
        return original_now()
    monkeypatch.setattr(core, '_model_context_stamp', stamp)
    monkeypatch.setattr(core, 'now', now)
    with pytest.raises(RuntimeError, match='synthetic audit failure'):
        core.generate_reply(sid, '继续说')
    assert not any(m['role'] == 'assistant' and 'PRIVATE_A_ONLY' in m['text'] for m in core.get_messages(sid))
    assert core.get_session(sid)['state'] == 'listening'
    assert not any(e['action'] == 'chat.turn' for e in core.audit_list(sid))


def test_session_deleted_at_post_model_boundary_is_not_recreated(monkeypatch):
    sid, _ = setup(monkeypatch)
    original_audit = core.audit
    def audit(sid, action, detail='', reason=''):
        if action == 'model.success':
            core.delete_session(sid)
            return
        return original_audit(sid, action, detail, reason)
    monkeypatch.setattr(core, 'audit', audit)
    result = core.generate_reply(sid, '继续说')
    assert result['cancelled'] and core.get_session(sid) is None
    assert not core.get_messages(sid)
