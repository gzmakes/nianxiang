"""A deleted conversation is not revived by a late remote completion."""
import pytest
from server import core


@pytest.mark.parametrize('fails', [False, True])
def test_deleted_during_remote_call_does_not_restore_messages_or_audit(tmp_path, monkeypatch, fails):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'deleted.db'))
    core.init_db()
    sid = core.create_session('empty')['session']['id']
    class DeletionDuringCall:
        model = 'isolated-test'
        def complete(self, system, prompt):
            core.delete_session(sid)
            if fails:
                raise core.model.ModelError('timeout')
            return '删除前生成的旧回复'
    monkeypatch.setattr(core.model, 'from_env', lambda: DeletionDuringCall())
    result = core.generate_reply(sid, '这段请听我说')
    assert result['cancelled'] is True
    assert result['assistant_message_id'] is None
    assert core.get_session(sid) is None
    assert not core.get_messages(sid)
    conn = core.get_db()
    assert conn.execute('SELECT COUNT(*) FROM audit WHERE session_id=?', (sid,)).fetchone()[0] == 0
    conn.close()
