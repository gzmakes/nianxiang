"""Startup migrations must run before opening an existing user session."""
from fastapi.testclient import TestClient

from server import core
from server.main import app


def test_uvicorn_lifespan_migrates_old_database_and_keeps_data(tmp_path, monkeypatch, legacy_schema_without_changes):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'legacy.db'))
    core.init_db()
    sid = core.create_session('empty')['session']['id']
    bookmark = core.create_bookmark(sid, '原来的书签', '', '')
    original = core.add_memory(sid, 'fact', '原来的记忆', status='confirmed')
    conn = core.get_db()
    legacy_schema_without_changes(conn)
    for table, column in [('bookmarks', 'recallable'), ('sessions', 'source_attachment_id'),
                          ('sessions', 'source_bookmark_start_rowid'), ('sessions', 'source_context_stale'),
                          ('memories', 'source_attachment_id')]:
        conn.execute(f'ALTER TABLE {table} DROP COLUMN {column}')
    conn.commit()
    conn.close()

    # No new session is created first; the real server must migrate on startup.
    with TestClient(app) as client:
        response = client.get(f'/api/session/{sid}')
        assert response.status_code == 200
        assert response.json()['bookmark']['id'] == bookmark['id']
        assert response.json()['bookmark']['recallable'] == 1
        assert any(m['id'] == original['id'] for m in response.json()['memories'])
    # Startup and migration are safe to repeat.
    with TestClient(app) as client:
        assert client.get(f'/api/session/{sid}').status_code == 200
