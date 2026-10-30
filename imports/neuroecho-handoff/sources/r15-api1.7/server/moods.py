"""User-confirmed daily mood entries and deliberately limited draft suggestions.

The two coordinates are self-report aids, not measurements or diagnoses. The
optional recognizer does not read messages or hardware and never persists text.
"""
from datetime import date, datetime, timezone, timedelta
from contextlib import contextmanager
import re
import sqlite3
from pathlib import Path


class MoodConflict(ValueError):
    """Another window changed a record after the user loaded it."""

    def __init__(self, message, current_updated_at=None):
        super().__init__(message)
        self.current_updated_at = current_updated_at


def init_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS mood_entries (
        session_id TEXT NOT NULL, date TEXT NOT NULL,
        x REAL NOT NULL CHECK(x >= -1 AND x <= 1),
        y REAL NOT NULL CHECK(y >= -1 AND y <= 1),
        note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, PRIMARY KEY(session_id, date)
    )""")
    # This global clock carries no day, session, coordinates or note. It keeps
    # deleted-record versions from recurring after clock rollback or restore.
    conn.execute("""CREATE TABLE IF NOT EXISTS mood_version_clock (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        last_issued_at TEXT NOT NULL
    )""")
    conn.execute("INSERT OR IGNORE INTO mood_version_clock(singleton,last_issued_at) VALUES(1,?)",
                 ('1970-01-01T00:00:00.000000+00:00',))
    legacy = conn.execute('SELECT MAX(updated_at) FROM mood_entries').fetchone()[0]
    if legacy:
        clock = conn.execute('SELECT last_issued_at FROM mood_version_clock WHERE singleton=1').fetchone()[0]
        if datetime.fromisoformat(legacy) > datetime.fromisoformat(clock):
            conn.execute('UPDATE mood_version_clock SET last_issued_at=? WHERE singleton=1', (legacy,))


def _next_version(conn):
    """Issue a unique ISO UTC CAS token inside the caller's write transaction."""
    current = datetime.now(timezone.utc)
    previous = conn.execute('SELECT last_issued_at FROM mood_version_clock WHERE singleton=1').fetchone()[0]
    previous_time = datetime.fromisoformat(previous)
    if current <= previous_time:
        current = previous_time + timedelta(microseconds=1)
    stamp = current.astimezone(timezone.utc).isoformat(timespec='microseconds')
    conn.execute('UPDATE mood_version_clock SET last_issued_at=? WHERE singleton=1', (stamp,))
    return stamp


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('请使用有效的 YYYY-MM-DD 日期。')
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError('请使用有效的 YYYY-MM-DD 日期。') from None


@contextmanager
def _connect(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=rw', uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _check_session(conn, session_id):
    if not conn.execute('SELECT 1 FROM sessions WHERE id=?', (session_id,)).fetchone():
        raise LookupError('对话不存在。')


def list_entries(path, session_id):
    with _connect(path) as conn:
        _check_session(conn, session_id)
        return [dict(row) for row in conn.execute(
            'SELECT date,x,y,note,updated_at FROM mood_entries WHERE session_id=? ORDER BY date DESC',
            (session_id,)).fetchall()]


def save(path, session_id, day, x, y, note, expected_updated_at):
    day = _date(day)
    with _connect(path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        return save_in_transaction(conn, session_id, day, x, y, note, expected_updated_at)


def save_in_transaction(conn, session_id, day, x, y, note, expected_updated_at):
    """Shared mutation primitive; caller owns validation and write transaction."""
    _check_session(conn, session_id)
    previous = conn.execute('SELECT updated_at FROM mood_entries WHERE session_id=? AND date=?',
                            (session_id, day)).fetchone()
    if (previous['updated_at'] if previous else None) != expected_updated_at:
        raise MoodConflict('这一天的记录已在其他窗口更改，请刷新后再保存。',
                           previous['updated_at'] if previous else None)
    stamp = _next_version(conn)
    conn.execute('''INSERT INTO mood_entries(session_id,date,x,y,note,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(session_id,date) DO UPDATE SET
                    x=excluded.x,y=excluded.y,note=excluded.note,updated_at=excluded.updated_at''',
                 (session_id, day, x, y, note, stamp, stamp))
    row = conn.execute('SELECT date,x,y,note,updated_at FROM mood_entries WHERE session_id=? AND date=?',
                       (session_id, day)).fetchone()
    return dict(row)


def delete(path, session_id, day, expected_updated_at):
    day = _date(day)
    with _connect(path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        return delete_in_transaction(conn, session_id, day, expected_updated_at)


def delete_in_transaction(conn, session_id, day, expected_updated_at):
    _check_session(conn, session_id)
    previous = conn.execute('SELECT updated_at FROM mood_entries WHERE session_id=? AND date=?',
                            (session_id, day)).fetchone()
    if not previous or previous['updated_at'] != expected_updated_at:
        raise MoodConflict('这一天的记录已在其他窗口更改，请刷新后再删除。',
                           previous['updated_at'] if previous else None)
    result = conn.execute('DELETE FROM mood_entries WHERE session_id=? AND date=?', (session_id, day))
    return bool(result.rowcount)


def delete_for_session(conn, session_id):
    return conn.execute('DELETE FROM mood_entries WHERE session_id=?', (session_id,)).rowcount


# These are whole self-descriptions, not keyword matches in arbitrary text.
# For any additional context, quotation, negation or ambiguity we abstain.
_VALENCE = {'开心': 0.6, '愉快': 0.6, '难过': -0.6, '低落': -0.6}
_ENERGY = {'精力充沛': 0.6, '很有精神': 0.6, '疲惫': -0.6, '很累': -0.6}
_PART = r'(?:很开心|开心|很愉快|愉快|很难过|难过|很低落|低落|精力充沛|很有精神|很疲惫|疲惫|很累)'
_SELF = re.compile(rf'^(?:我今天|今天我)(?P<a>{_PART})(?:[，,、](?:而且|并且)?(?:我)?(?P<b>{_PART}))?[。.!！]?$')


def suggestion(path, session_id, text):
    with _connect(path) as conn:
        _check_session(conn, session_id)
    raw = text.strip()
    match = _SELF.fullmatch(raw)
    limits = ['仅参考你这次主动提供的自述，不能代表完整心情。',
              '手表、眼镜和脑机设备的情绪数据尚不可用；专注度不能直接推断情绪。',
              '这只是待你调整的草稿，不会自动保存。']
    if not match:
        return {'suggestion': None, 'limitations': limits}
    values = {'x': None, 'y': None}
    for word in (match.group('a'), match.group('b')):
        if not word:
            continue
        normalized = word[1:] if word.startswith('很') and word not in ('很有精神', '很累') else word
        for axis, dictionary in (('x', _VALENCE), ('y', _ENERGY)):
            if normalized in dictionary:
                if values[axis] is not None:  # Two claims about one axis are ambiguous.
                    return {'suggestion': None, 'limitations': limits}
                values[axis] = dictionary[normalized]
    if values['x'] is None and values['y'] is None:
        return {'suggestion': None, 'limitations': limits}
    return {'suggestion': {**values, 'evidence': [raw],
                           'explanation': '这只是一处可调整的参考位置；没有明确描述的维度留给你决定。'},
            'limitations': limits}
