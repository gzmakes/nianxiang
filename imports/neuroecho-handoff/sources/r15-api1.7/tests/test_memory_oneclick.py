"""Literal one-click confirmation, provenance, retry and model visibility."""
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from server import core, model
from server.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'oneclick.db'))
    monkeypatch.setattr(model, 'from_env', lambda: None)
    core.init_db()
    with TestClient(app) as c:
        yield c


def source(client, text='我希望你先听我说'):
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    mid = core.add_message(sid, 'user', text)['id']
    return sid, mid


def save(client, sid, mid, **extra):
    return client.post('/api/memory/proposal', json={'session_id': sid, 'message_id': mid, **extra})


def test_one_click_confirmed_memory_immediately_reaches_model_and_can_be_deleted(client, monkeypatch):
    sid, mid = source(client)
    assert core._memory_groups(sid)[0] == []
    saved = save(client, sid, mid, confirm=True).json()
    assert saved['status'] == 'confirmed' and saved['created'] and saved['confirmed_now']
    assert saved['source_message_id'] == mid
    captured = []
    class Fake:
        model = 'synthetic'
        def complete(self, system, user):
            captured.append(user)
            return '我先听着。'
    monkeypatch.setattr(model, 'from_env', lambda: Fake())
    core.generate_reply(sid, '今天有些事情想说')
    confirmed_block = captured[-1].split('【用户已确认的记忆】')[1].split('【')[0]
    assert '我希望你先听我说' in confirmed_block
    assert client.delete('/api/memory/' + saved['id']).status_code == 200
    assert core._memory_groups(sid)[0] == []


def test_legacy_default_stays_candidate_and_one_click_upgrade_is_idempotent(client):
    sid, mid = source(client)
    old = save(client, sid, mid).json()
    assert old['status'] == 'candidate' and old['version'] == 1
    assert not core._memory_groups(sid)[0]
    new = save(client, sid, mid, confirm=True).json()
    assert new['id'] == old['id'] and new['version'] == 2
    assert not new['created'] and new['confirmed_now']
    for confirmation in (True, False, True):
        same = save(client, sid, mid, confirm=confirmation).json()
        assert same['id'] == new['id'] and same['version'] == 2
        assert same['status'] == 'confirmed' and not same['created'] and not same['confirmed_now']
    assert len(core.memory_history(new['id'])) == 2


def test_concurrent_confirm_same_source_creates_one_confirmed_record_and_revision(client):
    sid, mid = source(client)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: core.save_proposed_memory(sid, mid, confirm=True), range(8)))
    assert len({r['id'] for r in results}) == 1
    assert sum(r['created'] for r in results) == 1
    assert sum(r['confirmed_now'] for r in results) == 1
    assert len(core.list_memories(sid)) == len(core.memory_history(results[0]['id'])) == 1


def test_same_text_document_memory_is_not_relabelled_and_quote_survives_source_revocation(client):
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    text = '我希望你先听我说'
    core.attach_source_to_empty_session(sid, '文档来源', text, {'facts': [text]}, [], [], [])
    derived = core.list_memories(sid)[0]
    mid = core.add_message(sid, 'user', text)['id']
    assert core.propose_from_message(sid, mid)['message_id'] == mid
    quote = save(client, sid, mid, confirm=True).json()
    assert quote['id'] != derived['id'] and quote['source_attachment_id'] is None
    assert quote['source'] == '对话原话 · 用户选存'
    assert core.list_memories(sid)[0]['source'] == derived['source']
    core.revoke_source(sid)
    remaining = core.list_memories(sid)
    assert [m['id'] for m in remaining] == [quote['id']]
    assert remaining[0]['status'] == 'confirmed' and core._memory_groups(sid)[0] == [text]


def test_same_text_manual_memory_is_preserved_without_reusing_its_identity(client):
    sid, mid = source(client)
    manual = core.add_memory(sid, 'fact', '我希望你先听我说', source='用户手动添加', status='confirmed')
    saved = save(client, sid, mid, confirm=True).json()
    assert saved['id'] != manual['id']
    unchanged = next(m for m in core.list_memories(sid) if m['id'] == manual['id'])
    assert unchanged['source'] == '用户手动添加' and unchanged['source_message_id'] is None


def test_repeating_stale_card_never_overwrites_user_correction(client):
    sid, mid = source(client)
    saved = save(client, sid, mid, confirm=True).json()
    core.update_memory(saved['id'], text='我有时希望先梳理')
    before = core.list_memories(sid)
    assert save(client, sid, mid, confirm=True).status_code == 409
    assert core.list_memories(sid) == before


@pytest.mark.parametrize('text', [
    '我希望你先听我说，我的手机号是13800138000',
    '我希望你先听我说吗？', '别人说我希望你先听我说',
    '我平时喜欢银行卡6222021234567890123', '记住：我希望你先听我说',
])
def test_confirmation_does_not_bypass_full_literal_allowlist(client, text):
    sid, mid = source(client, text)
    assert save(client, sid, mid, confirm=True).status_code == 409
    assert not core.list_memories(sid)


@pytest.mark.parametrize('confirm', ['true', 1, 0, None, [], {}])
def test_confirm_requires_an_actual_boolean(client, confirm):
    sid, mid = source(client)
    assert save(client, sid, mid, confirm=confirm).status_code == 422
    assert not core.list_memories(sid)


def test_wrong_session_and_assistant_source_cannot_be_confirmed(client):
    sid, mid = source(client)
    other, _ = source(client)
    assistant = core.add_message(sid, 'assistant', '我希望你先听我说')['id']
    assert save(client, other, mid, confirm=True).status_code == 409
    assert save(client, sid, assistant, confirm=True).status_code == 409
    assert core.list_memories(sid) == core.list_memories(other) == []


def test_explicit_remember_command_and_inferences_remain_candidates(client):
    sid, _ = source(client)
    result = client.post('/api/chat', json={'session_id': sid, 'text': '记住：我希望你先听我说'}).json()
    assert result['memories'][0]['status'] == 'candidate'
    inferred = core.add_memory(sid, 'inference', '推测喜欢安静')
    assert inferred['status'] == 'candidate'
