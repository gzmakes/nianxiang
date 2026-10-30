"""A busy rejection is durable and never starts a duplicate synthetic turn."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import threading

import pytest
from fastapi.testclient import TestClient

from server import companion_boundary, core, followups, main


@pytest.fixture
def setup(monkeypatch):
    core.init_db()
    sid = core.create_session('empty')['session']['id']
    entered, release = threading.Event(), threading.Event()
    calls = []

    class Model:
        model = 'synthetic'
        def complete(self, system, prompt):
            calls.append(prompt)
            if len(calls) == 1:
                entered.set()
                assert release.wait(5)
            return '合成回复'

    monkeypatch.setattr(core.model, 'from_env', lambda: Model())
    return TestClient(main.app), sid, entered, release, calls


def post(client, sid, request_id, text):
    return client.post('/api/chat', json={'session_id': sid, 'request_id': request_id, 'text': text})


def test_busy_is_durably_rejected_even_if_response_is_lost_or_late(setup):
    client, sid, entered, release, calls = setup
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(post, client, sid, 'first-turn-1', '第一句')
        assert entered.wait(3)
        try:
            rejected = post(client, sid, 'second-turn-1', '第二句')
            assert rejected.status_code == 409
            body = rejected.json()
            assert (body['session_id'], body['request_id'], body['status'], body['error_code']) == (
                sid, 'second-turn-1', 'unknown', 'conversation_busy_not_accepted')
            assert post(client, sid, 'second-turn-1', '不同内容').json()['error_code'] == 'request_id_conflict'
        finally:
            release.set()
        assert first.result(timeout=5).status_code == 200
    late = post(client, sid, 'second-turn-1', '第二句')
    assert late.status_code == 409 and late.json()['error_code'] == 'conversation_busy_not_accepted'
    recovered = client.get('/api/chat/turn/second-turn-1', params={'session_id': sid}).json()
    assert (recovered['session_id'], recovered['request_id'], recovered['error_code']) == (sid, 'second-turn-1', 'conversation_busy_not_accepted')
    assert len(calls) == 1
    assert not any(m['text'] == '第二句' for m in core.get_messages(sid))
    assert post(client, sid, 'second-turn-2', '第二句').status_code == 200
    assert len(calls) == 2


def test_direct_pause_during_generation_is_immediate_and_no_second_model_call(setup):
    client, sid, entered, release, calls = setup
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(post, client, sid, 'first-turn-2', '第一句')
        assert entered.wait(3)
        try:
            text = '今天先别问，我想自己待一会儿。'
            pause = post(client, sid, 'pause-turn-1', text)
            assert pause.status_code == 200
            assert pause.json()['action'] == 'boundary.changed'
            assert companion_boundary.get(core.DB_PATH, sid)['mode'] == 'until'
            assert any(m['role'] == 'user' and m['text'] == text for m in core.get_messages(sid))
            assert len(calls) == 1
        finally:
            release.set()
        assert first.result(timeout=5).status_code == 200
    assert len(calls) == 1
    assert not any(m['role'] == 'assistant' and m['text'] == '合成回复' for m in core.get_messages(sid))
    assert post(client, sid, 'pause-turn-1', text).status_code == 200
    assert len([m for m in core.get_messages(sid) if m['text'] == text]) == 1


def test_legacy_request_without_id_cannot_bypass_busy_guard(setup):
    client, sid, entered, release, calls = setup
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(post, client, sid, 'first-turn-3', '第一句')
        assert entered.wait(3)
        try:
            result = client.post('/api/chat', json={'session_id': sid, 'text': '旧端消息'})
            assert result.status_code == 409
            assert result.json()['error_code'] == 'conversation_busy_not_accepted'
        finally:
            release.set()
        assert first.result(timeout=5).status_code == 200
    assert len(calls) == 1


def test_explicit_safety_response_is_not_blocked_by_busy_model(setup):
    client, sid, entered, release, calls = setup
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(post, client, sid, 'first-turn-4', '第一句')
        assert entered.wait(3)
        try:
            response = post(client, sid, 'safety-turn-1', '我想伤害自己')
            assert response.status_code == 200 and response.json()['action'] == 'safety'
            assert len(calls) == 1
        finally:
            release.set()
        assert first.result(timeout=5).status_code == 200
    assert not any(m['role'] == 'assistant' and m['text'] == '合成回复' for m in core.get_messages(sid))


def test_safety_and_explicit_pause_use_user_time_zone_during_generation(setup, monkeypatch):
    client, sid, entered, release, calls = setup
    fixed = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(followups, '_current', lambda clock: clock() if clock else fixed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(post, client, sid, 'first-turn-5', '第一句')
        assert entered.wait(3)
        try:
            text = '今天先别问，我想伤害自己'
            response = client.post('/api/chat', json={'session_id': sid, 'request_id': 'safety-zone-1',
                                    'text': text, 'time_zone': 'Asia/Shanghai'})
            assert response.status_code == 200 and response.json()['action'] == 'safety'
            saved = companion_boundary.get(core.DB_PATH, sid)
            assert saved['mode'] == 'until'
            assert saved['time_zone'] == 'Asia/Shanghai'
            assert saved['until'].startswith('2026-10-30T16:00:00')
            assert any(m['role'] == 'user' and m['text'] == text for m in core.get_messages(sid))
            assert len(calls) == 1
        finally:
            release.set()
        assert first.result(timeout=5).status_code == 200
    assert not any(m['role'] == 'assistant' and m['text'] == '合成回复' for m in core.get_messages(sid))
