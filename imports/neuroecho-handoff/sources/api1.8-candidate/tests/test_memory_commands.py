"""Synthetic coverage for explicit memory commands and mixed turns."""
import pytest
from fastapi.testclient import TestClient

from server import core, model
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'memory.db'))
    core.init_db()
    with TestClient(app) as c:
        yield c


def session(c):
    return c.post('/api/session', json={'mode': 'empty'}).json()['session']['id']


@pytest.mark.parametrize('text', ['我总是记住以前的不愉快', '我想记住昨天的感受'])
def test_ordinary_narrative_does_not_save_memory_on_outage(client, monkeypatch, text):
    monkeypatch.setattr(model, 'from_env', lambda: None)
    sid = session(client)
    result = client.post('/api/chat', json={'session_id': sid, 'text': text}).json()
    assert result['memories'] == []
    assert '没有连接对话模型' in result['reply']


@pytest.mark.parametrize('joiner', ['，也帮我', '，并帮我', '然后帮我', '，同时帮我'])
def test_mixed_turn_saves_only_fact_and_answers_followup(client, monkeypatch, joiner):
    captured = []
    class Fake:
        model = 'fake'
        def complete(self, system, prompt):
            captured.append(prompt)
            return '可以试试把茶泡淡一些。'
    monkeypatch.setattr(model, 'from_env', lambda: Fake())
    sid = session(client)
    text = f'记住：我喜欢红茶{joiner}想一个喝茶的建议'
    result = client.post('/api/chat', json={'session_id': sid, 'text': text}).json()
    assert [m['text'] for m in result['memories']] == ['我喜欢红茶']
    assert result['memories'][0]['status'] == 'candidate'
    assert '待确认' in result['reply'] and '泡淡' in result['reply']
    assert '想一个喝茶的建议' in captured[-1]
    assert result['messages'][-2]['text'] == text


def test_repeated_command_keeps_one_card_but_does_not_claim_turn_idempotency(client, monkeypatch):
    monkeypatch.setattr(model, 'from_env', lambda: None)
    sid = session(client)
    text = '记住：我喜欢红茶，也帮我想个建议'
    first = client.post('/api/chat', json={'session_id': sid, 'text': text}).json()
    second = client.post('/api/chat', json={'session_id': sid, 'text': text}).json()
    assert len(first['memories']) == len(second['memories']) == 1
    assert first['memories'][0]['id'] == second['memories'][0]['id']
    assert '已在待确认' in second['reply']
    assert len([m for m in second['messages'] if m['role'] == 'user']) == 2


def test_existing_confirmed_and_deleted_memory(client, monkeypatch):
    monkeypatch.setattr(model, 'from_env', lambda: None)
    sid = session(client)
    body = {'session_id': sid, 'text': '记住：我喜欢红茶'}
    one = client.post('/api/chat', json=body).json()
    mid = one['memories'][0]['id']
    core.update_memory(mid, status='confirmed')
    two = client.post('/api/chat', json=body).json()
    assert len(two['memories']) == 1 and '确认过' in two['reply']
    core.delete_memory(mid)
    three = client.post('/api/chat', json=body).json()
    assert len(three['memories']) == 1 and three['memories'][0]['id'] != mid


def test_urgent_signal_precedes_mixed_memory_even_with_model_failure(client, monkeypatch):
    monkeypatch.setattr(model, 'from_env', lambda: None)
    sid = session(client)
    result = client.post('/api/chat', json={'session_id': sid,
        'text': '记住：我喜欢红茶，也帮我，我现在想自杀'}).json()
    assert result['action'] == 'safety' and result['memories'] == []


def test_empty_memory_command_does_not_save_placeholder(client, monkeypatch):
    monkeypatch.setattr(model, 'from_env', lambda: None)
    sid = session(client)
    result = client.post('/api/chat', json={'session_id': sid, 'text': '记住：'}).json()
    assert result['memories'] == [] and '记住什么' in result['reply']
