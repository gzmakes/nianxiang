"""Legacy provenance tests; use only isolated synthetic sessions and data."""
import pytest
from server import core

@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'legacy.db'))
    core.init_db()


def legacy():
    d=core.create_session('connector', '来源正文', source_label='Gmail · 已连接',
        understanding={'facts':['来源事实'], 'inferences':[], 'questions':[]})
    sid=d['session']['id']
    core.set_session_context(sid,'gmail',[{'title':'来源事实'}],[])
    return sid,d['memories'][0]


def test_keep_user_words_delete_only_attributed_data_and_preserve_history():
    sid, original=legacy()
    manual=core.add_memory(sid,'fact','我的手动陈述',source='用户手动添加',status='confirmed')
    core._remember_candidate_once(sid, '我的对话陈述')
    proposal=core.add_memory(sid,'fact','用户选存的对话原话',source='对话原话 · 用户选存',status='confirmed')
    insight=core.add_memory(sid,'inference','来源洞察',source='Gmail · 只读')
    before=core.memory_history(manual['id'])
    out=core.revoke_source(sid)
    got={m['text']:m for m in core.list_memories(sid)}
    assert out['cleaned']==2 and out['review_required']==0
    assert set(got)=={'我的手动陈述','我的对话陈述','用户选存的对话原话'}
    assert got['用户选存的对话原话']['status']=='confirmed'
    assert core.memory_history(proposal['id'])
    assert core.memory_history(manual['id'])==before
    assert core.memory_history(original['id'])==[] and core.memory_history(insight['id'])==[]
    assert core.get_session(sid)['source_text']=='' and core.get_session_context(sid) is None
    assert core.get_session(sid)['mode']=='empty'


def test_ambiguous_and_edited_values_are_kept_quarantined_with_linked_copies(monkeypatch):
    sid, original=legacy()
    core.update_memory(original['id'],text='用户修改过的内容',status='confirmed')
    other=core.create_session('empty')['session']['id']
    assert core.import_carryover(other,[original['id']])['imported']==1
    unknown=core.add_memory(sid,'fact','来源不明的内容',source='旧数据',status='confirmed')
    out=core.revoke_source(sid)
    assert out['cleaned']==0 and out['review_required']==3
    assert {m['text'] for m in core.list_memories(sid)}=={'用户修改过的内容','来源不明的内容'}
    assert all(m['status']=='candidate' and m['source'].startswith(core.REVOKE_REVIEW_PREFIX) for m in core.list_memories(sid))
    assert core.list_memories(other)[0]['status']=='candidate'
    assert not core.carryover_memories(core.create_session('empty')['session']['id'])
    assert not any('用户修改过的内容' in x or '来源不明的内容' in x for g in core._memory_groups(sid) for x in g)
    assert '用户修改过的内容' not in core.suggest_next_step(sid)['step']
    assert len(core.memory_history(unknown['id']))==2
    core.update_memory(original['id'],status='confirmed')
    assert '用户修改过的内容' in core._memory_groups(sid)[0]
    assert core.list_memories(other)[0]['status']=='candidate'
    assert core.list_memories(other)[0]['source'].startswith(core.REVOKE_REVIEW_PREFIX)


def test_known_source_deletes_linked_copies_but_not_independently_edited_copy():
    sid, original=legacy()
    core.update_memory(original['id'],status='confirmed')
    b=core.create_session('empty')['session']['id']
    c=core.create_session('empty')['session']['id']
    core.import_carryover(b,[original['id']]);copy=core.list_memories(b)[0]
    core.import_carryover(c,[original['id']]);independent=core.list_memories(c)[0]
    core.update_memory(independent['id'],text='独立纠正')
    core.revoke_source(sid)
    assert not core.list_memories(sid) and not core.list_memories(b)
    assert core.list_memories(c)[0]['text']=='独立纠正'


def test_legacy_source_bookmark_is_not_automatically_recalled():
    sid,_=legacy()
    bm=core.create_bookmark(sid,'来源书签','选择','下一步')
    core.commit_bookmark(bm['id'])
    assert core.latest_bookmark(sid)
    core.revoke_source(sid)
    assert core.latest_bookmark(sid) is None
    conn=core.get_db()
    assert conn.execute('SELECT COUNT(*) FROM bookmarks WHERE session_id=?',(sid,)).fetchone()[0]==1
    conn.close()

@pytest.mark.parametrize('edit', [False, True])
def test_selected_message_memory_survives_legacy_revoke_without_demotion(edit):
    sid,_=legacy()
    message=core.add_message(sid,'user','我不喜欢被打断。')
    saved=core.save_proposed_memory(sid,message['id'])
    core.update_memory(saved['id'],status='confirmed')
    if edit: core.update_memory(saved['id'],text='我希望先说完',status='confirmed')
    before=next(m for m in core.list_memories(sid) if m['id']==saved['id'])
    assert before['source_message_id']==message['id']
    core.revoke_source(sid)
    after=next(m for m in core.list_memories(sid) if m['id']==saved['id'])
    assert after['text']==before['text'] and after['status']=='confirmed'
    assert after['source_message_id']==message['id'] and after['source']==before['source']
    assert after['text'] in core._memory_groups(sid)[0]
