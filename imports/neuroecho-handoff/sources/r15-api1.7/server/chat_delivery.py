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


_CLOSERS = frozenset('\"\'\u201d\u2019\u3009\u300b\u300d\u300f\u3011\u3015\u3017\u3019\u301b\uff09\uff3d\u300f\u3010\u3014\u3016\u3018\u301a\u301c\u300d\u300f\u3009\u00bb\u0029\u005d\u007d')
_TERMINAL = frozenset('。！？!?')
_ABBREVIATIONS = frozenset({
    'mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr', 'st', 'vs', 'etc', 'e.g',
    'i.e', 'fig', 'no', 'approx', 'inc', 'jan', 'feb', 'mar', 'apr', 'jun',
    'jul', 'aug', 'sep', 'sept', 'oct', 'nov', 'dec',
})
_STICKER_MARKER = re.compile(r"\[表情[:：]\s*([^\]\r\n]{1,240}?)\s*\]")


def _rich_reply(text):
    """Whether sentence splitting would damage a structured response."""
    if len(text) > 1200 or '```' in text:
        return True
    # Keep markdown headings, lists, block quotes and tables in one response.
    if re.search(r'(?m)^\s*(?:#{1,6}\s|[-*+]\s|>\s|\d+[.、)]\s*)', text):
        return True
    if re.search(r'(?m)^\s*\|.*\|\s*$', text) and '\n' in text:
        return True
    return False


def _period_is_terminal(text, index):
    """Conservatively decide whether an ASCII period ends a sentence."""
    before, after = text[index - 1:index], text[index + 1:index + 2]
    if before.isdigit() and after.isdigit():
        return False
    # A URL/domain or a token such as ``foo.bar`` is not a sentence boundary.
    start = index
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    token = text[start:index + 1]
    if '://' in token or token.lower().startswith(('www.', 'http.')):
        # A URL's internal dots are never boundaries. A trailing dot followed
        # by a new sentence can still be a genuine boundary; keep the URL in
        # the preceding bubble while allowing the next sentence to start.
        if after and after.isspace():
            following = text[index + 1:].lstrip()
            if following and (following[0].isupper() or '\u3400' <= following[0] <= '\u9fff'):
                return True
        return False
    # Common abbreviations (including e.g. and i.e.) should stay intact.
    word_start = index - 1
    while word_start >= 0 and text[word_start].isalpha():
        word_start -= 1
    word = text[word_start + 1:index].lower()
    if word in _ABBREVIATIONS:
        return False
    if text[max(0, index - 3):index].lower() in ('e.g', 'i.e'):
        return False
    if re.search(r'(?:[a-z]\.)+[a-z]$', text[max(0, index - 8):index].lower()):
        return False
    # A period in the middle of an unspaced alphanumeric token is not terminal.
    if before.isalnum() and after.isalnum():
        return False
    # English sentence punctuation normally has a following space. Allow CJK
    # text directly after a period because Chinese/English mixed replies often
    # omit that space.
    if after and not after.isspace() and not ('\u3400' <= after <= '\u9fff'):
        return False
    return True


def _sentence_parts(text):
    """Split short prose at complete sentence boundaries only."""
    parts, start, i, length = [], 0, 0, len(text)
    while i < length:
        char = text[i]
        terminal = char in _TERMINAL or (char == '.' and _period_is_terminal(text, i))
        if not terminal:
            i += 1
            continue
        # Consume repeated punctuation (?!, ...) and closing quotes/brackets so
        # each bubble retains the complete final punctuation.
        end = i + 1
        while end < length and (text[end] in _TERMINAL or text[end] == '.'):
            if text[end] == '.' and not _period_is_terminal(text, end):
                break
            end += 1
        while end < length and text[end] in _CLOSERS:
            end += 1
        piece = text[start:end].strip()
        if piece:
            parts.append(piece)
        start = end
        i = end
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _cap_parts(parts, limit=4):
    if len(parts) <= limit:
        return parts
    sticker_indexes = [index for index, part in enumerate(parts)
                       if _STICKER_MARKER.fullmatch(part.strip())]
    if sticker_indexes:
        sticker_index = sticker_indexes[0]
        # Reserve one complete bubble for the sticker even when sentence or
        # paragraph splitting would otherwise exceed the delivery cap.
        before, after = parts[:sticker_index], parts[sticker_index + 1:]

        def compress(values, slots):
            if not values or slots <= 0:
                return []
            if len(values) <= slots:
                return values
            head = values[:slots - 1]
            head.append(' '.join(values[slots - 1:]))
            return head

        after_slots = 1 if after else 0
        before_slots = max(0, limit - 1 - after_slots)
        return compress(before, before_slots) + [parts[sticker_index]] + compress(after, after_slots)
    # Keep the first three turns natural and append the remainder to the last
    # one, preventing a long response from becoming notification spam.
    return parts[:limit - 1] + [' '.join(parts[limit - 1:])]


def _explicit_parts(text):
    """Split on explicit bubble markers outside fenced code blocks.

    The marker is an internal delivery protocol, so it is removed from the
    delivered text.  A marker inside a fenced code block remains literal and
    must never trigger a split.
    """
    marker = '<!--NX-BUBBLE-->'
    parts, start, cursor, fenced = [], 0, 0, False
    found = False
    while cursor < len(text):
        if text.startswith('```', cursor):
            fenced = not fenced
            cursor += 3
            continue
        if not fenced and text.startswith(marker, cursor):
            found = True
            piece = text[start:cursor].strip()
            if piece:
                parts.append(piece)
            cursor += len(marker)
            start = cursor
            continue
        cursor += 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts if found else None


def _sticker_parts(text):
    """Keep each sticker marker in its own delivery bubble.

    Sticker markers are rendered as images by the clients.  Keeping a marker
    beside prose in the same bubble makes a response that conceptually has a
    text message followed by an image look like one combined message.  Scan
    fences first so an example marker in a code block remains literal.
    """
    matches = []
    cursor, fenced = 0, False
    while cursor < len(text):
        if text.startswith('```', cursor):
            fenced = not fenced
            cursor += 3
            continue
        if not fenced:
            match = _STICKER_MARKER.match(text, cursor)
            if match:
                matches.append((match.start(), match.end()))
                cursor = match.end()
                continue
        cursor += 1
    if not matches:
        return None
    parts, start = [], 0
    for marker_start, marker_end in matches:
        prose = text[start:marker_start].strip()
        if prose:
            parts.append(prose)
        parts.append(text[marker_start:marker_end].strip())
        start = marker_end
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts or [text.strip()]


def _work_parts(text):
    """Backward-compatible work helper; markers are now mode-independent."""
    return _explicit_parts(text) or [str(text or '').strip()]


def split_reply(text, mode='auto'):
    """Return conservative, human-sized delivery bubbles.

    Explicit blank lines are authoritative. Short unstructured prose may also
    split at complete sentence boundaries; rich/technical responses remain
    intact. The result is capped at four bubbles.
    """
    text = str(text or '')
    if not text.strip():
        return []
    explicit = _explicit_parts(text)
    if explicit is not None:
        parts = []
        for part in explicit:
            parts.extend(_sticker_parts(part) or [part])
        return _cap_parts(parts)
    stickers = _sticker_parts(text)
    if stickers is not None:
        return _cap_parts(stickers)
    if mode not in ('auto', 'paragraph', 'sentence'):
        mode = 'auto'
    if _rich_reply(text) or mode == 'paragraph':
        return [text]

    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text.strip()) if p.strip()]
    if len(paragraphs) >= 2:
        if len(paragraphs) > 12 or any(len(p) > 360 for p in paragraphs):
            return [text]
        return _cap_parts([
            '\n\n'.join(paragraphs[i * len(paragraphs) // min(4, len(paragraphs)):
                                      (i + 1) * len(paragraphs) // min(4, len(paragraphs))])
            for i in range(min(4, len(paragraphs)))
        ])

    if mode == 'paragraph':
        return [text]
    if len(text) > 360:
        return [text]
    sentences = _sentence_parts(text)
    if len(sentences) <= 1:
        return [text]
    return _cap_parts(sentences)


def register(conn, sid, mid, text, at=None, mode='companion'):
    parts = split_reply(text, mode=mode)
    if len(parts) < 2 and mode != 'work':
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
