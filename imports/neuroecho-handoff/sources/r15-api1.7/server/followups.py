"""Consent-based, one-time in-app follow-ups. No background delivery occurs here."""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re
import sqlite3
import uuid
from pathlib import Path


class FollowupConflict(ValueError):
    """A request key or a terminal transition conflicts with existing state."""


def init_schema(conn):
    """Create schema on the supplied connection; caller owns commit/rollback."""
    conn.execute("""CREATE TABLE IF NOT EXISTS followups (
        id TEXT PRIMARY KEY, session_id TEXT NOT NULL, request_id TEXT NOT NULL,
        content TEXT NOT NULL, due_at TEXT NOT NULL, status TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(session_id, request_id),
        CHECK(status IN ('pending', 'done', 'cancelled'))
    )""")
    # Additive migration: existing reminders and their request IDs are preserved.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(followups)")}
    for name, spec in (("repeat_rule", "TEXT NOT NULL DEFAULT 'once'"),
                       ("time_zone", "TEXT NOT NULL DEFAULT 'UTC'"),
                       ("quiet_start", "TEXT"), ("quiet_end", "TEXT"),
                       ("paused", "INTEGER NOT NULL DEFAULT 0"),
                       ("last_completed_at", "TEXT"), ("last_occurrence_at", "TEXT"),
                       ("created_due_at", "TEXT"),
                       ("allow_contact", "INTEGER NOT NULL DEFAULT 0"),
                       ("contact_window_minutes", "INTEGER NOT NULL DEFAULT 30"),
                       ("contact_topic", "TEXT"),
                       ("contact_suppression_revision", "INTEGER NOT NULL DEFAULT -1")):
        if name not in columns:
            conn.execute(f"ALTER TABLE followups ADD COLUMN {name} {spec}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_followups_session ON followups(session_id, status, due_at)")


def _utc(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("时间必须是带时区偏移的 ISO 8601 时间。")
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ValueError("时间必须是带时区偏移的有效 ISO 8601 时间。") from None


def _current(clock):
    value = clock() if clock else datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _stamp(dt):
    return dt.isoformat(timespec='microseconds')


def _connect(db_path):
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=rw', uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _audit(conn, session_id, kind, followup_id, stamp):
    conn.execute("INSERT INTO audit(id,session_id,action,detail,reason,created_at) VALUES(?,?,?,?,?,?)",
                 ('aud_' + uuid.uuid4().hex[:12], session_id, kind, followup_id,
                  '用户确认', stamp))


def _zone(name):
    if not isinstance(name, str) or len(name) > 128:
        raise ValueError('请选择有效时区。')
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('请选择有效时区。') from None


def _quiet(start, end, current, zone):
    if start is None and end is None:
        return False
    if not all(isinstance(x, str) and re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', x) for x in (start, end)) or start == end:
        raise ValueError('请填写不同的安静时段开始和结束时间。')
    local = current.astimezone(zone).strftime('%H:%M')
    return start <= local < end if start < end else local >= start or local < end


def _next_daily(due, current, zone):
    # Daily wall-clock time in the chosen zone (not a fixed 24h UTC interval).
    local_due, local_now = due.astimezone(zone), current.astimezone(zone)
    target = local_now.date()
    candidate = datetime.combine(target, local_due.timetz().replace(tzinfo=None), zone)
    candidate = candidate.astimezone(timezone.utc).astimezone(zone)  # normalize DST gaps
    if candidate.astimezone(timezone.utc) <= current:
        candidate = datetime.combine(target + timedelta(days=1), local_due.timetz().replace(tzinfo=None), zone)
        candidate = candidate.astimezone(timezone.utc).astimezone(zone)
    return candidate.astimezone(timezone.utc)


def _present(row, current, conn=None):
    item = dict(row)
    quiet = _quiet(item['quiet_start'], item['quiet_end'], current, _zone(item['time_zone']))
    item['paused'] = bool(item['paused'])
    item['due'] = item['status'] == 'pending' and _utc(item['due_at']) <= current
    item['quiet'] = quiet
    item['review_available'] = item['due'] and not item['paused'] and not quiet
    item['allow_contact'] = bool(item.get('allow_contact', False))
    item['contact_window_minutes'] = item.get('contact_window_minutes',30)
    item['contact_topic'] = item.get('contact_topic') or item['content']
    expires = _utc(item['due_at']) + timedelta(minutes=item['contact_window_minutes'])
    item['contact_expires_at'] = _stamp(expires)
    reason = ('contact_not_allowed' if not item['allow_contact'] else
              'completed' if item['status']!='pending' else 'not_due' if not item['due'] else
              'expired' if current>=expires else 'item_paused' if item['paused'] else 'item_quiet' if quiet else None)
    revision = 0
    if conn is not None:
        from . import companion_boundary, proactive_policy
        if companion_boundary.exists(conn):
            boundary=companion_boundary.snapshot(conn,item['session_id'],current)
            revision = boundary['revision']
            if item.get('contact_suppression_revision',-1)!=boundary['suppression_revision']:
                reason=reason or 'boundary_changed'
            reason = reason or companion_boundary.blocked(conn,item['session_id'],_utc(item['due_at']),current)
            reason = reason or proactive_policy.contact_blocked(conn,item['session_id'],item,current,channel='in_app')
    item['boundary_revision'] = revision
    item['contact_reason'] = reason
    item['contact_eligible'] = reason is None
    item['available'] = item['contact_eligible']
    return item


def create(db_path, session_id, content, due_at, request_id, *, repeat_rule="once", time_zone="UTC", quiet_start=None, quiet_end=None, allow_contact=False, contact_window_minutes=30, contact_topic=None, clock=None):
    """Create once for a request key, or return its matching existing record."""
    if not isinstance(session_id, str) or not session_id or len(session_id) > 128:
        raise ValueError('无效的对话。')
    if not isinstance(content, str) or not content.strip() or len(content) > 1000:
        raise ValueError('请输入 1 至 1000 字的跟进内容。')
    if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128:
        raise ValueError('无效的请求标识。')
    content = content.strip()
    if type(allow_contact) is not bool:raise ValueError('请明确选择是否允许联系。')
    if type(contact_window_minutes) is not int or not 5<=contact_window_minutes<=180:raise ValueError('联系窗口须为5至180分钟。')
    if contact_topic is None:contact_topic=content
    if not isinstance(contact_topic,str) or not contact_topic.strip() or len(contact_topic)>1000:raise ValueError('联系话题须为1至1000字。')
    contact_topic=contact_topic.strip()
    if repeat_rule not in ('once', 'daily'):
        raise ValueError('重复方式无效。')
    zone = _zone(time_zone)
    _quiet(quiet_start, quiet_end, _current(clock), zone)
    due = _utc(due_at)
    due_stamp = _stamp(due)
    current = _current(clock)
    conn = _connect(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        if not conn.execute('SELECT 1 FROM sessions WHERE id=?', (session_id,)).fetchone():
            raise LookupError('对话不存在。')
        row = conn.execute('SELECT * FROM followups WHERE session_id=? AND request_id=?',
                           (session_id, request_id)).fetchone()
        if row:
            if (row['content'] != content or (row['due_at'] != due_stamp and row['repeat_rule'] == 'once') or (row['repeat_rule'] == 'daily' and row['created_due_at'] != due_stamp) or row['repeat_rule'] != repeat_rule or row['time_zone'] != time_zone or row['quiet_start'] != quiet_start or row['quiet_end'] != quiet_end or bool(row['allow_contact']) != allow_contact or row['contact_window_minutes'] != contact_window_minutes or (row['contact_topic'] or row['content']) != contact_topic):
                raise FollowupConflict('请求标识已用于不同内容或时间。')
            conn.commit()
            return _present(row, current, conn)
        if due <= current:
            raise ValueError('请选择未来的时间。')
        fid, stamp = 'fup_' + uuid.uuid4().hex[:12], _stamp(current)
        from . import companion_boundary
        consent_revision=companion_boundary.snapshot(conn,session_id,current)['suppression_revision']
        conn.execute('''INSERT INTO followups(id,session_id,request_id,content,due_at,status,created_at,updated_at,repeat_rule,time_zone,quiet_start,quiet_end,created_due_at,allow_contact,contact_window_minutes,contact_topic,contact_suppression_revision) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                     (fid, session_id, request_id, content, due_stamp, 'pending', stamp, stamp, repeat_rule, time_zone, quiet_start, quiet_end, due_stamp, int(allow_contact), contact_window_minutes, contact_topic,consent_revision))
        _audit(conn, session_id, 'followup.create', fid, stamp)
        row = conn.execute('SELECT * FROM followups WHERE id=?', (fid,)).fetchone()
        conn.commit()
        return _present(row, current, conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_for_session(db_path, session_id, *, clock=None):
    """Return records with due derived at read time; does not mark delivery."""
    current = _current(clock)
    conn = _connect(db_path)
    try:
        rows = conn.execute('SELECT * FROM followups WHERE session_id=? ORDER BY due_at, id',
                            (session_id,)).fetchall()
        return [_present(row, current, conn) for row in rows]
    finally:
        conn.close()


def transition(db_path, session_id, followup_id, target, *, occurrence_at=None, clock=None):
    """Move pending to done/cancelled atomically; repeat of same target is safe."""
    if target not in ('done', 'cancelled', 'paused', 'resumed'):
        raise ValueError('无效的跟进状态。')
    current = _current(clock)
    stamp = _stamp(current)
    conn = _connect(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM followups WHERE id=? AND session_id=?',
                           (followup_id, session_id)).fetchone()
        if not row:
            raise LookupError('跟进事项不存在。')
        if target in ('paused', 'resumed'):
            if row['status'] != 'pending':
                raise FollowupConflict('这条跟进已处理。')
            desired = 1 if target == 'paused' else 0
            if row['paused'] != desired:
                conn.execute('UPDATE followups SET paused=?, updated_at=? WHERE id=?', (desired, stamp, followup_id))
                _audit(conn, session_id, 'followup.' + target, followup_id, stamp)
                row = conn.execute('SELECT * FROM followups WHERE id=?', (followup_id,)).fetchone()
            conn.commit()
            return _present(row, current, conn)
        if target == 'done' and row['status'] == 'pending' and row['repeat_rule'] == 'daily':
            if not occurrence_at:
                raise ValueError('请指定要完成的这次跟进。')
            occurrence_stamp = _stamp(_utc(occurrence_at))
            if row['last_occurrence_at'] == occurrence_stamp:
                conn.commit()
                return _present(row, current, conn)
            if occurrence_stamp != row['due_at']:
                raise FollowupConflict('这次跟进状态已变化，请刷新后重试。')
            if not _present(row, current, conn)['due']:
                raise FollowupConflict('当前没有可完成的每日跟进。')
            next_due = _stamp(_next_daily(_utc(row['created_due_at'] or row['due_at']), current, _zone(row['time_zone'])))
            conn.execute('UPDATE followups SET due_at=?,last_occurrence_at=?,last_completed_at=?,updated_at=? WHERE id=?',
                         (next_due, row['due_at'], stamp, stamp, followup_id))
            _audit(conn, session_id, 'followup.occurrence_done', followup_id, stamp)
            row = conn.execute('SELECT * FROM followups WHERE id=?', (followup_id,)).fetchone()
            conn.commit()
            return _present(row, current, conn)
        if row['status'] not in ('pending', target):
            raise FollowupConflict('这条跟进已处理。')
        if row['status'] == 'pending':
            conn.execute("UPDATE followups SET status=?,updated_at=? WHERE id=? AND session_id=? AND status='pending'",
                         (target, stamp, followup_id, session_id))
            _audit(conn, session_id, 'followup.' + target, followup_id, stamp)
            row = conn.execute('SELECT * FROM followups WHERE id=?', (followup_id,)).fetchone()
        conn.commit()
        return _present(row, current, conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_for_export(db_path, session_id=None):
    conn = _connect(db_path)
    try:
        if session_id is None:
            rows = conn.execute('SELECT * FROM followups ORDER BY created_at,id').fetchall()
        else:
            rows = conn.execute('SELECT * FROM followups WHERE session_id=? ORDER BY created_at,id', (session_id,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def delete_for_session(conn, session_id):
    """Delete within caller's transaction; do not commit. Return deleted count."""
    return conn.execute('DELETE FROM followups WHERE session_id=?', (session_id,)).rowcount
