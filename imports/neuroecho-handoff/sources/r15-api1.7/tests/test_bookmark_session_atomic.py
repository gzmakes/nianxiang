"""Synthetic bookmark creation cannot revive a deleted session's data."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
import pytest
from server import core


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'bookmark.db'))
    core.init_db()


def test_missing_or_deleted_session_cannot_create_a_manual_bookmark():
    sid = core.create_session('empty')['session']['id']
    core.delete_session(sid)
    for missing in ('never-existed', sid):
        with pytest.raises(LookupError, match='session not found'):
            core.create_bookmark(missing, '不得形成孤儿数据', '', '')
        conn = core.get_db()
        try:
            assert conn.execute('SELECT COUNT(*) FROM bookmarks WHERE session_id=?', (missing,)).fetchone()[0] == 0
            assert conn.execute('SELECT COUNT(*) FROM audit WHERE session_id=?', (missing,)).fetchone()[0] == 0
        finally:
            conn.close()


def test_bookmark_waits_for_session_delete_transaction_then_rejects(monkeypatch):
    sid = core.create_session('empty')['session']['id']
    deleting, release_delete, creation_waiting = threading.Event(), threading.Event(), threading.Event()
    class CoordinatedConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            normalized = sql.strip().upper()
            if normalized.startswith('DELETE FROM SESSIONS '):
                deleting.set()
                assert release_delete.wait(4)
            if normalized == 'BEGIN IMMEDIATE' and deleting.is_set():
                creation_waiting.set()
            return super().execute(sql, parameters)
    def connect():
        conn = sqlite3.connect(core.DB_PATH, factory=CoordinatedConnection)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        return conn
    monkeypatch.setattr(core, 'get_db', connect)
    with ThreadPoolExecutor(max_workers=2) as pool:
        deletion = pool.submit(core.delete_session, sid)
        assert deleting.wait(3)
        creation = pool.submit(core.create_bookmark, sid, '删除中的会话', '', '')
        assert creation_waiting.wait(3)
        assert not creation.done()
        release_delete.set()
        assert deletion.result(timeout=4)['ok']
        with pytest.raises(LookupError, match='session not found'):
            creation.result(timeout=4)
    assert core.latest_bookmark(sid) is None
    assert core.get_session(sid) is None


def test_existing_manual_bookmark_creation_still_succeeds():
    sid = core.create_session('empty')['session']['id']
    bookmark = core.create_bookmark(sid, '本人主动留下的断点', '', '下次继续')
    assert bookmark['source_attachment_id'] == ''
    assert core.commit_bookmark(bookmark['id'])['status'] == 'committed'
    assert core.latest_bookmark(sid)['id'] == bookmark['id']
