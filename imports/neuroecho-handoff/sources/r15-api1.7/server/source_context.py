"""Persistent, bounded source attachments; callers own SQLite transactions."""
from __future__ import annotations

import hashlib
import json
import uuid

MAX_SOURCES = 8


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def loads(value, fallback=None):
    try:
        result = json.loads(value or '[]')
        return result if isinstance(result, list) else (fallback or [])
    except (TypeError, ValueError):
        return fallback or []


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS source_attachments(
        id TEXT PRIMARY KEY, session_id TEXT NOT NULL, connector_id TEXT NOT NULL,
        label TEXT NOT NULL, source_text TEXT NOT NULL DEFAULT '',
        items TEXT NOT NULL DEFAULT '[]', insights TEXT NOT NULL DEFAULT '[]',
        starters TEXT NOT NULL DEFAULT '[]', stale INTEGER NOT NULL DEFAULT 0,
        legacy INTEGER NOT NULL DEFAULT 0, bookmark_start_rowid INTEGER NOT NULL DEFAULT 0,
        fingerprint TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS source_attachments_session ON source_attachments(session_id)')


def fingerprint(connector_id, label, text, items):
    # The same body under a different title/provider is a distinct source.
    return hashlib.sha256(dumps([connector_id, label, text[:20000], items]).encode()).hexdigest()


def rows(conn, sid):
    return conn.execute('SELECT * FROM source_attachments WHERE session_id=? ORDER BY rowid', (sid,)).fetchall()


def migrate_legacy(conn, timestamp):
    """Represent old sources once without guessing provenance of their memories.

    A revoked flag always wins over residual old text/context. Revocation clears
    compatibility fields, so a later init cannot resurrect an attachment.
    """
    sessions = conn.execute('''SELECT s.* FROM sessions s WHERE s.source_revoked=0
        AND NOT EXISTS(SELECT 1 FROM source_attachments a WHERE a.session_id=s.id)
        AND ((s.mode!='empty' AND COALESCE(s.source_text,'')!='') OR
             EXISTS(SELECT 1 FROM session_context c WHERE c.session_id=s.id))''').fetchall()
    for sess in sessions:
        ctx = conn.execute('SELECT * FROM session_context WHERE session_id=?', (sess['id'],)).fetchone()
        connector = ctx['connector_id'] if ctx else (sess['mode'] or 'paste')
        label, text = sess['source_label'] or '资料', sess['source_text'] or ''
        items, insights, starters = (loads(ctx[key]) if ctx else [] for key in ('items', 'insights', 'starters'))
        attachment = sess['source_attachment_id'] or 'src_' + uuid.uuid4().hex[:12]
        conn.execute('''INSERT OR IGNORE INTO source_attachments
            (id,session_id,connector_id,label,source_text,items,insights,starters,stale,legacy,
             bookmark_start_rowid,fingerprint,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (attachment, sess['id'], connector, label, text[:20000], dumps(items), dumps(insights),
             dumps(starters), int(bool(sess['source_context_stale'])), int(not bool(sess['source_attachment_id'])),
             sess['source_bookmark_start_rowid'], fingerprint(connector, label, text, items),
             sess['created_at'] or timestamp, timestamp))
        sync_compat(conn, sess['id'])


def public(row):
    items = loads(row['items'])
    return {'id': row['id'], 'connector_id': row['connector_id'], 'label': row['label'],
            'title': str(items[0].get('title') or row['label'])[:160] if items else row['label'],
            'items': items, 'insights': loads(row['insights']), 'starters': loads(row['starters']),
            'stale': bool(row['stale']), 'created_at': row['created_at'], 'updated_at': row['updated_at']}


def interleave(sources, field, limit):
    result = []
    for index in range(max((len(s.get(field) or []) for s in sources), default=0)):
        for source in sources:
            values = source.get(field) or []
            if index < len(values):
                value = values[index]
                if field == 'starters':
                    if value not in result:
                        result.append(value)
                else:
                    # Add provenance without changing existing title/summary fields.
                    result.append({**value, 'source_id': source['id'], 'source_label': source['label']})
                if len(result) >= limit:
                    return result
    return result


def aggregate(sources):
    if not sources:
        return None
    single = len(sources) == 1
    return {'connector_id': sources[0]['connector_id'] if single else 'multiple',
            'items': sources[0]['items'] if single else interleave(sources, 'items', 16),
            'insights': sources[0]['insights'] if single else interleave(sources, 'insights', 8),
            'starters': interleave(sources, 'starters', 8), 'sources': sources}


def sync_compat(conn, sid):
    attachments = rows(conn, sid)
    if not attachments:
        conn.execute('DELETE FROM session_context WHERE session_id=?', (sid,))
        conn.execute("UPDATE sessions SET mode='empty',source_label='新对话',source_text='',source_attachment_id=NULL, "
                     "source_bookmark_start_rowid=0,source_context_stale=0 WHERE id=?", (sid,))
        return
    sources = [public(row) for row in attachments]
    context = aggregate(sources)
    sole = attachments[0] if len(attachments) == 1 else None
    conn.execute('INSERT OR REPLACE INTO session_context(session_id,connector_id,items,insights,starters) VALUES(?,?,?,?,?)',
                 (sid, context['connector_id'], dumps(context['items']), dumps(context['insights']), dumps(context['starters'])))
    conn.execute("UPDATE sessions SET source_text=?,source_label=?,source_attachment_id=?,source_bookmark_start_rowid=?, "
                 "source_context_stale=?,source_revoked=0 WHERE id=?",
                 (sole['source_text'] if sole else '', sole['label'] if sole else f'已接入 {len(attachments)} 份资料',
                  sole['id'] if sole else None, sole['bookmark_start_rowid'] if sole else 0,
                  int(all(row['stale'] for row in attachments)), sid))
