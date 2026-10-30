"""提醒与日历动作：明确区分真实结果、未知结果和演示。"""
import pytest
from fastapi.testclient import TestClient

from server import apple_source, core
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    core.init_db()
    return TestClient(app)


def make_action(client):
    sid = client.post("/api/session", json={"mode": "sample"}).json()["session"]["id"]
    return client.post("/api/action", json={"session_id": sid, "kind": "reminder", "title": "演示前彩排"}).json()


def test_real_reminder_write(client, monkeypatch):
    monkeypatch.setattr(apple_source, "create_reminder", lambda title: {"ok": True, "title": title})
    a = make_action(client)
    done = client.post(f"/api/action/{a['id']}/commit", json={"real": True}).json()
    assert done["real"] == 1
    assert done["receipt"].startswith("reminders:")


def test_real_write_failure_never_claims_demo_success(client, monkeypatch):
    def boom(title):
        raise RuntimeError("Not authorized")
    monkeypatch.setattr(apple_source, "create_reminder", boom)
    a = make_action(client)
    done = client.post(f"/api/action/{a['id']}/commit", json={"real": True}).json()
    assert done["real"] == 0
    assert done["status"] == "unknown"
    assert done["receipt"] == ""
    assert done["committed_at"] is None
    assert "Not authorized" in done["error"]


def test_real_calendar_write(client, monkeypatch):
    monkeypatch.setattr(apple_source, "create_event", lambda title, when: {"ok": True, "title": title, "when": when})
    sid = client.post("/api/session", json={"mode": "sample"}).json()["session"]["id"]
    a = client.post("/api/action", json={"session_id": sid, "kind": "calendar", "title": "演示",
                                          "when": "2026-10-29T10:00"}).json()
    done = client.post(f"/api/action/{a['id']}/commit", json={"real": True}).json()
    assert done["real"] == 1 and done["receipt"].startswith("calendar:")


def test_real_calendar_without_time_fails_without_external_write(client, monkeypatch):
    def unexpected(*args):
        raise AssertionError('missing time must not call Calendar')
    monkeypatch.setattr(apple_source, 'create_event', unexpected)
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    a = client.post('/api/action', json={'session_id': sid, 'kind': 'calendar', 'title': '演示'}).json()
    done = client.post(f"/api/action/{a['id']}/commit", json={'real': True}).json()
    assert done['status'] == 'failed' and done['real'] == 0
    assert not done['receipt'] and '时间' in done['error']


def test_repeated_commit_does_not_duplicate_real_write(client, monkeypatch):
    calls = []
    monkeypatch.setattr(apple_source, 'create_reminder', lambda title: calls.append(title) or {'ok': True})
    a = make_action(client)
    first = client.post(f"/api/action/{a['id']}/commit", json={'real': True}).json()
    second = client.post(f"/api/action/{a['id']}/commit", json={'real': True}).json()
    assert first['status'] == second['status'] == 'committed'
    assert first['receipt'] == second['receipt'] and len(calls) == 1


def test_unconfirmed_external_result_is_not_retried_automatically(client, monkeypatch):
    calls = []
    def unconfirmed(title):
        calls.append(title)
        return {'ok': False}
    monkeypatch.setattr(apple_source, 'create_reminder', unconfirmed)
    a = make_action(client)
    first = client.post(f"/api/action/{a['id']}/commit", json={'real': True}).json()
    second = client.post(f"/api/action/{a['id']}/commit", json={'real': True}).json()
    assert first['status'] == second['status'] == 'unknown'
    assert not first['receipt'] and len(calls) == 1
