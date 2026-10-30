"""Suppress only obsolete assistant output; retain the person's actual words."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from server import core


@pytest.fixture()
def sid(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'turns.db'))
    core.init_db()
    return core.create_session('empty')['session']['id']


def test_superseded_remote_reply_is_not_stored_and_next_turn_sees_prior_user_input(sid, monkeypatch):
    entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
    reply_lock = threading.RLock()
    sent = []
    class Fake:
        model = 'isolated-test'
        def complete(self, system, prompt):
            sent.append(prompt)
            if len(sent) == 1:
                entered.set()
                assert release.wait(5)
                return '过时的回应'
            return '我把你刚补充的也听到了。'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    initial_assistant_count = sum(m['role'] == 'assistant' for m in core.get_messages(sid))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(core.generate_reply, sid, '今天开会很烦',
                             should_cancel=cancelled.is_set, reply_lock=reply_lock)
        assert entered.wait(5)
        # The user's words have reached persistent storage before HTTP returns.
        assert any(m['text'] == '今天开会很烦' for m in core.get_messages(sid))
        with reply_lock:
            cancelled.set()
        release.set()
        old = future.result(timeout=5)
    assert old['cancelled'] is True and old['action'] == 'cancelled' and old['reply'] == ''
    assert sum(m['role'] == 'assistant' for m in core.get_messages(sid)) == initial_assistant_count
    assert not any(m['text'] == '过时的回应' for m in old['messages'])
    assert sent[0].count('今天开会很烦') == 1  # current turn isn't duplicated in history
    current = core.generate_reply(sid, '我还没说完，后来又发生了一件事')
    assert current['action'] == 'model.reply'
    assert '今天开会很烦' in sent[-1]
    assert '过时的回应' not in sent[-1]
    assert sent[-1].count('我还没说完，后来又发生了一件事') == 1
    assert sum(m['role'] == 'user' and m['text'] == '今天开会很烦' for m in current['messages']) == 1


def test_cancelled_explicit_memory_request_retains_user_requested_candidate(sid):
    result = core.generate_reply(sid, '记住：我喜欢散步', should_cancel=lambda: True,
                                 reply_lock=threading.RLock())
    assert result['cancelled'] is True
    assert any(m['text'] == '我喜欢散步' and m['status'] == 'candidate' for m in result['memories'])
    assert any(m['text'] == '记住：我喜欢散步' and m['role'] == 'user' for m in result['messages'])


def test_safety_response_cannot_be_cancelled(sid, monkeypatch):
    monkeypatch.setattr(core.model, 'from_env', lambda: pytest.fail('safety must not call remote model'))
    result = core.generate_reply(sid, '我现在要伤害自己', should_cancel=lambda: True)
    assert result['action'] == 'safety' and result['reply']
    assert not result.get('cancelled')
    assert result['messages'][-1]['role'] == 'assistant'
