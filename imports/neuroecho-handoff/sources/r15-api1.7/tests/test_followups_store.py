from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from server import followups


START = datetime(2026, 10, 30, 1, tzinfo=timezone.utc)
CLOCK = lambda: START
DUE = '2026-10-30T10:00:00+08:00'


@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'synthetic.db'
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE sessions(id TEXT PRIMARY KEY)')
    conn.execute('CREATE TABLE audit(id TEXT PRIMARY KEY,session_id TEXT,action TEXT,detail TEXT,reason TEXT,created_at TEXT)')
    conn.executemany('INSERT INTO sessions VALUES(?)', [('one',), ('two',)])
    followups.init_schema(conn)
    conn.commit()
    conn.close()
    return path


def test_due_is_derived_after_restart_and_never_claims_delivery(database):
    item = followups.create(database, 'one', '喝一杯水', DUE, 'r1', clock=CLOCK)
    assert not item['due']
    later = lambda: START + timedelta(hours=2)
    for _ in range(2):
        overdue = followups.list_for_session(database, 'one', clock=later)[0]
        assert overdue['due'] and overdue['status'] == 'pending'
        assert 'delivered' not in overdue
    assert followups.list_for_session(database, 'two', clock=later) == []


def test_request_is_idempotent_even_after_due_and_conflicts_on_change(database):
    first = followups.create(database, 'one', '喝水', DUE, 'r1', clock=CLOCK)
    later = lambda: START + timedelta(hours=2)
    again = followups.create(database, 'one', '喝水', '2026-10-30T02:00:00Z', 'r1', clock=later)
    assert again['id'] == first['id'] and again['due']
    with pytest.raises(followups.FollowupConflict):
        followups.create(database, 'one', '走走', DUE, 'r1', clock=CLOCK)
    assert len(followups.list_for_session(database, 'one', clock=CLOCK)) == 1


def test_reject_invalid_and_past_times_and_missing_session(database):
    for due in ('2026-10-30T10:00', 'garbage', '2026-10-30T08:00:00+08:00'):
        with pytest.raises(ValueError):
            followups.create(database, 'one', '喝水', due, due, clock=CLOCK)
    with pytest.raises(LookupError):
        followups.create(database, 'missing', '喝水', DUE, 'r1', clock=CLOCK)
    with pytest.raises(ValueError):
        followups.create(database, 'one', ' ', DUE, 'r1', clock=CLOCK)
    assert followups.list_for_session(database, 'one', clock=CLOCK) == []


def test_conflicting_concurrent_transitions_have_only_one_winner(database):
    item = followups.create(database, 'one', '走走', DUE, 'r1', clock=CLOCK)
    def change(target):
        try:
            return followups.transition(database, 'one', item['id'], target, clock=CLOCK)['status']
        except followups.FollowupConflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(change, ['done', 'cancelled']))
    assert outcomes.count('conflict') == 1
    winner = next(x for x in outcomes if x != 'conflict')
    assert followups.transition(database, 'one', item['id'], winner, clock=CLOCK)['status'] == winner
    with pytest.raises(LookupError):
        followups.transition(database, 'two', item['id'], winner, clock=CLOCK)
    conn = sqlite3.connect(database)
    try:
        audits = conn.execute('SELECT action,detail FROM audit').fetchall()
        assert len(audits) == 2
        assert all('走走' not in detail for _, detail in audits)
    finally:
        conn.close()


def test_concurrent_duplicate_creation_and_audit_failure_are_atomic(database):
    def make(_):
        return followups.create(database, 'one', '喝水', DUE, 'same', clock=CLOCK)['id']
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(make, range(2)))
    assert ids[0] == ids[1]
    conn = sqlite3.connect(database)
    conn.execute('DROP TABLE audit')
    conn.commit()
    conn.close()
    with pytest.raises(sqlite3.OperationalError):
        followups.create(database, 'one', '另一件事', DUE, 'another', clock=CLOCK)
    assert len(followups.list_for_session(database, 'one', clock=CLOCK)) == 1


def test_export_and_deletion_join_callers_transaction(database):
    followups.create(database, 'one', '内容一', DUE, 'a', clock=CLOCK)
    followups.create(database, 'two', '内容二', DUE, 'b', clock=CLOCK)
    assert len(followups.list_for_export(database)) == 2
    assert [x['content'] for x in followups.list_for_export(database, 'one')] == ['内容一']
    conn = sqlite3.connect(database)
    try:
        conn.execute('BEGIN')
        assert followups.delete_for_session(conn, 'one') == 1
        conn.rollback()
        assert len(followups.list_for_export(database, 'one')) == 1
        conn.execute('BEGIN')
        followups.delete_for_session(conn, 'one')
        conn.commit()
    finally:
        conn.close()
    assert len(followups.list_for_export(database)) == 1


def test_read_of_missing_database_does_not_create_file(tmp_path):
    missing = tmp_path / 'not-created.db'
    with pytest.raises(sqlite3.OperationalError):
        followups.list_for_session(missing, 'one', clock=CLOCK)
    assert not missing.exists()
