"""Persistent timed delivery of one assistant reply, interruptible atomically."""
from __future__ import annotations
import json
import re
import time


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS chat_delivery (
        message_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, parts TEXT NOT NULL,
        start REAL NOT NULL, offsets TEXT NOT NULL, stopped INTEGER NOT NULL DEFAULT 0)''')
    conn.execute('CREATE INDEX IF NOT EXISTS chat_delivery_session ON chat_delivery(session_id)')


def split_reply(text):
    text = str(text or '')
    # Preserve rich/long or technical answers intact; split ordinary paragraphs.
    if len(text) > 1200 or re.search(r'(?m)^\s*(?:[-*#>]\s|\d+[.、)]\s*)|```', text):
        return [text]
    parts = [p.strip() for p in re.split(r'\n\s*\n', text.strip()) if p.strip()]
    if len(parts) < 2 or len(parts) > 12 or any(len(p) > 360 for p in parts):
        return [text]
    # At most four actual sends, preserving all paragraphs and original order.
    count = min(4, len(parts))
    return ['\n\n'.join(parts[i * len(parts) // count:(i + 1) * len(parts) // count]) for i in range(count)]


def register(conn, sid, mid, text, at=None):
    parts = split_reply(text)
    if len(parts) < 2:
        return
    offsets = [0.0]
    for part in parts[:-1]:
        offsets.append(offsets[-1] + min(2.0, max(.8, len(part) * .035)))
    conn.execute('INSERT INTO chat_delivery(message_id,session_id,parts,start,offsets) VALUES(?,?,?,?,?)',
                 (mid, sid, json.dumps(parts, ensure_ascii=False), time.time() if at is None else at, json.dumps(offsets)))


def _state(row, at):
    parts = json.loads(row['parts'])
    offsets = json.loads(row['offsets'])
    elapsed = max(0, at - row['start'])
    count = min(len(parts), max(1, sum(offset <= elapsed for offset in offsets)))
    return parts, offsets, count


def annotate(conn, sid, messages, at=None):
    at = time.time() if at is None else at
    rows = {r['message_id']: r for r in conn.execute('SELECT * FROM chat_delivery WHERE session_id=?', (sid,))}
    for m in messages:
        row = rows.get(m['id'])
        if not row:
            continue
        parts, offsets, count = _state(row, at)
        visible = parts[:count]
        m['text'] = '\n\n'.join(visible)
        m['bubbles'] = visible
        pending = count < len(parts) and not row['stopped']
        m['delivery_pending'] = pending
        if pending:
            m['delivery_next_ms'] = max(50, min(2000, int((row['start'] + offsets[count] - at) * 1000) + 25))
    return messages


def interrupt(conn, sid, at=None):
    """Stop pending sends and truncate content the user had not yet received.

    Caller holds the same SQLite write transaction as the next user message.
    """
    at = time.time() if at is None else at
    rows = conn.execute('SELECT * FROM chat_delivery WHERE session_id=? AND stopped=0', (sid,)).fetchall()
    for row in rows:
        parts, offsets, count = _state(row, at)
        if count < len(parts):
            kept = parts[:count]
            conn.execute('UPDATE messages SET text=? WHERE id=? AND session_id=?', ('\n\n'.join(kept), row['message_id'], sid))
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_action_proposals'").fetchone():
                conn.execute('DELETE FROM agent_action_proposals WHERE message_id=?', (row['message_id'],))
            conn.execute('UPDATE chat_delivery SET parts=?,offsets=?,stopped=1 WHERE message_id=?',
                         (json.dumps(kept, ensure_ascii=False), json.dumps(offsets[:count]), row['message_id']))
        else:
            conn.execute('UPDATE chat_delivery SET stopped=1 WHERE message_id=?', (row['message_id'],))


def stop_current(conn, sid, message_id, at=None):
    """Stop only the pending reply the caller observed, under its write lock.

    Internal context invalidation may interrupt all delivery rows. A delayed
    client request must never use that broad operation to stop a newer reply.
    """
    if not message_id:
        return {'stopped': False, 'reason': 'message_id_required'}
    latest = conn.execute(
        'SELECT id FROM messages WHERE session_id=? AND suppressed=0 ORDER BY rowid DESC LIMIT 1',
        (sid,)).fetchone()
    if latest is None or latest['id'] != message_id:
        return {'stopped': False, 'reason': 'not_current'}
    row = conn.execute(
        'SELECT * FROM chat_delivery WHERE session_id=? AND message_id=?',
        (sid, message_id)).fetchone()
    if row is None or row['stopped']:
        return {'stopped': False, 'reason': 'not_pending'}
    parts, offsets, count = _state(row, time.time() if at is None else at)
    if count >= len(parts):
        return {'stopped': False, 'reason': 'not_pending'}
    kept = parts[:count]
    conn.execute('UPDATE messages SET text=? WHERE id=? AND session_id=?',
                 ('\n\n'.join(kept), message_id, sid))
    conn.execute('DELETE FROM agent_action_proposals WHERE message_id=? AND session_id=?',
                 (message_id, sid))
    conn.execute('UPDATE chat_delivery SET parts=?,offsets=?,stopped=1 WHERE message_id=? AND session_id=?',
                 (json.dumps(kept, ensure_ascii=False), json.dumps(offsets[:count]), message_id, sid))
    return {'stopped': True, 'reason': 'stopped'}
