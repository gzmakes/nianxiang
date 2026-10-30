"""Completion IDs must identify this exact assistant, not a nearby reply."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from server import core


@pytest.fixture()
def sid(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'ids.db'))
    core.init_db()
    return core.create_session('empty')['session']['id']


def test_each_concurrent_result_references_its_own_assistant(sid, monkeypatch):
    first_in_model, second_finished = threading.Event(), threading.Event()
    class Fake:
        model = 'isolated-test'
        def complete(self, system, prompt):
            if '【用户现在说】\n第一句话\n' in prompt:
                first_in_model.set()
                assert second_finished.wait(5)
                return '第一句的回复'
            return '第二句的回复'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(core.generate_reply, sid, '第一句话')
        assert first_in_model.wait(5)
        second = core.generate_reply(sid, '第二句话')
        second_finished.set()
        first = first.result(timeout=5)
    messages = {m['id']: m for m in core.get_messages(sid)}
    assert messages[first['assistant_message_id']]['text'] == first['reply']
    assert messages[first['assistant_message_id']]['text'] != '第二句的回复'
    assert messages[second['assistant_message_id']]['text'] == '第二句的回复'
    assert first['assistant_message_id'] != second['assistant_message_id']


def test_safety_has_exact_assistant_id(sid):
    result = core.generate_reply(sid, '我想伤害自己')
    assert result['assistant_message_id'] == result['messages'][-1]['id']
