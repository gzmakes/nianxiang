"""R9 boundary compatibility using synthetic SQLite data and a fixed clock."""
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from server import companion_boundary as boundary, core, followups, proactive_policy


NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)


def legacy_db(monkeypatch):
    monkeypatch.setattr(followups, '_current', lambda clock: clock() if clock else NOW)
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE sessions (id TEXT PRIMARY KEY)')
    conn.execute("INSERT INTO sessions VALUES ('synthetic')")
    conn.execute('''CREATE TABLE companion_boundaries (
        session_id TEXT PRIMARY KEY, ask_until TEXT, ask_time_zone TEXT,
        notify_until TEXT, notify_time_zone TEXT, ask_suppressed_through TEXT,
        notify_suppressed_through TEXT, revision INTEGER, updated_at TEXT)''')
    return conn


def add_legacy(conn, *, ask=None, notify=None, ask_cutoff=None, notify_cutoff=None):
    conn.execute('INSERT INTO companion_boundaries VALUES(?,?,?,?,?,?,?,?,?)',
                 ('synthetic', ask, 'Asia/Shanghai', notify, 'UTC', ask_cutoff,
                  notify_cutoff, 3, NOW.isoformat()))


def test_migrate_independent_pauses_conservatively_and_preserve_old_data(monkeypatch):
    conn = legacy_db(monkeypatch)
    ask_end = NOW + timedelta(hours=1)
    notify_end = NOW + timedelta(hours=3)
    add_legacy(conn, ask=ask_end.isoformat(), notify=notify_end.isoformat(),
               ask_cutoff=(NOW - timedelta(hours=2)).isoformat())
    old = tuple(conn.execute('SELECT * FROM companion_boundaries').fetchone())
    boundary.init_schema(conn)
    current = boundary.snapshot(conn, 'synthetic', NOW)
    assert current['mode'] == 'until'
    assert followups._utc(current['until_at']) == notify_end
    assert boundary.blocked(conn, 'synthetic', NOW, NOW) == 'boundary_until'
    assert tuple(conn.execute('SELECT * FROM companion_boundaries').fetchone()) == old
    assert boundary.blocked(conn, 'synthetic', notify_end, notify_end) == 'suppressed_occurrence'
    assert boundary.blocked(conn, 'synthetic', notify_end + timedelta(microseconds=1), notify_end) is None


def test_expired_legacy_pause_and_explicit_watermark_are_inclusive(monkeypatch):
    conn = legacy_db(monkeypatch)
    cutoff = NOW - timedelta(hours=2)
    add_legacy(conn, ask=(NOW - timedelta(hours=3)).isoformat(), notify_cutoff=cutoff.isoformat())
    boundary.init_schema(conn)
    assert boundary.snapshot(conn, 'synthetic', NOW)['mode'] == 'active'
    assert boundary.blocked(conn, 'synthetic', cutoff, NOW) == 'suppressed_occurrence'
    assert boundary.blocked(conn, 'synthetic', cutoff + timedelta(microseconds=1), NOW) is None


def test_existing_new_boundary_is_not_overwritten_or_resurrected(monkeypatch):
    conn = legacy_db(monkeypatch)
    add_legacy(conn, ask=(NOW + timedelta(hours=2)).isoformat())
    conn.execute('''CREATE TABLE companion_boundary (
        session_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, mode TEXT NOT NULL,
        until_at TEXT, time_zone TEXT NOT NULL, suppression_revision INTEGER NOT NULL,
        contact_after TEXT, updated_at TEXT NOT NULL)''')
    conn.execute('INSERT INTO companion_boundary VALUES(?,?,?,?,?,?,?,?)',
                 ('synthetic', 9, 'active', None, 'UTC', 7, None, NOW.isoformat()))
    before = tuple(conn.execute('SELECT * FROM companion_boundary').fetchone())
    boundary.init_schema(conn)
    boundary.init_schema(conn)
    assert tuple(conn.execute('SELECT * FROM companion_boundary').fetchone()) == before
    conn.execute("DELETE FROM companion_boundary WHERE session_id='synthetic'")
    boundary.init_schema(conn)
    assert conn.execute('SELECT * FROM companion_boundary').fetchall() == []


def test_invalid_legacy_time_fails_closed(monkeypatch):
    conn = legacy_db(monkeypatch)
    add_legacy(conn, ask='not-a-time')
    boundary.init_schema(conn)
    assert boundary.snapshot(conn, 'synthetic', NOW)['mode'] == 'paused'
    assert boundary.blocked(conn, 'synthetic', NOW, NOW) == 'boundary_paused'


def test_incomplete_legacy_table_fails_closed(monkeypatch):
    conn = legacy_db(monkeypatch)
    conn.execute('DROP TABLE companion_boundaries')
    conn.execute('CREATE TABLE companion_boundaries (session_id TEXT PRIMARY KEY)')
    conn.execute("INSERT INTO companion_boundaries VALUES ('synthetic')")
    boundary.init_schema(conn)
    assert boundary.snapshot(conn, 'synthetic', NOW)['mode'] == 'paused'


def test_actual_startup_imports_old_scope_without_touching_other_sessions(monkeypatch):
    monkeypatch.setattr(followups, '_current', lambda clock: clock() if clock else NOW)
    core.init_db()
    sid = core.create_session('empty')['session']['id']
    with core.get_db() as conn:
        conn.execute('''CREATE TABLE companion_boundaries (
            session_id TEXT PRIMARY KEY, ask_until TEXT, ask_time_zone TEXT,
            notify_until TEXT, notify_time_zone TEXT, ask_suppressed_through TEXT,
            notify_suppressed_through TEXT, revision INTEGER, updated_at TEXT)''')
        conn.execute('INSERT INTO companion_boundaries VALUES(?,?,?,?,?,?,?,?,?)',
                     (sid, (NOW + timedelta(hours=1)).isoformat(), 'Asia/Shanghai',
                      None, None, None, None, 1, NOW.isoformat()))
    core.init_db()
    assert boundary.get(core.DB_PATH, sid)['mode'] == 'until'
    core.init_db()
    assert boundary.get(core.DB_PATH, sid)['revision'] == 1


def test_deletion_is_same_transaction_and_rollback_preserves_legacy(monkeypatch):
    conn = legacy_db(monkeypatch)
    add_legacy(conn, ask=(NOW + timedelta(hours=1)).isoformat())
    proactive_policy.init_schema(conn)
    conn.commit()
    conn.execute('BEGIN')
    proactive_policy.delete_for_session(conn, 'synthetic')
    assert conn.execute('SELECT COUNT(*) FROM companion_boundaries').fetchone()[0] == 0
    assert conn.execute('SELECT COUNT(*) FROM companion_boundary_legacy_migrated').fetchone()[0] == 0
    conn.rollback()
    assert conn.execute('SELECT COUNT(*) FROM companion_boundaries').fetchone()[0] == 1
    assert conn.execute('SELECT COUNT(*) FROM companion_boundary_legacy_migrated').fetchone()[0] == 1
    assert boundary.snapshot(conn, 'synthetic', NOW)['mode'] == 'until'


def test_actual_session_delete_only_cleans_its_own_legacy_and_cannot_revive(monkeypatch):
    monkeypatch.setattr(followups, '_current', lambda clock: clock() if clock else NOW)
    core.init_db()
    sid = core.create_session('empty')['session']['id']
    other = core.create_session('empty')['session']['id']
    with core.get_db() as conn:
        conn.execute('''CREATE TABLE companion_boundaries (
            session_id TEXT PRIMARY KEY, ask_until TEXT, ask_time_zone TEXT,
            notify_until TEXT, notify_time_zone TEXT, ask_suppressed_through TEXT,
            notify_suppressed_through TEXT, revision INTEGER, updated_at TEXT)''')
        for value in (sid, other):
            conn.execute('INSERT INTO companion_boundaries VALUES(?,?,?,?,?,?,?,?,?)',
                         (value, (NOW + timedelta(hours=1)).isoformat(), 'UTC', None,
                          None, None, None, 1, NOW.isoformat()))
    core.init_db()
    assert core.delete_session(sid)['ok']
    with core.get_db() as conn:
        assert conn.execute('SELECT session_id FROM companion_boundaries').fetchone()[0] == other
        assert conn.execute('SELECT session_id FROM companion_boundary_legacy_migrated').fetchone()[0] == other
        # A deliberately reused synthetic ID cannot bring the old pause back.
        conn.execute('INSERT INTO sessions(id) VALUES (?)', (sid,))
    core.init_db()
    assert boundary.get(core.DB_PATH, sid)['revision'] == 0
    assert boundary.get(core.DB_PATH, other)['mode'] == 'until'


@pytest.mark.parametrize('text,expected', [
    ('今天先别主动问/提醒', 'today'), ('今天不要主动提醒我', 'today'),
    ('今天别主动打扰我', 'today'), ('今天先别主动问我。', 'today'),
    ('恢复主动关怀', 'active'), ('可以恢复主动关怀了。', 'active'),
    ('“今天先别主动问/提醒”', None), ('今天别主动打扰我吗？', None),
    ('不要恢复主动关怀', None), ('今天不要主动提醒我开会', None),
    ('今天先别主动问我，明天也别主动问我', None),
])
def test_legacy_commands_require_a_standalone_statement(text, expected):
    assert boundary.direct_control(text) == expected
