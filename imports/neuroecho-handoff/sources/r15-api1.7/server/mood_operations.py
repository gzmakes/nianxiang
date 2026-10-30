"""Atomic mood-write identities; retain metadata, never historical diary text."""
from datetime import datetime, timezone
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from . import moods

MAX_OPERATION_BYTES = 16384


class InvalidOperation(ValueError):
    pass


class IdentityConflict(ValueError):
    pass


def _version(value):
    if value is not None:
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError('Version must include its UTC offset.')
    return value


class _Save(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['save']
    date: str
    expected_updated_at: str | None = Field(min_length=1, max_length=64)
    x: float = Field(ge=-1, le=1, strict=True, allow_inf_nan=False)
    y: float = Field(ge=-1, le=1, strict=True, allow_inf_nan=False)
    note: str = Field(max_length=1000)

    _day = field_validator('date')(moods._date)
    _stamp = field_validator('expected_updated_at')(_version)


class _Delete(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['delete']
    date: str
    expected_updated_at: str = Field(min_length=1, max_length=64)

    _day = field_validator('date')(moods._date)
    _stamp = field_validator('expected_updated_at')(_version)


def operation_hash(raw):
    try:
        encoded = raw.encode('utf-8')
    except (AttributeError, UnicodeEncodeError):
        raise InvalidOperation('心情请求编码无效，没有执行写入。') from None
    if not encoded or len(encoded) > MAX_OPERATION_BYTES:
        raise InvalidOperation('心情请求大小无效，没有执行写入。')
    return hashlib.sha256(encoded).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def _constant(_):
    raise ValueError('non-finite JSON constant')


def parse_operation(raw):
    try:
        data = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
        if not isinstance(data, dict) or data.get('kind') not in ('save', 'delete'):
            raise ValueError('operation must be a known object')
        model = _Save if data['kind'] == 'save' else _Delete
        return model.model_validate(data).model_dump()
    except (ValueError, ValidationError, TypeError, RecursionError):
        # Do not echo the raw request, note, coordinates or validation input.
        raise InvalidOperation('心情请求字段或版本无效，没有执行写入。') from None


def init_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS mood_operations (
        session_id TEXT NOT NULL, request_id TEXT NOT NULL,
        operation_sha256 TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('save','delete')),
        state TEXT NOT NULL CHECK(state IN ('applied','conflict','cancelled')),
        result_updated_at TEXT, created_at TEXT NOT NULL,
        PRIMARY KEY(session_id,request_id)
    )''')


def _receipt(row, session_id, request_id):
    return {'session_id': session_id, 'request_id': request_id,
            'operation_sha256': row['operation_sha256'] if row else None,
            'kind': row['kind'] if row else None,
            'state': row['state'] if row else 'not_found',
            'result_updated_at': row['result_updated_at'] if row else None}


def _existing(conn, session_id, request_id):
    return conn.execute('SELECT * FROM mood_operations WHERE session_id=? AND request_id=?',
                        (session_id, request_id)).fetchone()


def _check_identity(row, digest, kind=None):
    if row['operation_sha256'] != digest or (kind is not None and row['kind'] != kind):
        raise IdentityConflict('这个心情请求标识已绑定其他内容，请核对原请求，不会覆盖或重做。')


def _insert(conn, session_id, request_id, digest, kind, state, version):
    conn.execute('INSERT INTO mood_operations VALUES(?,?,?,?,?,?,?)',
                 (session_id, request_id, digest, kind, state, version,
                  datetime.now(timezone.utc).isoformat(timespec='microseconds')))
    return _receipt(_existing(conn, session_id, request_id), session_id, request_id)


def apply(path, session_id, request_id, raw):
    digest = operation_hash(raw)
    with moods._connect(path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        moods._check_session(conn, session_id)
        previous = _existing(conn, session_id, request_id)
        if previous:
            _check_identity(previous, digest)
            # A cancelled invalid request is retired too. Never parse/reapply
            # a terminal identity, or resurrect a diary deleted afterwards.
            return _receipt(previous, session_id, request_id)
        operation = parse_operation(raw)
        state, version = 'applied', None
        try:
            if operation['kind'] == 'save':
                saved = moods.save_in_transaction(conn, session_id, operation['date'], operation['x'],
                                                  operation['y'], operation['note'], operation['expected_updated_at'])
                version = saved['updated_at']
            else:
                moods.delete_in_transaction(conn, session_id, operation['date'], operation['expected_updated_at'])
                version = operation['expected_updated_at']
        except moods.MoodConflict as error:
            state, version = 'conflict', error.current_updated_at
        return _insert(conn, session_id, request_id, digest, operation['kind'], state, version)


def get(path, session_id, request_id):
    with moods._connect(path) as conn:
        conn.execute('BEGIN')
        moods._check_session(conn, session_id)
        return _receipt(_existing(conn, session_id, request_id), session_id, request_id)


def cancel(path, session_id, request_id, digest, kind):
    with moods._connect(path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        moods._check_session(conn, session_id)
        previous = _existing(conn, session_id, request_id)
        if previous:
            _check_identity(previous, digest, kind)
            return _receipt(previous, session_id, request_id)
        return _insert(conn, session_id, request_id, digest, kind, 'cancelled', None)


def delete_for_session(conn, session_id):
    return conn.execute('DELETE FROM mood_operations WHERE session_id=?', (session_id,)).rowcount
