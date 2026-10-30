"""Optimistic memory edits use isolated SQLite transactions, not last-writer overwrite."""
from concurrent.futures import ThreadPoolExecutor
import threading

from fastapi.testclient import TestClient
import pytest

from server import core, main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "memory-versions.db"))
    core.init_db()
    return TestClient(main.app)


def create_memory(client):
    sid = client.get('/api/conversation').json()['session']['id']
    memory = client.post('/api/memory', json={'session_id': sid, 'kind': 'fact', 'text': '合成初始偏好'}).json()
    return sid, memory


def test_stale_patch_rejects_without_overwriting_text_history_or_context(client):
    sid, memory = create_memory(client)
    updated = client.patch(f"/api/memory/{memory['id']}", json={'text': '第一台设备确认的新偏好', 'expected_version': 1})
    assert updated.status_code == 200 and updated.json()['version'] == 2
    before = client.get('/api/conversation').json()
    history = core.memory_history(memory['id'])
    stamp = core._model_context_stamp(sid)
    conflict = client.patch(f"/api/memory/{memory['id']}", json={'text': '第二台设备尚未保存的草稿', 'status': 'confirmed', 'expected_version': 1})
    assert conflict.status_code == 409
    assert conflict.json()['error_code'] == 'memory_version_conflict'
    assert conflict.json()['current_version'] == 2 and conflict.json()['expected_version'] == 1
    assert isinstance(conflict.json()['detail'], str)
    assert '第二台设备尚未保存的草稿' not in conflict.text
    assert client.get('/api/conversation').json() == before
    assert core.memory_history(memory['id']) == history
    assert core._model_context_stamp(sid) == stamp


def test_two_devices_compete_for_same_version_exactly_one_edit_wins(client):
    sid, memory = create_memory(client)
    gate = threading.Barrier(2)

    def edit(text):
        gate.wait(timeout=5)
        return client.patch(f"/api/memory/{memory['id']}", json={'text': text, 'expected_version': 1})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, ['合成设备 A 的修改', '合成设备 B 的修改']))
    assert sorted(result.status_code for result in results) == [200, 409]
    winner = next(result.json() for result in results if result.status_code == 200)
    stored = core.list_memories(sid)[0]
    assert stored['text'] == winner['text'] and stored['version'] == 2
    assert [row['version'] for row in core.memory_history(memory['id'])] == [1, 2]


def test_stale_delete_keeps_new_version_and_matching_delete_removes_history(client):
    sid, memory = create_memory(client)
    core.update_memory(memory['id'], text='保留的新版本', expected_version=1)
    conflict = client.delete(f"/api/memory/{memory['id']}?expected_version=1")
    assert conflict.status_code == 409 and conflict.json()['current_version'] == 2
    assert core.list_memories(sid)[0]['text'] == '保留的新版本'
    assert len(core.memory_history(memory['id'])) == 2
    deleted = client.delete(f"/api/memory/{memory['id']}?expected_version=2")
    assert deleted.status_code == 200 and deleted.json() == {'ok': True}
    assert core.list_memories(sid) == [] and core.memory_history(memory['id']) == []


def test_delete_and_edit_of_same_version_do_not_resurrect_or_erase_newer_data(client):
    sid, memory = create_memory(client)
    gate = threading.Barrier(2)

    def mutate(operation):
        gate.wait(timeout=5)
        if operation == 'edit':
            return operation, client.patch(f"/api/memory/{memory['id']}", json={'text': '竞争后保留的新版本', 'expected_version': 1})
        return operation, client.delete(f"/api/memory/{memory['id']}?expected_version=1")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = dict(pool.map(mutate, ['edit', 'delete']))
    if results['edit'].status_code == 200:
        assert results['delete'].status_code == 409
        assert core.list_memories(sid)[0]['text'] == '竞争后保留的新版本'
    else:
        assert results['delete'].status_code == 200 and results['edit'].status_code == 404
        assert core.list_memories(sid) == [] and core.memory_history(memory['id']) == []


def test_legacy_clients_can_still_edit_and_delete_without_version(client):
    _, memory = create_memory(client)
    response = client.patch(f"/api/memory/{memory['id']}", json={'text': '旧客户端编辑'})
    assert response.status_code == 200 and response.json()['version'] == 2
    assert client.delete(f"/api/memory/{memory['id']}").status_code == 200


@pytest.mark.parametrize('version', [0, -1, True, '1', 1.5])
def test_invalid_patch_versions_are_validation_errors_not_writes(client, version):
    sid, memory = create_memory(client)
    response = client.patch(f"/api/memory/{memory['id']}", json={'text': '不应写入', 'expected_version': version})
    assert response.status_code == 422 and response.json()['error_code'] == 'validation_error'
    assert core.list_memories(sid)[0]['version'] == 1
