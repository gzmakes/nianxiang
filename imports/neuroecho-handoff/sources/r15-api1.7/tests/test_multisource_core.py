"""Only synthetic data: append, migration, scoped revocation and model isolation."""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import pytest
from server import core


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'sources.db'))
    monkeypatch.setattr(core.model, 'from_env', lambda: None)
    core.init_db()


def session():
    return core.create_session('empty')['session']['id']


def attach(sid, title, text=None, *, connector='local_files', label=None):
    text = text or f'{title} 的专属内容与下一步'
    core.attach_source_to_empty_session(sid, label or title, text,
        {'facts': [text], 'inferences': [], 'questions': []},
        [{'title': title, 'summary': text}], [], [], connector_id=connector)
    return core.list_sources(sid)[-1]['id']


def capture(monkeypatch):
    prompts = []
    class Fake:
        model = 'synthetic'
        def complete(self, system, user):
            prompts.append(user)
            return '合成模型回复'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    return prompts


def test_append_preserves_conversation_and_exposes_distinct_metadata_without_raw_text():
    sid = session()
    prior = core.add_message(sid, 'user', '先说完今天的事情')
    a = attach(sid, 'first.md', '相同正文', label='本地文件 · 用户选择')
    b = attach(sid, 'second.md', '相同正文', label='本地文件 · 用户选择')
    context = core.get_session_context(sid)
    assert context['connector_id'] == 'multiple' and a != b
    assert [s['title'] for s in context['sources']] == ['first.md', 'second.md']
    assert [item['source_id'] for item in context['items']] == [a, b]
    assert all('source_text' not in s for s in context['sources'])
    assert prior['id'] in [m['id'] for m in core.get_messages(sid)]
    assert {m['source_attachment_id'] for m in core.list_memories(sid)} == {a, b}
    core.init_db(); core.init_db()
    assert [s['id'] for s in core.list_sources(sid)] == [a, b]


def test_duplicate_is_rejected_but_different_provider_title_or_body_is_not():
    sid = session()
    attach(sid, 'same', 'same body')
    with pytest.raises(core.SourceConflict):
        attach(sid, 'same', 'same body')
    attach(sid, 'other title', 'same body')
    attach(sid, 'same', 'same body', connector='feishu')
    attach(sid, 'same', 'different body')
    assert len(core.list_sources(sid)) == 4


def test_concurrent_distinct_attach_and_eight_source_limit_are_atomic():
    sid = session()
    def add(index):
        try:
            attach(sid, f'资料{index}')
            return True
        except core.SourceConflict:
            return False
    with ThreadPoolExecutor(max_workers=10) as pool:
        outcomes = list(pool.map(add, range(10)))
    assert sum(outcomes) == len(core.list_sources(sid)) == 8
    assert len({s['id'] for s in core.list_sources(sid)}) == 8
    assert len(core.list_memories(sid)) == 8


def test_single_revoke_deletes_only_its_lineage_and_excludes_old_dialogue(monkeypatch):
    sid, other = session(), session()
    personal = core.add_memory(sid, 'fact', '自己的独立选择', source='用户手动添加', status='confirmed')
    a = attach(sid, 'A文档', 'PRIVATE_A_ONLY 专属资料')
    b = attach(sid, 'B文档', 'PUBLIC_B_STILL_USABLE 专属资料')
    memory = next(m for m in core.list_memories(sid) if m['source_attachment_id'] == a)
    core.update_memory(memory['id'], status='confirmed')
    core.import_carryover(other, [memory['id']])
    core.add_message(sid, 'assistant', 'PRIVATE_A_ONLY 曾出现在回答里')
    result = core.revoke_source(sid, a)
    assert result['remaining_sources'] == 1 and result['cleaned'] == 1
    assert not core.list_memories(other)
    assert {m['id'] for m in core.list_memories(sid)} == {personal['id']} | {
        m['id'] for m in core.list_memories(sid) if m['source_attachment_id'] == b}
    assert core.get_session_context(sid)['connector_id'] == 'local_files'
    prompts = capture(monkeypatch)
    core.generate_reply(sid, 'PUBLIC_B_STILL_USABLE 的资料是什么？')
    assert 'PUBLIC_B_STILL_USABLE' in prompts[-1] and 'PRIVATE_A_ONLY' not in prompts[-1]
    assert core.get_session(sid)['source_revoked'] == 0


@pytest.mark.parametrize('operation', ['edit', 'delete'])
def test_memory_change_stales_only_its_source_and_preserves_other_source(monkeypatch, operation):
    sid = session()
    a = attach(sid, 'A文档', 'OLD_A_MUST_DISAPPEAR 旧偏好')
    b = attach(sid, 'B文档', 'CURRENT_B_IS_VALID 有效资料')
    memory = next(m for m in core.list_memories(sid) if m['source_attachment_id'] == a)
    core.add_message(sid, 'assistant', 'OLD_A_MUST_DISAPPEAR 历史解释')
    if operation == 'edit':
        core.update_memory(memory['id'], text='NEW_A_CORRECTION', status='confirmed')
    else:
        core.delete_memory(memory['id'])
    assert {s['id']:s['stale'] for s in core.list_sources(sid)} == {a: True, b: False}
    assert core.get_session(sid)['source_context_stale'] == 0
    prompts = capture(monkeypatch)
    core.generate_reply(sid, 'CURRENT_B_IS_VALID 的依据')
    assert 'CURRENT_B_IS_VALID' in prompts[-1] and 'OLD_A_MUST_DISAPPEAR' not in prompts[-1]
    if operation == 'edit':
        # A correction remains available, but a B-only question does not make
        # an unrelated A memory relevant. A direct recall request can see it.
        assert 'NEW_A_CORRECTION' not in prompts[-1]
        core.generate_reply(sid, '你记得我吗')
        assert 'NEW_A_CORRECTION' in prompts[-1]
        assert 'OLD_A_MUST_DISAPPEAR' not in prompts[-1]


def test_personal_memory_edit_does_not_stale_any_new_source():
    sid = session()
    attach(sid, 'A'); attach(sid, 'B')
    personal = core.add_memory(sid, 'fact', '自己的话', source='用户手动添加')
    core.update_memory(personal['id'], text='自己的新说法', status='confirmed')
    assert not any(s['stale'] for s in core.list_sources(sid))


def test_legacy_correction_remains_conservative_without_disabling_fresh_source(monkeypatch):
    old = core.create_session('paste', 'LEGACY_OLD 旧内容', source_label='原来的资料',
                              understanding={'facts':['LEGACY_OLD 旧内容'],'inferences':[],'questions':[]})
    sid = old['session']['id']
    legacy_id = core.list_sources(sid)[0]['id']
    b = attach(sid, '新资料', 'CURRENT_B_IS_VALID')
    core.update_memory(old['memories'][0]['id'], text='LEGACY_CORRECTED', status='confirmed')
    assert {s['id']:s['stale'] for s in core.list_sources(sid)} == {legacy_id: True, b: False}
    result = core.revoke_source(sid, legacy_id)
    assert result['review_required'] == 1 and result['remaining_sources'] == 1
    prompts = capture(monkeypatch)
    core.generate_reply(sid, 'CURRENT_B_IS_VALID 的内容')
    assert 'CURRENT_B_IS_VALID' in prompts[-1] and 'LEGACY_OLD' not in prompts[-1]
    assert 'LEGACY_CORRECTED' not in prompts[-1]


def test_migration_of_previous_known_attachment_keeps_id_and_never_revives_revoke():
    sid = session(); original_id = attach(sid, '历史文档', '历史内容')
    conn = core.get_db(); conn.execute('DROP TABLE source_attachments'); conn.commit(); conn.close()
    core.init_db()
    assert core.list_sources(sid)[0]['id'] == original_id
    assert core.revoke_source(sid, original_id)['cleaned'] == 1
    core.init_db(); core.init_db()
    assert core.list_sources(sid) == [] and core.get_session_context(sid) is None
    assert core.get_session(sid)['source_revoked'] == 1


def test_truly_old_database_migration_is_repeatable_and_respects_revoked_flag(tmp_path, monkeypatch):
    path = tmp_path / 'old.db'
    with sqlite3.connect(path) as conn:
        conn.executescript('''CREATE TABLE sessions(id TEXT PRIMARY KEY,created_at TEXT,mode TEXT,
            source_text TEXT,source_label TEXT,state TEXT,source_revoked INTEGER DEFAULT 0);
            INSERT INTO sessions VALUES('old','2020','paste','旧正文','旧资料','listening',0);
            INSERT INTO sessions VALUES('revoked','2020','paste','不可复活正文','撤回资料','revoked',1);''')
    monkeypatch.setattr(core, 'DB_PATH', str(path))
    core.init_db(); source_id = core.list_sources('old')[0]['id']; core.init_db()
    assert core.list_sources('old')[0]['id'] == source_id
    assert core.list_sources('revoked') == []
    core.revoke_source('old', source_id); core.init_db()
    assert core.list_sources('old') == []


@pytest.mark.parametrize('change', ['attach', 'revoke', 'edit_body'])
def test_source_changes_invalidate_inflight_model_even_if_metadata_timestamp_unchanged(monkeypatch, change):
    sid = session(); attachment = attach(sid, '材料', '旧正文')
    class Fake:
        model = 'synthetic'
        def complete(self, system, user):
            if change == 'attach':
                attach(sid, '新资料', '新正文')
            elif change == 'revoke':
                core.revoke_source(sid, attachment)
            else:
                conn = core.get_db()
                conn.execute('UPDATE source_attachments SET source_text=? WHERE id=?', ('新正文', attachment))
                conn.commit(); conn.close()
            return '旧模型结果不可展示'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    result = core.generate_reply(sid, '正文内容')
    assert result['action'] == 'model.stale' and result['reply'] != '旧模型结果不可展示'


def test_aggregate_is_fair_and_retrieval_has_one_labelled_window_per_relevant_source():
    sid = session()
    for index in range(8):
        core.attach_source_to_empty_session(sid, f'资料{index}', f'共同关键词 合成内容{index}', {'facts':[]},
            [{'title':f'{index}-{j}', 'summary':f'共同关键词{index}'} for j in range(4)],
            [{'type':'observation','title':f'洞察{index}','text':'合成'}], [f'问题{index}'], connector_id='local_files')
    context = core.get_session_context(sid)
    assert len({item['source_id'] for item in context['items'][:8]}) == 8
    assert len({item['source_id'] for item in context['insights']}) == 8
    excerpts = core._source_excerpts(sid, '共同关键词')
    assert len(excerpts) == 8 and sum(map(len, excerpts)) <= 3200
    assert all(f'资料{i}' in excerpts[i] for i in range(8))


def test_single_source_retains_three_distinct_matches_and_multisource_rotates_first_windows():
    sid = session()
    text = '关键词第一段' + '甲' * 600 + '关键词第二段' + '乙' * 600 + '关键词第三段'
    attach(sid, 'A资料', text)
    single = core._source_excerpts(sid, '关键词')
    assert len(single) == 3
    assert all(any(marker in excerpt for excerpt in single) for marker in ('第一段', '第二段', '第三段'))
    attach(sid, 'B资料', text)
    multiple = core._source_excerpts(sid, '关键词')
    assert len(multiple) == 6
    assert ['来源：A资料' in excerpt for excerpt in multiple] == [True, False, True, False, True, False]
    assert sum(map(len, multiple)) <= 3200


def test_bookmark_source_marker_preserves_other_source_and_rejects_foreign_marker():
    sid, other = session(), session()
    a = attach(sid, 'A'); b = attach(sid, 'B'); foreign = attach(other, '外部资料')
    with pytest.raises(ValueError):
        core.create_bookmark(sid, '错误来源', '', '', source_attachment_id=foreign)
    ba = core.create_bookmark(sid, 'A断点', '', '', source_attachment_id=a)
    bb = core.create_bookmark(sid, 'B断点', '', '', source_attachment_id=b)
    memory = next(m for m in core.list_memories(sid) if m['source_attachment_id'] == b)
    inferred = core.create_bookmark(sid, 'B记忆断点', '', '', source_memory_id=memory['id'])
    assert inferred['source_attachment_id'] == b
    core.revoke_source(sid, a)
    rows = {b['id']: b for b in core.export_data(sid)['bookmarks']}
    assert rows[ba['id']]['recallable'] == 0
    assert rows[bb['id']]['recallable'] == rows[inferred['id']]['recallable'] == 1
    assert core.latest_bookmark(sid)['id'] == inferred['id']


def test_deleting_session_clears_all_sources_and_unknown_id_cannot_remove_another_session():
    a, b = session(), session()
    aid = attach(a, 'A'); bid = attach(b, 'B')
    assert core.revoke_source(a, bid)['ok'] is False
    assert core.list_sources(a)[0]['id'] == aid
    result = core.delete_session(a)
    assert result['deleted']['source_attachments'] == 1
    assert core.list_sources(a) == [] and core.list_sources(b)[0]['id'] == bid
