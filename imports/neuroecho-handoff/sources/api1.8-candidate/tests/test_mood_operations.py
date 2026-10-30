"""Persistent write identity, crash recovery and content-retention boundaries."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from threading import Barrier

from fastapi.testclient import TestClient
import pytest

from server import core, mood_operations, moods
from server.main import app


@pytest.fixture()
def context():
    with TestClient(app) as client:
        yield client, client.get('/api/conversation').json()['session']['id']


def payload(**changes):
    data = dict(kind='save', date='2026-10-30', expected_updated_at=None,
                x=.3, y=-.4, note='合成记录🙂')
    data.update(changes)
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'))


def digest(raw):
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def apply(client, sid, identity, raw):
    return client.post('/api/mood-operations', json=dict(
        session_id=sid, request_id=identity, operation_json=raw, confirmed=True))


def query(client, sid, identity):
    return client.get('/api/mood-operations/' + identity, params={'session_id': sid})


def cancel(client, sid, identity, raw, kind='save'):
    return client.post('/api/mood-operations/' + identity + '/cancel', json=dict(
        session_id=sid, operation_sha256=digest(raw), kind=kind, confirmed=True))


def records(client, sid):
    return client.get('/api/moods', params={'session_id': sid}).json()['moods']


def test_not_found_is_metadata_only_and_capability_is_additive(context):
    client, sid = context
    response = query(client, sid, 'r11-unseen-id')
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert response.json() == dict(session_id=sid, request_id='r11-unseen-id',
        operation_sha256=None, kind=None, state='not_found', result_updated_at=None)
    capabilities = client.get('/api/capabilities').json()
    assert capabilities['contract_version'] == '1.8.0'
    for flag in ['mood_operation_ledger', 'daily_mood_entries', 'companion_boundaries',
                 'bounded_followup_contact', 'chat_delivery_targeted_stop']:
        assert capabilities['features'][flag] is True


def test_exact_utf8_identity_replays_without_rewriting_and_rejects_reserialization(context):
    client, sid = context
    raw = payload()
    first = apply(client, sid, 'r11-exact-id', raw).json()
    assert first == dict(session_id=sid, request_id='r11-exact-id', operation_sha256=digest(raw),
                         kind='save', state='applied', result_updated_at=records(client, sid)[0]['updated_at'])
    assert apply(client, sid, 'r11-exact-id', raw).json() == first
    assert query(client, sid, 'r11-exact-id').json() == first
    for changed in [' ' + raw, json.dumps(json.loads(raw), ensure_ascii=True), payload(note='changed')]:
        response = apply(client, sid, 'r11-exact-id', changed)
        assert response.status_code == 409 and response.json()['error_code'] == 'mood_operation_identity_conflict'
    assert len(records(client, sid)) == 1
    assert records(client, sid)[0]['updated_at'] == first['result_updated_at']


@pytest.mark.parametrize('raw', [payload(), '{ invalid raw JSON'])
def test_pre_cancel_retires_even_invalid_payload_and_blocks_late_apply(context, raw):
    client, sid = context
    receipt = cancel(client, sid, 'r11-pre-cancel', raw).json()
    assert receipt['state'] == 'cancelled' and receipt['result_updated_at'] is None
    assert cancel(client, sid, 'r11-pre-cancel', raw).json() == receipt
    assert apply(client, sid, 'r11-pre-cancel', raw).json() == receipt
    assert records(client, sid) == []
    assert apply(client, sid, 'r11-pre-cancel', payload(note='other')).status_code == 409
    assert cancel(client, sid, 'r11-pre-cancel', raw, kind='delete').status_code == 409


def test_applied_cancel_does_not_roll_back_and_old_save_cannot_resurrect_deleted_diary(context):
    client, sid = context
    raw = payload()
    applied = apply(client, sid, 'r11-applied-save', raw).json()
    assert cancel(client, sid, 'r11-applied-save', raw).json() == applied
    assert records(client, sid)[0]['note'] == '合成记录🙂'
    assert client.delete('/api/moods/2026-10-30', params={
        'session_id': sid, 'expected_updated_at': applied['result_updated_at']}).json()['deleted']
    assert apply(client, sid, 'r11-applied-save', raw).json() == applied
    assert records(client, sid) == []


def test_old_applied_delete_does_not_delete_a_recreated_day(context):
    client, sid = context
    saved = apply(client, sid, 'r11-save-before-delete', payload()).json()
    raw = json.dumps(dict(kind='delete', date='2026-10-30', expected_updated_at=saved['result_updated_at']))
    deleted = apply(client, sid, 'r11-ledger-delete', raw).json()
    assert deleted['state'] == 'applied' and deleted['kind'] == 'delete'
    assert deleted['result_updated_at'] == saved['result_updated_at'] and records(client, sid) == []
    newer = apply(client, sid, 'r11-recreate-day', payload(note='new day')).json()
    assert apply(client, sid, 'r11-ledger-delete', raw).json() == deleted
    assert cancel(client, sid, 'r11-ledger-delete', raw, kind='delete').json() == deleted
    assert records(client, sid)[0]['updated_at'] == newer['result_updated_at']


def test_cas_conflict_is_queryable_terminal_not_a_retried_write(context):
    client, sid = context
    existing = apply(client, sid, 'r11-existing-entry', payload()).json()
    raw = payload(note='another draft')
    conflict = apply(client, sid, 'r11-conflicting-id', raw)
    assert conflict.status_code == 200
    assert conflict.json()['state'] == 'conflict'
    assert conflict.json()['result_updated_at'] == existing['result_updated_at']
    client.delete('/api/moods/2026-10-30', params={'session_id': sid, 'expected_updated_at': existing['result_updated_at']})
    assert apply(client, sid, 'r11-conflicting-id', raw).json() == conflict.json()
    assert cancel(client, sid, 'r11-conflicting-id', raw).json() == conflict.json()
    assert records(client, sid) == []
    assert apply(client, sid, 'r11-explicit-new-id', raw).json()['state'] == 'applied'


@pytest.mark.parametrize('same_id', [True, False])
def test_competing_creates_are_atomic_for_same_and_different_identities(context, same_id):
    client, sid = context
    barrier = Barrier(2)
    raw = payload()
    def write(index):
        barrier.wait(timeout=5)
        return apply(client, sid, 'r11-racing-id' if same_id else f'r11-racing-id-{index}', raw).json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(write, range(2)))
    assert sorted(row['state'] for row in responses) == (['applied', 'applied'] if same_id else ['applied', 'conflict'])
    if same_id:
        assert responses[0] == responses[1]
    assert len(records(client, sid)) == 1


def test_cancel_and_apply_race_has_one_terminal_decision(context):
    client, sid = context
    raw = payload()
    barrier = Barrier(2)
    def race(kind):
        barrier.wait(timeout=5)
        return (cancel if kind == 'cancel' else apply)(client, sid, 'r11-cancel-race', raw).json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(race, ['apply', 'cancel']))
    assert responses[0] == responses[1]
    assert responses[0]['state'] in ('cancelled', 'applied')
    assert len(records(client, sid)) == (1 if responses[0]['state'] == 'applied' else 0)


def test_failure_between_diary_and_ledger_rolls_back_both(context, monkeypatch):
    client, sid = context
    before = core.export_data(sid)
    original = mood_operations._insert
    monkeypatch.setattr(mood_operations, '_insert', lambda *args: (_ for _ in ()).throw(RuntimeError('synthetic crash')))
    with pytest.raises(RuntimeError, match='synthetic crash'):
        apply(client, sid, 'r11-atomic-rollback', payload())
    assert core.export_data(sid) == before
    assert query(client, sid, 'r11-atomic-rollback').json()['state'] == 'not_found'
    monkeypatch.setattr(mood_operations, '_insert', original)
    assert apply(client, sid, 'r11-atomic-rollback', payload()).json()['state'] == 'applied'


@pytest.mark.parametrize('crash_before_commit', [True, False])
def test_process_loss_with_no_response_can_be_queried_or_pre_cancelled(context, crash_before_commit):
    client, sid = context
    identity = 'r11-process-loss'
    raw = payload()
    code = '''import os,sys
from server import mood_operations
if sys.argv[5] == 'before':
    mood_operations._insert = lambda *args: os._exit(0)
mood_operations.apply(sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4])
os._exit(0)
'''
    child = subprocess.run([sys.executable, '-B', '-c', code, str(core.DB_PATH), sid, identity, raw,
                            'before' if crash_before_commit else 'after'],
                           cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15)
    assert child.returncode == 0
    observed = query(client, sid, identity).json()
    if crash_before_commit:
        assert observed['state'] == 'not_found' and records(client, sid) == []
        assert cancel(client, sid, identity, raw).json()['state'] == 'cancelled'
        assert apply(client, sid, identity, raw).json()['state'] == 'cancelled'
    else:
        assert observed['state'] == 'applied'
        assert apply(client, sid, identity, raw).json() == observed
        assert records(client, sid)[0]['updated_at'] == observed['result_updated_at']


def test_ledger_export_is_metadata_only_and_session_deletion_is_scoped(context):
    client, sid = context
    other = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    secret = 'synthetic-content-not-retained-in-ledger'
    raw = payload(note=secret)
    first = apply(client, sid, 'r11-export-ledger', raw).json()
    assert query(client, other, 'r11-export-ledger').json()['state'] == 'not_found'
    other_row = apply(client, other, 'r11-export-ledger', payload(note='other session')).json()
    client.delete('/api/moods/2026-10-30', params={'session_id': sid, 'expected_updated_at': first['result_updated_at']})
    exported = core.export_data(sid)
    assert exported['mood_entries'] == [] and len(exported['mood_operations']) == 1
    expected = {'session_id', 'request_id', 'operation_sha256', 'kind', 'state', 'result_updated_at', 'created_at'}
    assert set(exported['mood_operations'][0]) == expected
    assert secret not in json.dumps(exported)
    with core.get_db() as conn:
        assert {row['name'] for row in conn.execute('PRAGMA table_info(mood_operations)')} == expected
    assert core.delete_session(sid)['deleted']['mood_operations'] == 1
    assert query(client, sid, 'r11-export-ledger').status_code == 404
    assert apply(client, sid, 'r11-export-ledger', raw).status_code == 404
    assert cancel(client, sid, 'r11-export-ledger', raw).status_code == 404
    assert query(client, other, 'r11-export-ledger').json() == other_row


def test_legacy_put_delete_do_not_invent_operation_identities(context):
    client, sid = context
    legacy = json.loads(payload()); legacy.pop('date')
    saved = client.put('/api/moods/2026-10-30', json={**legacy, 'session_id': sid,
                      'confirmed': True}).status_code
    # Legacy endpoint must still reject the new inner-only kind field.
    assert saved == 422
    legacy.pop('kind')
    response = client.put('/api/moods/2026-10-30', json={**legacy, 'session_id': sid, 'confirmed': True})
    assert response.status_code == 200
    assert core.export_data(sid)['mood_operations'] == []
    client.delete('/api/moods/2026-10-30', params={'session_id': sid, 'expected_updated_at': response.json()['updated_at']})
    assert core.export_data(sid)['mood_operations'] == []


@pytest.mark.parametrize('raw', [
    '{}', '[]', '{', payload(kind='unknown'), payload(date='2026-02-30'),
    payload(x=True), payload(x='0.3'), payload(x=float('inf')),
    payload(expected_updated_at='not-ISO'), payload(extra='not allowed'),
    '{"kind":"save","kind":"delete"}',
    json.dumps(dict(kind='delete', date='2026-10-30', expected_updated_at=None)),
    json.dumps(dict(kind='delete', date='2026-10-30', expected_updated_at='2026-10-30T00:00:00+00:00', note='extra')),
    json.dumps({k:v for k,v in json.loads(payload()).items() if k != 'note'}),
    ' ' * 14000 + payload(note='🙂' * 1000),
])
def test_invalid_inner_json_is_rejected_without_body_reflection_or_ledger(context, raw):
    client, sid = context
    response = apply(client, sid, 'r11-invalid-inner', raw)
    assert response.status_code == 400
    assert response.json()['error_code'] == 'invalid_mood_operation'
    assert 'operation_json' not in response.json() and 'input' not in response.json()
    assert query(client, sid, 'r11-invalid-inner').json()['state'] == 'not_found'
    assert records(client, sid) == []


def test_cancel_confirmation_identity_fields_and_origin_are_required(context):
    client, sid = context
    raw = payload()
    body = dict(session_id=sid, operation_sha256=digest(raw), kind='save', confirmed=True)
    path = '/api/mood-operations/r11-cancel-validation/cancel'
    assert client.post(path, json={**body, 'confirmed': False}).status_code == 400
    assert client.post(path, json={**body, 'confirmed': 'true'}).status_code == 422
    assert client.post(path, json={**body, 'operation_sha256': 'bad'}).status_code == 422
    assert client.post(path, json={**body, 'operation_json': raw}).status_code == 422
    assert client.post(path, json=body, headers={'Origin':'https://evil.invalid'}).status_code == 403
    assert query(client, sid, 'r11-cancel-validation').json()['state'] == 'not_found'
