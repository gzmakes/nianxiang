"""Explicit owner-issued, hashed-only credentials for one canonical conversation."""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
import sqlite3
import uuid

TOKEN = re.compile(r'^echo_pair_[A-Za-z0-9_-]{43}$')
SCOPE_KEY = 'xinji.paired_principal'
_SENTINEL = object()


def _now():
    return datetime.now(timezone.utc)


def _connect(database):
    conn = sqlite3.connect(database, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def initialize(database):
    with closing(_connect(database)) as conn, conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS paired_service (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), instance_id TEXT NOT NULL)''')
        conn.execute('INSERT OR IGNORE INTO paired_service VALUES(1,?)', ('svc_' + uuid.uuid4().hex,))
        conn.execute('''CREATE TABLE IF NOT EXISTS paired_devices (
            id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, label TEXT NOT NULL,
            conversation_id TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
            revoked_at TEXT)''')


def instance_id(database):
    with closing(_connect(database)) as conn:
        return conn.execute('SELECT instance_id FROM paired_service WHERE singleton=1').fetchone()[0]


def public_device(row):
    return {key:row[key] for key in ('id','label','created_at','expires_at','revoked_at')}


def create(database, conversation_id, label, expires_in_seconds=86400):
    if not isinstance(label,str) or not 1 <= len(label.strip()) <= 80 or any(ord(c)<32 for c in label):
        raise ValueError('Invalid device label.')
    if type(expires_in_seconds) is not int or not 300 <= expires_in_seconds <= 2592000:
        raise ValueError('Invalid credential lifetime.')
    token = 'echo_pair_' + secrets.token_urlsafe(32)
    stamp = _now()
    with closing(_connect(database)) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        device = {'id':'dev_'+uuid.uuid4().hex, 'label':label.strip(), 'created_at':stamp.isoformat(),
                  'expires_at':(stamp+timedelta(seconds=expires_in_seconds)).isoformat(), 'revoked_at':None}
        conn.execute('INSERT INTO paired_devices VALUES(?,?,?,?,?,?,NULL)',
                     (device['id'],hashlib.sha256(token.encode('ascii')).hexdigest(),device['label'],conversation_id,device['created_at'],device['expires_at']))
    return {**envelope(database,conversation_id),'device':device,'token':token}


def envelope(database, conversation_id):
    return {'service_instance_id':instance_id(database),'conversation_id':conversation_id,
            'scope':'personal_core','local_actions_allowed':False}


def list_devices(database, conversation_id):
    with closing(_connect(database)) as conn:
        rows = conn.execute('SELECT * FROM paired_devices ORDER BY created_at DESC,id').fetchall()
    return {**envelope(database,conversation_id),'devices':[public_device(row) for row in rows]}


def revoke(database, device_id):
    with closing(_connect(database)) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT id FROM paired_devices WHERE id=?',(device_id,)).fetchone()
        if row is None: return None
        conn.execute('UPDATE paired_devices SET revoked_at=COALESCE(revoked_at,?) WHERE id=?',(_now().isoformat(),device_id))
    return {'service_instance_id':instance_id(database),'device_id':device_id,'revoked':True,
            'in_flight_may_have_committed':True}


@dataclass(frozen=True)
class Principal:
    database: str
    device_id: str
    conversation_id: str
    service_instance_id: str


def _active_row(conn, device_id=None, token_hash=None):
    field, value = ('d.id',device_id) if device_id is not None else ('d.token_hash',token_hash)
    row = conn.execute(f'''SELECT d.* FROM paired_devices d JOIN sessions s ON s.id=d.conversation_id
        JOIN app_state a ON a.key='canonical_conversation' AND a.value=d.conversation_id
        WHERE {field}=? AND d.revoked_at IS NULL''',(value,)).fetchone()
    if row is None:return None
    try:
        expires=datetime.fromisoformat(row['expires_at'])
        return row if expires.tzinfo is not None and expires > _now() else None
    except (TypeError,ValueError):return None


def authenticate(database, authorization):
    if not isinstance(authorization,str) or not authorization.startswith('Bearer '): return None
    token = authorization[7:]
    if not TOKEN.fullmatch(token): return None
    try:
        with closing(_connect(database)) as conn:
            conn.execute('BEGIN')
            row = _active_row(conn,token_hash=hashlib.sha256(token.encode('ascii')).hexdigest())
            instance=conn.execute('SELECT instance_id FROM paired_service WHERE singleton=1').fetchone()
            if row is None or instance is None:return None
            return Principal(str(database),row['id'],row['conversation_id'],instance[0])
    except sqlite3.Error:return None


def _principal_row(conn,principal):
    conn.execute('BEGIN')
    row=_active_row(conn,device_id=principal.device_id)
    instance=conn.execute('SELECT instance_id FROM paired_service WHERE singleton=1').fetchone()
    if (row is None or row['conversation_id']!=principal.conversation_id or instance is None
            or instance[0]!=principal.service_instance_id):return None
    return row


def active(principal):
    try:
        with closing(_connect(principal.database)) as conn:
            return _principal_row(conn,principal) is not None
    except sqlite3.Error:return False


def public_principal(principal):
    try:
        with closing(_connect(principal.database)) as conn:
            row = _principal_row(conn,principal)
    except sqlite3.Error:return None
    if row is None: return None
    return {'service_instance_id':principal.service_instance_id,'conversation_id':principal.conversation_id,
            'scope':'personal_core','local_actions_allowed':False,'device':public_device(row)}


def stamp_scope(scope, principal):
    scope[SCOPE_KEY] = (_SENTINEL,principal)


def principal_from_scope(scope):
    value = scope.get(SCOPE_KEY)
    if (isinstance(value,tuple) and len(value)==2 and value[0] is _SENTINEL
            and isinstance(value[1],Principal)):
        return value[1]
    return None


def resource_belongs(principal, table, key):
    if table not in ('memories','followups'): return False
    with closing(_connect(principal.database)) as conn:
        row = conn.execute(f'SELECT session_id FROM {table} WHERE id=?',(key,)).fetchone()
    return row is not None and row[0] == principal.conversation_id
