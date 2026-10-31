"""跨会话记忆：只带用户确认过的事实。"""
import pytest
from fastapi.testclient import TestClient

from server import core
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    core.init_db()
    return TestClient(app)


def test_carryover_and_import(client):
    a = client.post("/api/session", json={"mode": "paste", "text": "测试项目正在整理交互原型。测试团队准备下一轮演示。测试资料记录当前计划。测试选择先确认范围。测试安排稍后核对记录。"}).json()["session"]["id"]
    m = core.add_memory(a, "fact", "你更喜欢先看结论", source="用户确认", status="confirmed")
    core.add_memory(a, "fact", "还没确认的猜测", source="推测", status="candidate")

    b = client.post("/api/session", json={"mode": "paste", "text": "测试项目正在整理交互原型。测试团队准备下一轮演示。测试资料记录当前计划。测试选择先确认范围。测试安排稍后核对记录。"}).json()["session"]["id"]
    d = client.get(f"/api/carryover?session_id={b}").json()["memories"]
    assert len(d) == 1 and d[0]["text"] == "你更喜欢先看结论"

    r = client.post("/api/carryover/import", json={"session_id": b, "ids": [m["id"]]}).json()
    assert r["imported"] == 1
    mems = client.get(f"/api/memory?session_id={b}").json()["memories"]
    assert any(x["text"] == "你更喜欢先看结论" and x["status"] == "confirmed" for x in mems)


def test_selection_keeps_existing_choice_and_imports_only_checked_memory(client, monkeypatch):
    captured = []
    class Model:
        model = 'test'
        def complete(self, system, user):
            captured.append((system, user))
            return '收到'
    monkeypatch.setattr(core.model, 'from_env', lambda: Model())
    one = core.create_session('empty')['session']['id']
    two = core.create_session('empty')['session']['id']
    target = core.create_session('empty')['session']['id']
    old = core.add_memory(one, 'fact', '我喜欢绿茶', status='confirmed')
    new = core.add_memory(two, 'fact', '我喜欢红茶', status='confirmed')
    current = core.add_memory(target, 'fact', '我偏爱安静', status='confirmed')
    view = client.get('/api/carryover', params={'session_id': target}).json()
    assert {m['text'] for m in view['memories']} == {'我喜欢绿茶', '我喜欢红茶'}
    assert [m['text'] for m in view['current_confirmed']] == ['我偏爱安静']
    chosen = next(m for m in view['memories'] if m['id'] == new['id'])
    response = client.post('/api/carryover/import', json={'session_id': target, 'ids': [chosen['id']],
        'expected_versions': {chosen['id']: chosen['version']},
        'expected_target': {current['id']: current['version']}})
    assert response.status_code == 200 and response.json()['imported'] == 1
    assert {m['text'] for m in core.list_memories(target)} == {'我喜欢红茶', '我偏爱安静'}
    remaining = client.get('/api/carryover', params={'session_id': target}).json()['memories']
    assert [m['text'] for m in remaining] == ['我喜欢绿茶']
    core.generate_reply(target, '我们聊聊茶')
    assert '我喜欢红茶' in captured[-1][1] and '我喜欢绿茶' not in captured[-1][1]
    assert '存在冲突' in captured[-1][0]
    assert core.list_memories(one)[0]['text'] == '我喜欢绿茶'


@pytest.mark.parametrize('changed', ['source', 'target', 'deleted'])
def test_stale_review_is_rejected_atomically(client, changed):
    one = core.create_session('empty')['session']['id']
    target = core.create_session('empty')['session']['id']
    source1 = core.add_memory(one, 'fact', '第一条', status='confirmed')
    source2 = core.add_memory(one, 'fact', '第二条', status='confirmed')
    current = core.add_memory(target, 'fact', '目标已有记忆', status='confirmed')
    view = client.get('/api/carryover', params={'session_id': target}).json()
    versions = {m['id']: m['version'] for m in view['memories']}
    snapshot = {m['id']: m['version'] for m in view['current_confirmed']}
    if changed == 'source': core.update_memory(source2['id'], text='修改后的第二条')
    elif changed == 'target': core.update_memory(current['id'], text='修改后的目标记忆')
    else: core.delete_memory(source2['id'])
    r = client.post('/api/carryover/import', json={'session_id': target,
        'ids': [source1['id'], source2['id']], 'expected_versions': versions, 'expected_target': snapshot})
    assert r.status_code == 409
    assert len(core.list_memories(target)) == 1
