"""Generic connector boilerplate is not used as personal conversation context."""
import pytest
from fastapi.testclient import TestClient
from server import core
from server.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'memory.db'))
    core.init_db()
    return TestClient(app)


def test_generic_source_fragments_remain_in_records_but_are_not_sent_as_memory(client):
    sid = client.post('/api/session', json={'mode':'empty'}).json()['session']['id']
    q = core.add_memory(sid, 'question', '「黑客松海报制作」需要我先帮你做什么？', source='提醒事项', status='candidate')
    i = core.add_memory(sid, 'inference', '洞察（pattern）：本次展示 5 条提醒', source='提醒事项', status='candidate')
    user = core.add_memory(sid, 'question', '你喜欢吃什么？', source='用户手动添加', status='candidate')
    facts, inferences, questions, candidates, automatic = core._memory_groups(sid)
    assert q['text'] not in questions
    assert i['text'] not in inferences
    assert user['text'] in questions
    persisted = {record['id'] for record in core.list_memories(sid)}
    assert {q['id'], i['id'], user['id']} <= persisted
