"""Cross-session updates must never silently revive older memory text."""
import pytest
from server import core


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'lineage.db'))
    core.init_db()


def session():
    return core.create_session('empty')['session']['id']


def imported(source_id, target):
    assert core.import_carryover(target, [source_id])['imported'] == 1
    return core.list_memories(target)[0]


def test_source_updates_linked_memory_and_old_chat_is_not_reintroduced(db, monkeypatch):
    captured = []
    class Fake:
        model = 'fake'
        def complete(self, system, user):
            captured.append(user)
            return '收到'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    a, b = session(), session()
    original = core.add_memory(a, 'fact', '喜欢绿茶', status='confirmed')
    copy = imported(original['id'], b)
    assert copy['origin_memory_id'] == original['id']
    core.add_message(b, 'assistant', '你喜欢绿茶')
    core.update_memory(original['id'], text='喜欢红茶', status='confirmed')
    updated = core.list_memories(b)[0]
    assert updated['text'] == '喜欢红茶' and updated['version'] == 2
    assert [r['text'] for r in core.memory_history(copy['id'])] == ['喜欢绿茶', '喜欢红茶']
    core.generate_reply(b, '我喜欢什么？')
    assert '喜欢红茶' in captured[-1] and '喜欢绿茶' not in captured[-1]


def test_user_edit_detaches_copy_and_its_descendants_follow_it(db):
    a, b, c = session(), session(), session()
    original = core.add_memory(a, 'fact', '喜欢绿茶', status='confirmed')
    copy = imported(original['id'], b)
    descendant = imported(copy['id'], c)
    core.update_memory(copy['id'], text='喜欢咖啡')
    core.update_memory(original['id'], text='喜欢红茶')
    assert core.list_memories(b)[0]['text'] == '喜欢咖啡'
    assert core.list_memories(b)[0]['origin_memory_id'] is None
    assert core.list_memories(c)[0]['text'] == '喜欢咖啡'
    assert core.list_memories(c)[0]['origin_memory_id'] == copy['id']
    core.delete_memory(original['id'])
    assert core.list_memories(b) and core.list_memories(c)


@pytest.mark.parametrize('method', ['delete_memory', 'revoke_source', 'delete_session'])
def test_deleted_source_clears_linked_copies_and_old_history(db, monkeypatch, method):
    captured = []
    class Fake:
        model = 'fake'
        def complete(self, system, user):
            captured.append(user)
            return '收到'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    a, b, c = session(), session(), session()
    original = core.add_memory(a, 'fact', '秘密原值', status='confirmed')
    if method == 'revoke_source':
        core.set_session_context(a, 'test', [{'title': '秘密原值'}], [])
    copy = imported(original['id'], b)
    imported(copy['id'], c)
    core.add_message(c, 'assistant', '你说过秘密原值')
    if method == 'delete_memory': core.delete_memory(original['id'])
    elif method == 'revoke_source': core.revoke_source(a)
    else: core.delete_session(a)
    if method == 'revoke_source':
        # Legacy unlabeled data cannot be confidently attributed, so retain
        # both linked copies for review while excluding them from inference.
        assert all(core.list_memories(s)[0]['status'] == 'candidate' and
                   core.list_memories(s)[0]['source'].startswith(core.REVOKE_REVIEW_PREFIX)
                   for s in (b, c))
    else:
        assert core.list_memories(b) == [] and core.list_memories(c) == []
    core.generate_reply(c, '你好')
    assert '秘密原值' not in captured[-1]


def test_legacy_unlinked_copies_require_confirmation(db, monkeypatch, legacy_schema_without_changes):
    a = session()
    legacy = core.add_memory(a, 'fact', '旧版拷贝', source='跨会话 · 你确认过', status='confirmed')
    conn = core.get_db()
    legacy_schema_without_changes(conn)
    conn.execute('ALTER TABLE memories DROP COLUMN origin_memory_id')
    conn.commit(); conn.close()
    core.init_db()
    migrated = core.list_memories(a)[0]
    assert migrated['status'] == 'candidate'
    assert '旧版拷贝' not in sum((list(g) for g in core._memory_groups(a)), [])
    core.update_memory(legacy['id'], status='confirmed')
    assert '旧版拷贝' in core._memory_groups(a)[0]


def test_change_during_completion_does_not_display_old_model_result(db, monkeypatch):
    a = session()
    memory = core.add_memory(a, 'fact', '旧信息', status='confirmed')
    class Fake:
        model = 'fake'
        def complete(self, system, user):
            core.update_memory(memory['id'], text='新信息')
            return '旧信息'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    reply = core.generate_reply(a, '你记得什么？')
    assert reply['action'] == 'model.stale'
    assert reply['reply'] != '旧信息'
