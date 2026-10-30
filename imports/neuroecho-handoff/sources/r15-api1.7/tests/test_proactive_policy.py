from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from server import followups, proactive_policy as policy

BASE = datetime(2026, 10, 30, 0, tzinfo=timezone.utc)  # 08:00 Shanghai


@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'synthetic-policy.db'
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE sessions(id TEXT PRIMARY KEY)')
    conn.execute('CREATE TABLE audit(id TEXT PRIMARY KEY,session_id TEXT,action TEXT,detail TEXT,reason TEXT,created_at TEXT)')
    conn.executemany('INSERT INTO sessions VALUES(?)', [('one',), ('two',)])
    followups.init_schema(conn)
    policy.init_schema(conn)
    conn.commit()
    conn.close()
    return path


def settings(path, **overrides):
    values = dict(enabled=True, time_zone='Asia/Shanghai', quiet_start='22:00', quiet_end='08:00', cooldown_minutes=60, daily_limit=3, pause_until=None)
    values.update(overrides)
    return policy.set_settings(path, 'one', **values, clock=lambda: BASE)


def make(path, name='a', *, due=BASE, repeat='once', zone='Asia/Shanghai', quiet_start=None, quiet_end=None):
    return followups.create(path, 'one', name, due.isoformat(), name, repeat_rule=repeat, time_zone=zone, quiet_start=quiet_start, quiet_end=quiet_end, allow_contact=True, contact_window_minutes=180, clock=lambda: due - timedelta(hours=1))


def claim(path, item, now=BASE):
    return policy.claim(path, 'one', item['id'], item['due_at'], clock=lambda: now)


def test_off_by_default_and_settings_are_validated(database):
    item = make(database)
    assert policy.get_settings(database, 'one') == {**policy.DEFAULTS, 'configured': False, 'revision': 0}
    assert claim(database, item)['reason'] == 'disabled'
    for invalid in ({'enabled': 1}, {'time_zone': 'not/a-zone'}, {'quiet_start':'08:00','quiet_end':'08:00'}, {'daily_limit':4}, {'cooldown_minutes':59}):
        with pytest.raises(ValueError):
            settings(database, **invalid)
    assert not policy.get_settings(database, 'one')['enabled']
    assert settings(database, time_zone='UTC')['configured'] is True
    assert policy.get_settings(database, 'one')['time_zone'] == 'UTC'
    assert policy.get_settings(database, 'one')['configured'] is True
    with pytest.raises(LookupError):
        policy.get_settings(database, 'missing')


def test_utc_quiet_boundaries_pause_and_item_restrictions(database):
    item = make(database,due=BASE+timedelta(hours=14))
    settings(database)
    assert claim(database, item, BASE + timedelta(hours=14))['reason'] == 'quiet'  # 22:00
    assert claim(database, item, BASE + timedelta(hours=23, minutes=59))['reason'] == 'expired'  # 07:59
    morning=make(database,'morning',due=BASE+timedelta(days=1))
    assert claim(database,morning,BASE+timedelta(days=1))['claimed']  # 08:00
    p = make(database, 'b')
    settings(database, pause_until=(BASE + timedelta(hours=3)).isoformat())
    assert claim(database, p, BASE + timedelta(hours=1))['reason'] == 'paused'
    settings(database)
    followups.transition(database, 'one', p['id'], 'paused', clock=lambda: BASE)
    assert claim(database, p, BASE + timedelta(hours=2))['reason'] == 'item_paused'


def test_single_occurrence_concurrent_claim_and_unknown_never_retries(database):
    item = make(database)
    settings(database)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: claim(database, item), range(8)))
    assert sum(r['claimed'] for r in results) == 1
    assert all(r['reason'] == 'already_claimed' for r in results if not r['claimed'])
    assert claim(database, item, BASE + timedelta(days=2))['reason'] == 'expired'
    assert followups.list_for_session(database, 'one', clock=lambda: BASE)[0]['status'] == 'pending'
    conn = sqlite3.connect(database)
    assert conn.execute('SELECT state FROM followup_notification_attempts').fetchone()[0] == 'claimed'
    conn.close()


def test_recheck_detects_disable_and_item_cancel_before_platform_call(database):
    item = make(database)
    settings(database)
    c = claim(database, item)
    settings(database, enabled=False)
    assert policy.recheck(database, 'one', c['claim_id'], clock=lambda: BASE)['reason'] == 'settings_changed'
    settings(database)
    followups.transition(database, 'one', item['id'], 'cancelled', clock=lambda: BASE)
    assert policy.recheck(database, 'one', c['claim_id'], clock=lambda: BASE)['reason'] == 'settings_changed'
    with pytest.raises(LookupError):
        policy.finish(database, 'two', c['claim_id'], 'submitted', clock=lambda: BASE)


def test_failure_and_submission_are_terminal_without_automatic_retry(database):
    item = make(database)
    settings(database)
    first = claim(database, item)
    assert policy.finish(database, 'one', first['claim_id'], 'failed', clock=lambda: BASE)['state'] == 'failed'
    assert claim(database, item, BASE + timedelta(days=1))['reason'] == 'expired'
    other = make(database, 'submitted')
    second = claim(database, other, BASE + timedelta(hours=1))
    assert second['claimed']
    assert policy.recheck(database, 'one', second['claim_id'], clock=lambda: BASE + timedelta(hours=1))['allowed']
    assert policy.finish(database, 'one', second['claim_id'], 'submitted', clock=lambda: BASE + timedelta(hours=1))['state'] == 'submitted'
    assert claim(database, other, BASE + timedelta(days=1))['reason'] == 'expired'
    with pytest.raises(followups.FollowupConflict):
        policy.finish(database, 'one', second['claim_id'], 'failed', clock=lambda: BASE)
    assert followups.list_for_session(database, 'one', clock=lambda: BASE)[0]['status'] == 'pending'


def test_budget_and_cooldown_count_unconfirmed_attempts(database):
    items = [make(database, str(i)) for i in range(5)]
    settings(database)
    assert claim(database, items[0])['claimed']
    assert claim(database, items[1], BASE + timedelta(minutes=59))['reason'] == 'cooldown'
    assert claim(database, items[1], BASE + timedelta(hours=1))['claimed']
    assert claim(database, items[2], BASE + timedelta(hours=2))['claimed']
    assert claim(database, items[3], BASE + timedelta(hours=2,minutes=1))['reason'] == 'daily_limit'
    fresh=make(database,'next-day',due=BASE+timedelta(days=1))
    assert claim(database,fresh,BASE+timedelta(days=1))['claimed']


def test_daily_occurrence_identity_and_cleanup_transaction(database):
    item = make(database, repeat='daily')
    settings(database)
    first = claim(database, item)
    followups.transition(database, 'one', item['id'], 'done', occurrence_at=item['due_at'], clock=lambda: BASE)
    assert policy.recheck(database, 'one', first['claim_id'], clock=lambda: BASE)['reason'] == 'occurrence_changed'
    current = followups.list_for_session(database, 'one', clock=lambda: BASE)[0]
    assert claim(database, current, BASE + timedelta(days=1))['claimed']
    conn = sqlite3.connect(database)
    conn.execute('BEGIN')
    assert policy.delete_for_session(conn, 'one') == {'notification_attempts':2,'notification_settings':1,'companion_boundaries':0}
    conn.rollback()
    assert conn.execute('SELECT count(*) FROM followup_notification_attempts').fetchone()[0] == 2
    conn.close()


def test_concurrent_recheck_grants_exactly_one_invoke_permission(database):
    item = make(database)
    settings(database)
    reserved = claim(database, item)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: policy.recheck(database, 'one', reserved['claim_id'], clock=lambda: BASE), range(8)))
    assert sum(r['allowed'] for r in results) == 1
    assert all(r['reason'] == 'not_claimed' for r in results if not r['allowed'])
    assert claim(database, item, BASE + timedelta(days=1))['reason'] == 'expired'


def test_claim_is_atomic_across_independent_processes(database):
    import json
    import subprocess
    import sys

    item = make(database)
    settings(database)
    script = '''import json,sys
from datetime import datetime
from server.proactive_policy import claim
print(json.dumps(claim(sys.argv[1], 'one', sys.argv[2], sys.argv[3], clock=lambda: datetime.fromisoformat(sys.argv[4]))))'''
    def invoke(_):
        result = subprocess.run([sys.executable, '-c', script, str(database), item['id'], item['due_at'], BASE.isoformat()], capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(invoke, range(6)))
    assert sum(r['claimed'] for r in results) == 1
    assert all(r['reason'] == 'already_claimed' for r in results if not r['claimed'])


def test_expired_pause_normalizes_to_none_and_never_blocks_disabling(database):
    pause = (BASE + timedelta(hours=2)).isoformat()
    assert settings(database, pause_until=pause)['pause_until'] is not None
    assert policy.get_settings(database, 'one', clock=lambda: BASE + timedelta(hours=3))['pause_until'] is None
    result = policy.set_settings(database, 'one', enabled=False, time_zone='Asia/Shanghai', quiet_start='22:00', quiet_end='08:00', cooldown_minutes=60, daily_limit=3, pause_until=pause, clock=lambda: BASE + timedelta(hours=3))
    assert result['enabled'] is False and result['pause_until'] is None
    assert policy.get_settings(database, 'one', clock=lambda: BASE + timedelta(hours=3))['pause_until'] is None


def test_concurrent_initial_settings_creation_fails_stale_version(database):
    def save(value):
        try:
            return settings(database, enabled=value, expected_revision=0)
        except followups.FollowupConflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, [True, False]))
    assert results.count('conflict') == 1
    winner = next(result for result in results if result != 'conflict')
    assert winner['revision'] == 1
    saved = policy.get_settings(database, 'one', clock=lambda: BASE)
    assert saved['revision'] == 1 and saved['enabled'] == winner['enabled']


def test_concurrent_settings_update_preserves_first_writer(database):
    assert settings(database)['revision'] == 1
    def save(limit):
        try:
            return settings(database, daily_limit=limit, expected_revision=1)
        except followups.FollowupConflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, [1, 2]))
    assert results.count('conflict') == 1
    winner = next(result for result in results if result != 'conflict')
    saved = policy.get_settings(database, 'one', clock=lambda: BASE)
    assert saved['revision'] == 2 and saved['daily_limit'] == winner['daily_limit']
    with pytest.raises(followups.FollowupConflict):
        settings(database, enabled=False, expected_revision=1)
    assert policy.get_settings(database, 'one', clock=lambda: BASE) == saved


def test_revision_migration_preserves_existing_record(tmp_path):
    path = tmp_path / 'legacy-settings.db'
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE sessions(id TEXT PRIMARY KEY)')
    conn.execute('INSERT INTO sessions VALUES(?)', ('one',))
    conn.execute("""CREATE TABLE followup_notification_settings (session_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL, time_zone TEXT NOT NULL, quiet_start TEXT NOT NULL, quiet_end TEXT NOT NULL, cooldown_minutes INTEGER NOT NULL, daily_limit INTEGER NOT NULL, pause_until TEXT, updated_at TEXT NOT NULL)""")
    conn.execute('INSERT INTO followup_notification_settings VALUES(?,?,?,?,?,?,?,?,?)', ('one',1,'Asia/Shanghai','22:00','08:00',60,2,None,BASE.isoformat()))
    policy.init_schema(conn)
    policy.init_schema(conn)
    conn.commit()
    conn.close()
    migrated = policy.get_settings(path, 'one', clock=lambda: BASE)
    assert migrated['revision'] == 1 and migrated['enabled'] and migrated['daily_limit'] == 2
    assert settings(path, daily_limit=1, expected_revision=1)['revision'] == 2
