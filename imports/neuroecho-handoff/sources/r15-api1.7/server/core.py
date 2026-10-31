"""念响 · PC Web MVP 控制层核心（标准库实现，FastAPI / fallback 共用）。

设计对齐 PRD：
- 显式状态机：会话 / 采集 / 书签 / 记忆
- 设备为合成数据（synthetic），质量不合格时弃权
- 记忆可纠正（版本递增）、可删除、可导出
- 所有动作写审计
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from contextlib import nullcontext
from contextvars import ContextVar
from typing import Callable

from . import agent_runtime, apple_source, chat_delivery, companion_boundary, connection_intro, conversation_changes, faults, feishu_account, followups, proactive_policy, model, moods, mood_operations, plugin_bridge, prompts, source_context
from .conversation_intent import confirmed_preference_mode, requested_response_mode, requested_conversation_style

DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")

# Per-request database override. Unset (the default) means the single
# owner database above, so desktop/local use and the test suite are
# unchanged; the anonymous-visitor middleware sets it per request.
_DB_OVERRIDE: ContextVar[str | None] = ContextVar("nianxiang_db_path", default=None)


def db_path() -> str:
    return _DB_OVERRIDE.get() or DB_PATH


def use_db(path) -> object:
    return _DB_OVERRIDE.set(str(path))


def reset_db(token) -> None:
    _DB_OVERRIDE.reset(token)

SAMPLE_TEXT = (
    "我在做一个面向个人用户的 AI 产品，最近在整理交互原型。"
    "目前卡在「如何让助手记住上下文又不过度打扰」这个问题上。"
    "我倾向于先做一个最小闭环：用户说一件事，助手先复述理解，再给一条下一步。"
    "下周需要把原型给团队看，并准备三分钟演示。"
)

# ---------------- helpers ----------------

def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions(
            id TEXT PRIMARY KEY, created_at TEXT, mode TEXT,
            source_text TEXT, source_label TEXT, state TEXT,
            persona_id TEXT NOT NULL DEFAULT 'nianxiang',
            interaction_mode TEXT NOT NULL DEFAULT 'companion'
        );
        CREATE TABLE IF NOT EXISTS messages(
            id TEXT PRIMARY KEY, session_id TEXT, role TEXT, text TEXT,
            citations TEXT DEFAULT '[]', suggestions TEXT DEFAULT '[]', created_at TEXT,
            persona_id TEXT,
            interaction_mode TEXT
        );
        CREATE TABLE IF NOT EXISTS memories(
            id TEXT PRIMARY KEY, session_id TEXT, kind TEXT, text TEXT,
            status TEXT, version INTEGER, source TEXT,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS session_context(
            session_id TEXT PRIMARY KEY, connector_id TEXT,
            items TEXT DEFAULT '[]', insights TEXT DEFAULT '[]', starters TEXT DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS memory_revisions(
            id TEXT PRIMARY KEY, memory_id TEXT, session_id TEXT, text TEXT,
            status TEXT, version INTEGER, source TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS actions(
            id TEXT PRIMARY KEY, session_id TEXT, kind TEXT, title TEXT, detail TEXT,
            status TEXT, receipt TEXT, real INTEGER DEFAULT 0, when_text TEXT DEFAULT '', created_at TEXT, committed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS bookmarks(
            id TEXT PRIMARY KEY, session_id TEXT, note TEXT, choice TEXT,
            next_step TEXT, status TEXT, receipt TEXT,
            source_memory_id TEXT DEFAULT '', source_version INTEGER DEFAULT 0,
            source_label TEXT DEFAULT '', source_quote TEXT DEFAULT '',
            created_at TEXT, committed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS audit(
            id TEXT PRIMARY KEY, session_id TEXT, action TEXT,
            detail TEXT, reason TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS device(
            id INTEGER PRIMARY KEY CHECK(id = 1), status TEXT, started_at TEXT, seq INTEGER
        );
        CREATE TABLE IF NOT EXISTS app_state(
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO device(id, status, started_at, seq) VALUES(1,'off',NULL,0)"
    )
    chat_delivery.initialize(conn)
    agent_runtime.initialize(conn)
    feishu_account.init_schema(conn)
    connection_intro.init_schema(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
    if "citations" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN citations TEXT DEFAULT '[]'")
    if "suggestions" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN suggestions TEXT DEFAULT '[]'")
    if "suppressed" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN suppressed INTEGER NOT NULL DEFAULT 0")
    sess_cols = [r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()]
    if sess_cols and "persona_id" not in sess_cols:
        # Existing R15 sessions were all generated with the original whale card.
        conn.execute("ALTER TABLE sessions ADD COLUMN persona_id TEXT NOT NULL DEFAULT 'whale'")
    sess_cols = [r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()]
    if sess_cols and "interaction_mode" not in sess_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN interaction_mode TEXT NOT NULL DEFAULT 'companion'")
    msg_cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
    if msg_cols and "persona_id" not in msg_cols:
        conn.execute("ALTER TABLE messages ADD COLUMN persona_id TEXT")
        conn.execute("UPDATE messages SET persona_id='whale' WHERE role='assistant'")
    msg_cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
    if msg_cols and "interaction_mode" not in msg_cols:
        conn.execute("ALTER TABLE messages ADD COLUMN interaction_mode TEXT")
        conn.execute("UPDATE messages SET interaction_mode='companion' WHERE role='assistant'")
    if sess_cols and "response_mode" not in sess_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN response_mode TEXT NOT NULL DEFAULT 'auto'")
    if sess_cols and "conversation_style" not in sess_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN conversation_style TEXT NOT NULL DEFAULT 'warm'")
    if sess_cols and "title" not in sess_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN title TEXT DEFAULT ''")
    if sess_cols and "source_revoked" not in sess_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN source_revoked INTEGER NOT NULL DEFAULT 0")
    if sess_cols and "context_after_message_rowid" not in sess_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN context_after_message_rowid INTEGER NOT NULL DEFAULT 0")
    if sess_cols and "source_context_stale" not in sess_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN source_context_stale INTEGER NOT NULL DEFAULT 0")
    if sess_cols and "source_attachment_id" not in sess_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN source_attachment_id TEXT")
    if sess_cols and "source_bookmark_start_rowid" not in sess_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN source_bookmark_start_rowid INTEGER NOT NULL DEFAULT 0")
    memory_cols = [r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()]
    if memory_cols and "origin_memory_id" not in memory_cols:
        conn.execute("ALTER TABLE memories ADD COLUMN origin_memory_id TEXT")
        # Old copies contain no source ID. Require explicit re-confirmation rather than guessing lineage.
        legacy_sessions = [r[0] for r in conn.execute("SELECT DISTINCT session_id FROM memories "
                                                      "WHERE source='跨会话 · 你确认过'")]
        conn.execute("UPDATE memories SET status='candidate', source='跨会话 · 旧记录，需重新确认' "
                     "WHERE source='跨会话 · 你确认过'")
        _invalidate_history(conn, set(legacy_sessions))
    if memory_cols and "source_message_id" not in memory_cols:
        conn.execute("ALTER TABLE memories ADD COLUMN source_message_id TEXT")
    if memory_cols and "source_attachment_id" not in memory_cols:
        conn.execute("ALTER TABLE memories ADD COLUMN source_attachment_id TEXT")
    bm_cols = [r[1] for r in conn.execute("PRAGMA table_info(bookmarks)").fetchall()]
    for col, ddl in (("source_memory_id", "TEXT DEFAULT ''"), ("source_version", "INTEGER DEFAULT 0"),
                     ("source_label", "TEXT DEFAULT ''"), ("source_quote", "TEXT DEFAULT ''"),
                     ("source_attachment_id", "TEXT DEFAULT ''"),
                     ("recallable", "INTEGER NOT NULL DEFAULT 1")):
        if bm_cols and col not in bm_cols:
            conn.execute(f"ALTER TABLE bookmarks ADD COLUMN {col} {ddl}")
    act_cols = [r[1] for r in conn.execute("PRAGMA table_info(actions)").fetchall()]
    if act_cols and "real" not in act_cols:
        conn.execute("ALTER TABLE actions ADD COLUMN real INTEGER DEFAULT 0")
    if act_cols and "when_text" not in act_cols:
        conn.execute("ALTER TABLE actions ADD COLUMN when_text TEXT DEFAULT ''")
    ctx_cols = [r[1] for r in conn.execute("PRAGMA table_info(session_context)").fetchall()]
    if ctx_cols and "starters" not in ctx_cols:
        conn.execute("ALTER TABLE session_context ADD COLUMN starters TEXT DEFAULT '[]'")
    followups.init_schema(conn)
    proactive_policy.init_schema(conn)
    moods.init_schema(conn)
    mood_operations.init_schema(conn)
    source_context.initialize(conn)
    source_cols = [row[1] for row in conn.execute('PRAGMA table_info(source_attachments)')]
    if 'read_scope' not in source_cols:
        conn.execute("ALTER TABLE source_attachments ADD COLUMN read_scope TEXT NOT NULL DEFAULT '{}'")
    source_context.migrate_legacy(conn, now())
    conversation_changes.init_schema(conn)
    conn.commit()
    conn.close()


def audit(session_id: str | None, action: str, detail: str = "", reason: str = "") -> None:
    conn = get_db()
    conn.execute(
        "INSERT INTO audit(id,session_id,action,detail,reason,created_at) VALUES(?,?,?,?,?,?)",
        (uid("aud"), session_id, action, detail, reason, now()),
    )
    conn.commit()
    conn.close()


# ---------------- understanding ----------------

def _sentences(text: str) -> list[str]:
    raw = []
    buf = ""
    for ch in text.replace("\r", ""):
        if ch in "。！？!?；;\n":
            s = buf.strip()
            if s:
                raw.append(s)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        raw.append(buf.strip())
    return [s for s in raw if len(s) >= 6][:8]


def build_understanding(text: str, mode: str) -> dict:
    """规则版理解卡：事实 / 推测 / 问题 三栏分开（PRD F08/F22）。"""
    if mode == "sample" or not text.strip():
        return {
            "facts": [
                "你正在做面向个人用户的 AI 产品，最近在整理交互原型。",
                "你卡在「记住上下文又不过度打扰」这个问题上。",
                "下周需要给团队看原型，并准备三分钟演示。",
            ],
            "inferences": [
                "你可能更想要一个先理解、再行动的最小闭环，而不是完整功能。",
                "你倾向于用自己的判断做取舍，助手更适合给候选而不是结论。",
            ],
            "questions": ["优先理解哪一部分：交互原型、记忆分寸，还是演示准备？"],
            "source_label": "示例资料",
        }

    sents = _sentences(text)
    facts = sents[:3]
    inferences = []
    for s in sents[3:5]:
        inferences.append(f"看起来：{s}（这是我的推测，等你确认）")
    if not inferences:
        inferences.append("我还不确定你的优先级，需要你补充一句。")
    questions = ["这份资料里，你希望我优先理解哪一部分？"]
    return {
        "facts": facts or ["你给了一段资料，但我还没有提取到稳定事实。"],
        "inferences": inferences,
        "questions": questions,
        "source_label": "你提供的片段",
    }


# ---------------- sessions / messages ----------------

def create_session(mode: str = "sample", text: str = "", source_label: str | None = None,
                   understanding: dict | None = None, greeting: str | None = None,
                   persona_id: str = "nianxiang", interaction_mode: str = "companion") -> dict:
    init_db()
    sid = uid("ses")
    persona_id = prompts.normalize_persona_id(persona_id)
    interaction_mode = str(interaction_mode or '').strip().lower()
    if interaction_mode not in prompts.INTERACTION_MODES:
        raise ValueError('invalid interaction_mode')
    if mode == "empty":
        label = source_label or "新对话"
        src = ""
    else:
        label = source_label or ("示例资料" if mode == "sample" else "你提供的片段")
        src = SAMPLE_TEXT if mode == "sample" else text.strip()
    conn = get_db()
    conn.execute(
        "INSERT INTO sessions(id,created_at,mode,source_text,source_label,state,persona_id,interaction_mode) VALUES(?,?,?,?,?,?,?,?)",
        (sid, now(), mode, src[:20000], label, "listening", persona_id, interaction_mode),
    )
    conn.commit()
    conn.close()
    understanding = understanding or ({"facts": [], "inferences": [], "questions": []}
                                      if mode == "empty" else build_understanding(src, mode))
    for kind, key in (("fact", "facts"), ("inference", "inferences"), ("question", "questions")):
        for item in understanding[key]:
            add_memory(sid, kind, item, source=label, status="candidate")
    conn = get_db()
    conn.execute('BEGIN IMMEDIATE')
    source_context.migrate_legacy(conn, now())
    conn.commit()
    conn.close()
    audit(sid, "session.create", mode, "用户选择开始方式")
    greeting = greeting or ("你好，我是念响。今天想从哪件事开始？"
                            if mode == "empty" else "我在。先不急着安排事情，你想从哪儿说起？")
    add_message(sid, "assistant", greeting)
    return {
        "session": {
            "id": sid,
            "mode": mode,
            "source_label": label,
            "state": "listening",
            "created_at": now(),
            "persona_id": persona_id,
            "interaction_mode": interaction_mode,
        },
        "understanding": understanding,
        "memories": list_memories(sid),
        "messages": get_messages(sid),
    }


def conversation_id() -> str:
    """Choose one persistent conversation per DB, without merging legacy data."""
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        stored = conn.execute("SELECT s.id FROM app_state a JOIN sessions s ON s.id=a.value "
                              "WHERE a.key='canonical_conversation'").fetchone()
        if stored:
            conn.commit()
            return stored["id"]
        chosen = conn.execute("SELECT s.id FROM sessions s JOIN messages m ON m.session_id=s.id "
                              "WHERE COALESCE(s.mode,'empty')<>'sample' AND m.role='user' AND m.suppressed=0 "
                              "GROUP BY s.id ORDER BY MAX(m.rowid) DESC, s.rowid DESC LIMIT 1").fetchone()
        if chosen is None:
            chosen = conn.execute("SELECT id FROM sessions WHERE mode='empty' ORDER BY rowid DESC LIMIT 1").fetchone()
        sid = chosen["id"] if chosen else uid("ses")
        if chosen is None:
            stamp = now()
            conn.execute("INSERT INTO sessions(id,created_at,mode,source_text,source_label,state,persona_id,interaction_mode) VALUES(?,?,'empty','','我们的对话','listening','nianxiang','companion')", (sid, stamp))
            conn.execute("INSERT INTO messages(id,session_id,role,text,created_at,persona_id,interaction_mode) VALUES(?,?,'assistant',?,?,?,?)",
                         (uid("msg"), sid, "你好，我是念响。今天想从哪件事开始？", stamp, "nianxiang", "companion"))
            conn.execute("INSERT INTO audit(id,session_id,action,detail,reason,created_at) VALUES(?,?,'conversation.create','','开始和念响的对话',?)", (uid("aud"), sid, stamp))
        conn.execute("INSERT INTO app_state(key,value) VALUES('canonical_conversation',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (sid,))
        conn.commit()
        return sid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def set_session_context(sid: str, connector_id: str, items: list, insights: list,
                        starters_list: list | None = None) -> None:
    """Compatibility entry for older callers; new reviewed reads use attach."""
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        source_context.migrate_legacy(conn, now())
        sess = conn.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
        if not sess:
            raise LookupError('session not found')
        attached = source_context.rows(conn, sid)
        matching = [row for row in attached if row['connector_id'] == connector_id]
        target = matching[-1] if matching else (attached[0] if len(attached) == 1 and attached[0]['legacy'] else None)
        items, insights, starters_list = items[:16], insights[:8], (starters_list or [])[:8]
        if target:
            conn.execute("UPDATE source_attachments SET read_scope='{}',connector_id=?,items=?,insights=?,starters=?,stale=0,"
                         'fingerprint=?,updated_at=? WHERE id=?',
                         (connector_id, source_context.dumps(items), source_context.dumps(insights),
                          source_context.dumps(starters_list),
                          source_context.fingerprint(connector_id, target['label'], target['source_text'], items),
                          now(), target['id']))
        else:
            if len(attached) >= source_context.MAX_SOURCES:
                raise SourceConflict('一个对话最多接入 8 份资料，请先移除一份。')
            text = sess['source_text'] if not attached else ''
            label = sess['source_label'] if sess['mode'] != 'empty' else (items[0].get('title', '资料') if items else connector_id)
            conn.execute('INSERT INTO source_attachments(id,session_id,connector_id,label,source_text,items,insights,starters,'
                         'stale,legacy,bookmark_start_rowid,fingerprint,created_at,updated_at) '
                         'VALUES(?,?,?,?,?,?,?,?,0,1,0,?,?,?)',
                         (uid('src'), sid, connector_id, label, text or '', source_context.dumps(items),
                          source_context.dumps(insights), source_context.dumps(starters_list),
                          source_context.fingerprint(connector_id, label, text or '', items), now(), now()))
        source_context.sync_compat(conn, sid)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class SourceConflict(ValueError):
    pass


def attach_source_to_empty_session(sid: str, source_label: str, source_text: str,
                                   understanding: dict, items: list, insights: list,
                                   starters: list, connector_id: str = 'feishu', read_scope: dict | None = None) -> list[str]:
    """Append one reviewed source, preserving conversation and other sources.

    The historical function name remains for callers. Each attachment owns only
    its derived cards; user statements and manual memories remain independent.
    """
    return attach_sources_to_session(sid, [{'label': source_label, 'text': source_text,
        'understanding': understanding, 'items': items, 'insights': insights,
        'starters': starters, 'connector_id': connector_id, 'read_scope': read_scope or {}}])


def attach_sources_to_session(sid: str, sources: list[dict]) -> list[str]:
    """Attach a reviewed batch atomically, keeping each source's lineage separate."""
    if not sources:
        raise ValueError('至少需要一份资料。')
    attachment_ids = []
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        source_context.migrate_legacy(conn, now())
        session = conn.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
        if not session:
            raise LookupError('session not found')
        attached = source_context.rows(conn, sid)
        if len(attached) + len(sources) > source_context.MAX_SOURCES:
            raise SourceConflict('一个对话最多接入 8 份资料，请先移除一份。')
        stamps = {row['fingerprint'] for row in attached}
        bookmark_start = conn.execute('SELECT COALESCE(MAX(rowid),0) FROM bookmarks WHERE session_id=?', (sid,)).fetchone()[0]
        for source in sources:
            connector_id, source_label, source_text = source['connector_id'], source['label'], source['text']
            understanding = source['understanding']
            items, insights, starters = source['items'][:16], source['insights'][:8], source['starters'][:8]
            stamp = source_context.fingerprint(connector_id, source_label, source_text, items)
            # Before per-file attachments, one selected file was stored with a
            # synthetic name heading and a generic label. Recognize that exact
            # old one-file shape without guessing how an old batch was split.
            old_single = False
            if connector_id == 'local_files' and len(items) == 1:
                title = items[0].get('title', '')
                for previous in attached:
                    old_items = source_context.loads(previous['items'])
                    if (previous['connector_id'] == 'local_files'
                            and previous['label'] == '本地文件 · 用户选择'
                            and len(old_items) == 1 and isinstance(old_items[0], dict) and old_items[0].get('title') == title
                            and previous['source_text'] == f'【{title}】\n{source_text}'):
                        old_single = True
                        break
            if stamp in stamps or old_single:
                raise SourceConflict('这份资料已经在当前对话或本次选择中，无需重复接入。')
            stamps.add(stamp)
            attachment, ts = uid('src'), now()
            attachment_ids.append(attachment)
            conn.execute('INSERT INTO source_attachments(id,session_id,connector_id,label,source_text,items,insights,starters,'
                         'stale,legacy,bookmark_start_rowid,fingerprint,created_at,updated_at,read_scope) '
                         'VALUES(?,?,?,?,?,?,?,?,0,0,?,?,?,?,?)',
                         (attachment, sid, connector_id, source_label, source_text[:20000], source_context.dumps(items),
                          source_context.dumps(insights), source_context.dumps(starters), bookmark_start, stamp, ts, ts,
                          json.dumps(source.get('read_scope') or {}, ensure_ascii=False)))
            cards = [(kind, text) for kind, key in (('fact','facts'), ('inference','inferences'), ('question','questions'))
                     for text in understanding.get(key, [])]
            cards.extend(('inference', f"洞察（{i['type']}）：{i['title']}——{i['text']}") for i in insights)
            for kind, text in cards:
                mid = uid('mem')
                conn.execute('INSERT INTO memories(id,session_id,kind,text,status,version,source,created_at,updated_at,'
                             'origin_memory_id,source_attachment_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                             (mid, sid, kind, text, 'candidate', 1, source_label, ts, ts, None, attachment))
                conn.execute('INSERT INTO memory_revisions(id,memory_id,session_id,text,status,version,source,created_at) '
                             'VALUES(?,?,?,?,?,?,?,?)', (uid('rev'), mid, sid, text, 'candidate', 1, source_label, ts))
        conn.execute("UPDATE sessions SET mode='connector', source_revoked=0, "
                     "state=CASE WHEN state='revoked' THEN 'listening' ELSE state END WHERE id=?", (sid,))
        source_context.sync_compat(conn, sid)
        conn.execute('INSERT INTO audit(id,session_id,action,detail,reason,created_at) VALUES(?,?,?,?,?,?)',
                     (uid('aud'), sid, 'source.attach', f'{len(sources)} 份 · 用户选择',
                      '用户确认预览后加入现有会话', now()))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return attachment_ids


def list_sources(sid: str) -> list[dict]:
    """Public metadata only; source_text is deliberately not returned."""
    conn = get_db()
    try:
        # A legacy source is created only once even if two surfaces restore
        # the same old conversation at the same time.
        conn.execute('BEGIN IMMEDIATE')
        source_context.migrate_legacy(conn, now())
        result = [source_context.public(row) for row in source_context.rows(conn, sid)]
        conn.commit()
        return result
    finally:
        conn.close()


def get_session_context(sid: str) -> dict | None:
    return source_context.aggregate(list_sources(sid))


def _active_source_context(sid: str) -> dict:
    return source_context.aggregate([source for source in list_sources(sid) if not source['stale']]) or {}


def _source_excerpts(sid: str, query: str) -> list[str]:
    from .document_retrieval import relevant_excerpts
    conn = get_db()
    try:
        rows = conn.execute('SELECT * FROM source_attachments WHERE session_id=? AND stale=0 ORDER BY rowid', (sid,)).fetchall()
    finally:
        conn.close()
    per_source = []
    for row in rows:
        matches = relevant_excerpts(row['source_text'], query, limit=3)
        if matches:
            label = f"[来源：{row['label'][:80]}；资料：{source_context.public(row)['title'][:80]}] "
            per_source.append([label + match[:260] for match in matches])
    # First windows of every relevant source precede any second/third window.
    remaining, bounded = 3200, []
    for index in range(3):
        for matches in per_source:
            if index >= len(matches):
                continue
            if remaining <= 0 or len(bounded) >= 8:
                return bounded
            bounded.append(matches[index][:remaining])
            remaining -= len(bounded[-1])
    return bounded


def get_session(sid: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def set_session_persona(sid: str, persona_id: str) -> dict | None:
    """Persist one of the fixed personas without touching conversation data."""
    persona_id = str(persona_id or '').strip().lower()
    if persona_id not in prompts.PERSONA_PATHS:
        raise ValueError('invalid persona_id')
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
        if not row:
            conn.rollback()
            return None
        if row['persona_id'] != persona_id:
            conn.execute('UPDATE sessions SET persona_id=? WHERE id=?', (persona_id, sid))
            conn.execute('INSERT INTO audit(id,session_id,action,detail,reason,created_at) VALUES(?,?,?,?,?,?)',
                         (uid('aud'), sid, 'session.persona', persona_id, '用户切换对话人格', now()))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_session(sid)


def set_session_mode(sid: str, interaction_mode: str) -> dict | None:
    interaction_mode = str(interaction_mode or '').strip().lower()
    if interaction_mode not in prompts.INTERACTION_MODES:
        raise ValueError('invalid interaction_mode')
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
        if not row:
            conn.rollback()
            return None
        if row['interaction_mode'] != interaction_mode:
            conn.execute('UPDATE sessions SET interaction_mode=? WHERE id=?', (interaction_mode, sid))
            conn.execute('INSERT INTO audit(id,session_id,action,detail,reason,created_at) VALUES(?,?,?,?,?,?)',
                         (uid('aud'), sid, 'session.mode', interaction_mode, '用户切换互动模式', now()))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_session(sid)


def set_session_state(sid: str, state: str) -> None:
    conn = get_db()
    conn.execute("UPDATE sessions SET state=? WHERE id=?", (state, sid))
    conn.commit()
    conn.close()


def add_message(sid: str, role: str, text: str, citations: list | None = None,
                suggestions: list | None = None, *, time_zone: str | None = None) -> dict:
    conn = get_db()
    mid = uid("msg")
    cites = citations or []
    sugg = suggestions or []
    try:
        if role == "user":
            conn.execute("BEGIN IMMEDIATE")
            chat_delivery.interrupt(conn, sid)
            connection_intro.cancel_for_user(conn, sid)
        persona_id = None
        interaction_mode = None
        if role == "assistant":
            row = conn.execute("SELECT persona_id FROM sessions WHERE id=?", (sid,)).fetchone()
            persona_id = prompts.normalize_persona_id(row[0] if row else None)
            mode_row = conn.execute("SELECT interaction_mode FROM sessions WHERE id=?", (sid,)).fetchone()
            interaction_mode = prompts.normalize_interaction_mode(mode_row[0] if mode_row else None)
        conn.execute(
            "INSERT INTO messages(id,session_id,role,text,citations,suggestions,created_at,persona_id,interaction_mode) VALUES(?,?,?,?,?,?,?,?,?)",
            (mid, sid, role, text, json.dumps(cites, ensure_ascii=False), json.dumps(sugg, ensure_ascii=False), now(), persona_id, interaction_mode),
        )
        boundary_control = companion_boundary.apply_user_control(conn,sid,text,time_zone=time_zone) if role == "user" else None
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"id": mid, "role": role, "text": text, "citations": cites, "suggestions": sugg, "created_at": now(), **({"companion_boundary":boundary_control} if boundary_control else {})}


def get_messages(sid: str) -> list[dict]:
    conn = get_db()
    conn.execute('BEGIN')
    rows = conn.execute(
        "SELECT id,role,text,citations,suggestions,created_at,persona_id,interaction_mode FROM messages WHERE session_id=? AND suppressed=0 ORDER BY rowid",
        (sid,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["citations"] = json.loads(d.get("citations") or "[]")
        except Exception:
            d["citations"] = []
        try:
            d["suggestions"] = json.loads(d.get("suggestions") or "[]")
        except Exception:
            d["suggestions"] = []
        out.append(d)
    chat_delivery.annotate(conn, sid, out)
    intro_messages = {row['message_id']: row for row in conn.execute(
        'SELECT id,source_id,message_id,scope FROM connection_intro_jobs WHERE session_id=? AND message_id IS NOT NULL', (sid,))}
    for message in out:
        if message['id'] in intro_messages:
            intro_row = intro_messages[message['id']]
            message['connection_intro'] = {'id': intro_row['id'], 'source_id': intro_row['source_id'],
                                           'scope': json.loads(intro_row['scope'] or '{}')}
    proposals = agent_runtime.attach_proposals(conn, sid, out, agent_runtime.context_stamp(conn, sid))
    for message in out:
        if message["id"] in proposals:
            message["action_proposal"] = proposals[message["id"]]
    conn.close()
    return out


def stop_message_delivery(sid: str, message_id: str | None = None) -> dict | None:
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone():
            conn.rollback()
            return None
        result = chat_delivery.stop_current(conn, sid, message_id)
        conn.commit()
        return {'ok': True, 'message_id': message_id, **result}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------- memories ----------------

REVOKE_REVIEW_PREFIX = "撤回后来源待核对（暂不用于回复） · "

def add_memory(sid: str, kind: str, text: str, source: str = "", status: str = "candidate",
               origin_memory_id: str | None = None) -> dict:
    conn = get_db()
    mid = uid("mem")
    ts = now()
    conn.execute(
        "INSERT INTO memories(id,session_id,kind,text,status,version,source,created_at,updated_at,origin_memory_id) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (mid, sid, kind, text, status, 1, source, ts, ts, origin_memory_id),
    )
    conn.execute(
        "INSERT INTO memory_revisions(id,memory_id,session_id,text,status,version,source,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (uid("rev"), mid, sid, text, status, 1, source, ts),
    )
    conn.commit()
    conn.close()
    audit(sid, "memory.add", f"{kind}:{text[:60]}", source)
    return {"id": mid, "kind": kind, "text": text, "status": status, "version": 1, "source": source}


def list_memories(sid: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT id,kind,text,status,version,source,created_at,updated_at,origin_memory_id,source_message_id,source_attachment_id "
        "FROM memories WHERE session_id=? ORDER BY created_at",
        (sid,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _lineage_rows(conn: sqlite3.Connection, mid: str) -> list[sqlite3.Row]:
    return conn.execute(
        "WITH RECURSIVE linked(id) AS (SELECT id FROM memories WHERE id=? UNION "
        "SELECT m.id FROM memories m JOIN linked l ON m.origin_memory_id=l.id) "
        "SELECT m.* FROM memories m JOIN linked l ON m.id=l.id", (mid,)
    ).fetchall()


def _invalidate_history(conn: sqlite3.Connection, session_ids: set[str]) -> None:
    for sid in session_ids:
        # Never reveal queued segments generated from context that was just changed.
        chat_delivery.interrupt(conn, sid)
        conn.execute("UPDATE sessions SET context_after_message_rowid="
                     "(SELECT COALESCE(MAX(rowid),0) FROM messages WHERE session_id=?) WHERE id=?", (sid, sid))


def _mark_memory_sources_stale(conn: sqlite3.Connection, memories: list) -> None:
    """Invalidate only the attributable source, never unrelated fresh sources."""
    personal = ('用户手动添加', '对话中用户要求', '对话原话 · 用户选存', '对话原话 · 用户纠正')
    touched = set()
    for memory in memories:
        attachment = memory['source_attachment_id']
        targets = []
        if attachment:
            targets = conn.execute('SELECT id,session_id FROM source_attachments WHERE id=?', (attachment,)).fetchall()
        elif memory['source'] not in personal and not (memory['source'] or '').startswith('跨会话 · '):
            # Old cards lack provenance. Preserve their previous conservative
            # behavior, limited to legacy attachments instead of all new sources.
            targets = conn.execute('SELECT id,session_id FROM source_attachments WHERE session_id=? AND legacy=1',
                                   (memory['session_id'],)).fetchall()
        for target in targets:
            conn.execute('UPDATE source_attachments SET stale=1,updated_at=? WHERE id=?', (now(), target['id']))
            touched.add(target['session_id'])
    for sid in touched:
        source_context.sync_compat(conn, sid)


def _delete_lineages(conn: sqlite3.Connection, ids: list[str]) -> None:
    linked = {row['id']: row for mid in ids for row in _lineage_rows(conn, mid)}
    _invalidate_history(conn, {row['session_id'] for row in linked.values()})
    _mark_memory_sources_stale(conn, list(linked.values()))
    for mid in linked:
        conn.execute("DELETE FROM memory_revisions WHERE memory_id=?", (mid,))
        conn.execute("DELETE FROM memories WHERE id=?", (mid,))


class MemoryVersionConflict(ValueError):
    """An optional client version no longer matches the transaction's current row."""
    def __init__(self, expected_version: int, current_version: int):
        super().__init__('这条记忆已在另一处更新。你的修改尚未保存，请刷新并核对最新版本；原草稿可以保留。')
        self.expected_version = expected_version
        self.current_version = current_version


def _check_memory_version(row, expected_version: int | None) -> None:
    if expected_version is None:
        return  # Legacy clients retain their existing behavior.
    if type(expected_version) is not int or expected_version < 1:
        raise ValueError('expected_version 必须是正整数。')
    if row['version'] != expected_version:
        raise MemoryVersionConflict(expected_version, row['version'])


def update_memory(mid: str, text: str | None = None, status: str | None = None,
                  expected_version: int | None = None) -> dict | None:
    conn = get_db()
    try:
        # Serialize the read/version check and every dependent change. A conflict
        # must not invalidate model context, mutate lineages or append history.
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute("SELECT * FROM memories WHERE id=?", (mid,)).fetchone()
        if not row:
            return None
        _check_memory_version(row, expected_version)
        new_text = text if text is not None else row["text"]
        new_status = status if status is not None else row["status"]
        linked = _lineage_rows(conn, mid)
        # A newly confirmed/corrected explicit personal preference is a newer
        # user choice than a previously selected conversation mode.
        personal_sources = ('对话中用户要求', '用户手动添加', '对话原话 · 用户选存', '对话原话 · 用户纠正', '跨会话 · 用户重新确认')
        if (new_status == 'confirmed' and row['kind'] == 'fact' and row['source'] in personal_sources
                and confirmed_preference_mode(new_text)
                and (new_text != row['text'] or row['status'] != 'confirmed')):
            conn.execute("UPDATE sessions SET response_mode='auto' WHERE id=?", (row['session_id'],))
        _invalidate_history(conn, {item['session_id'] for item in linked})
        # Source items and derived insights have no fine-grained provenance linking
        # them to memory cards. A text correction can contradict any of them, so
        # keep the original visible for review but stop sending it to the model.
        if text is not None and text != row['text']:
            _mark_memory_sources_stale(conn, linked)
        for item in linked:
            item_source = item['source']
            if item['id'] == mid and text is not None and text != row['text'] and item_source == '对话原话 · 用户选存':
                item_source = '对话原话 · 用户纠正'
            if item['id'] == mid and (item_source or '').startswith(REVOKE_REVIEW_PREFIX) and (text is not None or status == 'confirmed'):
                item_source = '用户重新确认 · ' + item_source[len(REVOKE_REVIEW_PREFIX):]
            if item['id'] == mid and item_source == '跨会话 · 旧记录，需重新确认' and new_status == 'confirmed':
                item_source = '跨会话 · 用户重新确认'
            detach = item['id'] == mid and (text is not None or (status is not None and status != row['status']))
            item_status = 'candidate' if item['id'] != mid and (item_source or '').startswith(REVOKE_REVIEW_PREFIX) else new_status
            conn.execute("UPDATE memories SET text=?,status=?,source=?,version=version+1,updated_at=?, "
                         "origin_memory_id=CASE WHEN ? THEN NULL ELSE origin_memory_id END WHERE id=?",
                         (new_text, item_status, item_source, now(), detach, item['id']))
            conn.execute("INSERT INTO memory_revisions(id,memory_id,session_id,text,status,version,source,created_at) "
                         "VALUES(?,?,?,?,?,?,?,?)", (uid('rev'), item['id'], item['session_id'], new_text,
                         item_status, item['version']+1, item_source, now()))
        out = conn.execute("SELECT * FROM memories WHERE id=?", (mid,)).fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    audit(row["session_id"], "memory.correct", f"{mid} v{out['version']}", "用户纠正/确认")
    return dict(out)


def delete_memory(mid: str, expected_version: int | None = None) -> bool:
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute("SELECT session_id,version FROM memories WHERE id=?", (mid,)).fetchone()
        if not row:
            return False
        _check_memory_version(row, expected_version)
        _delete_lineages(conn, [mid])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    audit(row["session_id"], "memory.delete", mid, "用户删除")
    return True


def memory_history(mid: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT id,text,status,version,source,created_at FROM memory_revisions "
        "WHERE memory_id=? ORDER BY version", (mid,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def export_data(sid: str | None = None) -> dict:
    conn = get_db()
    q = "SELECT * FROM {}"
    args = ()
    where = ""
    if sid:
        where = " WHERE session_id=?"
        args = (sid,)
    out = {}
    for table in ("sessions", "messages", "memories", "memory_revisions", "bookmarks", "audit", "source_attachments", "followups", "followup_notification_settings", "followup_notification_attempts", "companion_boundary", "mood_entries", "mood_operations"):
        key = "id" if table == "sessions" else "session_id"
        sql = q.format(table) + (f" WHERE {key}=?" if sid else "")
        out[table] = [dict(r) for r in conn.execute(sql, args if sid else ()).fetchall()]
    conn.close()
    return out


# ---------------- bookmarks ----------------

def create_bookmark(sid: str, note: str, choice: str, next_step: str,
                    source_memory_id: str = "", source_version: int = 0,
                    source_label: str = "", source_quote: str = "", source_attachment_id: str = "") -> dict:
    conn = get_db()
    conn.execute('BEGIN IMMEDIATE')
    if not conn.execute('SELECT 1 FROM sessions WHERE id=?', (sid,)).fetchone():
        conn.close()
        raise LookupError('session not found')
    memory = conn.execute('SELECT source_attachment_id FROM memories WHERE id=? AND session_id=?',
                          (source_memory_id, sid)).fetchone() if source_memory_id else None
    inferred = (memory['source_attachment_id'] or '') if memory else ''
    if source_attachment_id and inferred and source_attachment_id != inferred:
        conn.close()
        raise ValueError('书签来源与记忆来源不一致。')
    source_attachment_id = source_attachment_id or inferred
    if source_attachment_id and not conn.execute('SELECT 1 FROM source_attachments WHERE id=? AND session_id=?',
                                                 (source_attachment_id, sid)).fetchone():
        conn.close()
        raise ValueError('书签来源不属于当前会话，或已被移除。')
    bid = uid("bmk")
    conn.execute(
        "INSERT INTO bookmarks(id,session_id,note,choice,next_step,status,receipt,"
        "source_memory_id,source_version,source_label,source_quote,source_attachment_id,created_at,committed_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
        (bid, sid, note, choice, next_step, "draft", "",
         source_memory_id, int(source_version or 0), source_label, source_quote, source_attachment_id, now()),
    )
    conn.commit()
    conn.close()
    audit(sid, "bookmark.draft", bid, "保存工作书签草稿")
    return {"id": bid, "status": "draft", "note": note, "choice": choice, "next_step": next_step,
            "source_memory_id": source_memory_id, "source_version": int(source_version or 0),
            "source_label": source_label, "source_quote": source_quote, "source_attachment_id": source_attachment_id}


def commit_bookmark(bid: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM bookmarks WHERE id=?", (bid,)).fetchone()
    if not row:
        conn.close()
        return None
    receipt = f"stored:{hashlib.sha256((bid+now()).encode()).hexdigest()[:12]}"
    conn.execute(
        "UPDATE bookmarks SET status='committed', receipt=?, committed_at=? WHERE id=?",
        (receipt, now(), bid),
    )
    conn.commit()
    out = conn.execute("SELECT * FROM bookmarks WHERE id=?", (bid,)).fetchone()
    conn.close()
    audit(row["session_id"], "bookmark.commit", f"{bid} {receipt}", "用户确认保存")
    return dict(out)


def latest_bookmark(sid: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM bookmarks WHERE session_id=? AND recallable=1 ORDER BY rowid DESC LIMIT 1", (sid,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------- device ----------------

THRESHOLDS = {"quality_min": 0.55}
CHAT_BUDGET = 40
CHAT_BUDGET_WINDOW_MINUTES = 60


class BudgetExceeded(RuntimeError):
    """当前对话的滚动时间窗口预算用尽，原消息继续保留。"""


def _chat_budget_used(sid: str) -> int:
    """Count completed turns in (UTC now minus 60 minutes, UTC now].

    SQLite's julianday normalizes existing ISO timestamps with Z or explicit
    offsets, including legacy timezone-less UTC values. Keep all history intact.
    """
    current = datetime.fromisoformat(now().replace("Z", "+00:00"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    cutoff = current - timedelta(minutes=CHAT_BUDGET_WINDOW_MINUTES)
    conn = get_db()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM audit WHERE session_id=? AND action='chat.turn' "
            "AND julianday(created_at)>julianday(?) AND julianday(created_at)<=julianday(?)",
            (sid, cutoff.isoformat(), current.isoformat()),
        ).fetchone()[0]
    finally:
        conn.close()


def device_state() -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM device WHERE id=1").fetchone()
    conn.close()
    return {"status": row["status"], "started_at": row["started_at"], "seq": row["seq"]}


def device_start() -> dict:
    conn = get_db()
    conn.execute("UPDATE device SET status='on', started_at=? WHERE id=1", (now(),))
    conn.commit()
    conn.close()
    audit(None, "device.start", "synthetic", "用户单次采集授权")
    return device_state()


def device_stop() -> dict:
    conn = get_db()
    conn.execute("UPDATE device SET status='off', started_at=NULL WHERE id=1")
    conn.commit()
    conn.close()
    audit(None, "device.stop", "synthetic", "用户停止采集")
    return device_state()


def device_frame() -> dict:
    st = device_state()
    if faults.active("device_stall"):
        audit(None, "device.stall", "injected", "故障演练：设备断流")
        return {"status": "stalled", "source": "synthetic", "abstain": True,
                "reason": "设备断流（演练），状态未知"}
    if st["status"] != "on":
        return {"status": "off", "source": "synthetic", "abstain": True,
                "reason": "采集未开启"}
    conn = get_db()
    seq = (st["seq"] or 0) + 1
    conn.execute("UPDATE device SET seq=? WHERE id=1", (seq,))
    conn.commit()
    conn.close()
    quality = round(random.uniform(0.35, 0.95), 2)
    abstain = quality < THRESHOLDS["quality_min"]
    if abstain:
        audit(None, "device.abstain", f"quality={quality}", "信号质量低于阈值，弃权")
    frame = {
        "status": "on",
        "source": "synthetic",
        "model": "RSC-64RS-demo",
        "ts": now(),
        "seq": seq,
        "quality": quality,
        "algo_version": "demo-0.4",
        "abstain": abstain,
        "reason": "信号质量低于阈值，本轮不更新状态" if abstain else "ok",
        "bands": {"theta": round(random.uniform(0.2, 0.8), 2),
                  "alpha": round(random.uniform(0.3, 0.9), 2)},
    }
    return frame


# ---------------- chat ----------------

def _available_memories(sid: str) -> list[dict]:
    sources = list_sources(sid)
    stale_ids = {source['id'] for source in sources if source['stale']}
    conn = get_db()
    legacy_stale = bool(conn.execute('SELECT 1 FROM source_attachments WHERE session_id=? AND legacy=1 AND stale=1',
                                    (sid,)).fetchone())
    corrected = {r[0] for r in conn.execute(
        "SELECT m.id FROM memories m JOIN memory_revisions r ON r.memory_id=m.id AND r.version=1 "
        "WHERE m.session_id=? AND m.text!=r.text", (sid,)).fetchall()}
    conn.close()
    personal = ('对话中用户要求', '用户手动添加', '对话原话 · 用户选存', '对话原话 · 用户纠正')
    result = []
    for memory in list_memories(sid):
        if memory['status'] not in ('candidate', 'confirmed') or (memory['source'] or '').startswith(REVOKE_REVIEW_PREFIX):
            continue
        if memory['source'] == '跨会话 · 旧记录，需重新确认' and memory['status'] != 'confirmed':
            continue
        affected = memory['source_attachment_id'] in stale_ids or (
            memory['source_attachment_id'] is None and legacy_stale and memory['source'] not in personal)
        if affected and memory['status'] != 'confirmed' and memory['id'] not in corrected and memory['source'] not in personal:
            continue
        result.append(memory)
    return result


def _memory_digest(sid: str) -> list[str]:
    return [memory['text'] for memory in _available_memories(sid)][:4]


def _memory_groups(sid: str, query: str | None = None) -> tuple[list[str], list[str], list[str], list[str]]:
    mems = _available_memories(sid)
    if query is not None:
        from .memory_retrieval import relevant_memories, user_declines_recall
        selected = relevant_memories(mems, query)
        # A verified conversation preference applies to every response, unlike
        # biographical facts. Only exact personal preferences participate; do
        # not silently choose a side if confirmed preferences conflict.
        personal = {'对话中用户要求', '用户手动添加', '对话原话 · 用户选存', '对话原话 · 用户纠正', '跨会话 · 用户重新确认'}
        preferences = [m for m in mems if m['status'] == 'confirmed' and m['kind'] == 'fact'
                       and m['source'] in personal and confirmed_preference_mode(m['text'])]
        modes = {confirmed_preference_mode(m['text']) for m in preferences}
        if len(modes) == 1 and not user_declines_recall(query):
            selected_ids = {m['id'] for m in selected}
            selected += [m for m in preferences if m['id'] not in selected_ids]
        mems = selected
    facts = [m["text"] for m in mems if m["kind"] in ("fact", "inference") and m["status"] == "confirmed"]
    candidates = [m["text"] for m in mems if m["kind"] == "fact" and m["status"] != "confirmed"
                  and not m["source"].startswith("对话原话 · 用户")]
    inferences = [m["text"] for m in mems if m["kind"] == "inference" and m["status"] != "confirmed"]
    questions = [m["text"] for m in mems if m["kind"] == "question"]
    return facts, inferences, questions, candidates


def _confirmed_preference_mode(sid: str) -> str | None:
    """Use unanimous explicit preferences only; conflicting cards stay unresolved."""
    personal = {'对话中用户要求', '用户手动添加', '对话原话 · 用户选存', '对话原话 · 用户纠正',
                '跨会话 · 用户重新确认'}
    modes = {mode for m in _available_memories(sid)
             if m['status'] == 'confirmed' and m['kind'] == 'fact' and m['source'] in personal
             and (mode := confirmed_preference_mode(m['text']))}
    return next(iter(modes)) if len(modes) == 1 else None


def _effective_response_mode(sid: str, session: dict | None = None) -> tuple[str, bool]:
    """Explicit session control wins; confirmed preference is the default."""
    session_mode = (session or get_session(sid) or {}).get('response_mode', 'auto')
    if session_mode != 'auto':
        return session_mode, False
    preference = _confirmed_preference_mode(sid)
    return (preference, True) if preference else ('auto', False)


def _citations(sid: str, limit: int = 3) -> list[dict]:
    mems = _available_memories(sid)
    confirmed = [m for m in mems if m["status"] == "confirmed"]
    chosen = (confirmed or mems)[:limit]
    return [{"id": m["id"], "text": m["text"][:60], "version": m["version"],
             "status": m["status"]} for m in chosen]


def confirmed_facts(sid: str) -> list[dict]:
    return [m for m in list_memories(sid) if m.get("status") == "confirmed" and m.get("kind") == "fact"]


def _capability_reply(sid: str, text: str) -> str | None:
    ctx = get_session_context(sid) or {}
    name = (ctx.get("connector_id") or "").strip()
    if any(k in text for k in ("你能做什么", "会什么", "能帮我做什么", "有什么功能")):
        src = f"你这次接了「{name}」，" if name else ""
        return ("我不替你决定。能做的：读你授权的真实来源（飞书/Notion/Gmail/本地代码/Apple）；"
                f"把今天收成一张可改的卡；记住你确认过的，纠正后按新版本；经你批准做提醒/日历/草稿。{src}"
                "现在想从哪件开始？")
    if "先听我说" in text:
        return "好，我先听你说，不急着给建议。"
    if any(k in text for k in ("随便聊", "聊聊")):
        return "好啊，我在。你想从哪里说起？"
    return None


def _is_command(text: str) -> bool:
    s = text.strip().strip("。.!！?？ ")
    if s in ("安静", "安静一会儿", "停下", "不用了", "别说了",
             "继续上次", "回到上次", "上次的书签", "回到书签", "别安排", "不用提醒", "不用提醒我"):
        return True
    if _memory_request(text) is not None:
        return True
    return False


def _memory_request(text: str) -> tuple[str, str] | None:
    """Recognize an explicit opening command and an independently marked request.

    This deliberately does not infer intent from ordinary mentions of 记住.
    Complex, unmarked compound sentences remain a single candidate for review.
    """
    opening = re.match(r'^(?:(?:请你|请)?(?:帮我)?记住)', text.strip())
    if opening is None:
        return None
    rest = text.strip()[opening.end():].lstrip('：:，, \t')
    # Only remove the explicitly delimited command label, not part of a fact
    # such as “这句话让我开心”. Quoted/forwarded opening text never matched.
    rest = re.sub(r'^(?:这一句(?:话)?|这句(?:话)?)\s*[：:]\s*', '', rest)
    first_clause = re.split(r'[,，。.;；!！\r\n]', rest, maxsplit=1)[0]
    if any(mark in first_clause for mark in ('?', '？')) or rest.startswith(('是什么意思', '是什么', '怎么用', '的意思')):
        return None
    followup = re.search(r'(?:也|并|还|再|然后|同时)帮我(?=\s*\S)', rest)
    if followup:
        fact = rest[:followup.start()].strip(' ：:，,。；; \t\n')
        request = rest[followup.start():].strip()
        return fact, request
    return rest.strip(' ：:，,。；; \t\n'), ''


def _remember_candidate_once(sid: str, fact: str) -> str:
    """Atomically reuse an exact, still-existing user-requested memory.

    This prevents duplicate cards on a repeat request, but does not make an
    entire chat turn idempotent: a repeat can still create another dialogue.
    """
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        found = conn.execute(
            "SELECT status FROM memories WHERE session_id=? AND kind='fact' AND text=? "
            "AND source='对话中用户要求' AND status IN ('candidate','confirmed') LIMIT 1", (sid, fact)
        ).fetchone()
        if found:
            conn.commit()
            return found['status']
        mid, ts = uid('mem'), now()
        conn.execute(
            "INSERT INTO memories(id,session_id,kind,text,status,version,source,created_at,updated_at,origin_memory_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (mid, sid, 'fact', fact, 'candidate', 1, '对话中用户要求', ts, ts, None))
        conn.execute(
            "INSERT INTO memory_revisions(id,memory_id,session_id,text,status,version,source,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (uid('rev'), mid, sid, fact, 'candidate', 1, '对话中用户要求', ts))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    audit(sid, 'memory.add', f'fact:{fact[:60]}', '对话中用户要求')
    return 'new'


def memory_proposal(text: str) -> str | None:
    """Suggest only a small allowlist of whole user sentences; never infer.

    The allowlist intentionally misses most preferences. It cannot establish
    that an otherwise allowed preference is not sensitive in a wider context.
    """
    quote = text.strip().rstrip('。')
    companion_preferences = {
        '我不喜欢被催', '我不喜欢被催促', '我不喜欢被打断',
        '我希望你先听我说', '我希望你先听我说完',
        '我不希望你马上给建议', '我不希望你立刻给建议',
    }
    if quote in companion_preferences:
        return quote
    pattern = r'我(?:一直|平时|通常)(?:更喜欢|喜欢|偏好|习惯)(.+)'
    match = re.fullmatch(pattern, quote)
    allowed = {
        '喝红茶', '喝绿茶', '喝茶', '喝咖啡', '喝水', '喝温水',
        '红茶', '绿茶', '茶', '咖啡', '温水',
        '吃米饭', '吃面条', '散步', '跑步', '听音乐', '看书', '阅读',
        '早睡', '早起', '晚睡', '晚起',
    }
    return quote if match and match.group(1) in allowed else None


def propose_from_message(sid: str, message_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT text FROM messages WHERE id=? AND session_id=? AND role='user'", (message_id, sid)).fetchone()
    if not row:
        conn.close()
        return None
    quote = memory_proposal(row['text'])
    exists = quote and conn.execute(
        "SELECT 1 FROM memories WHERE session_id=? AND text=? AND kind='fact' "
        "AND source='对话原话 · 用户选存' AND source_message_id IS NOT NULL LIMIT 1", (sid, quote)).fetchone()
    conn.close()
    return {'message_id': message_id, 'quote': quote} if quote and not exists else None


def save_proposed_memory(sid: str, message_id: str, *, confirm: bool = False) -> dict:
    """Save a verified literal quote; an explicit one-click choice may confirm it.

    Legacy callers still create candidates. Never reuse a same-text document or
    manual memory: its provenance and revocation dependencies are different.
    """
    if not isinstance(confirm, bool):
        raise ValueError('confirm 必须是布尔值。')
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute("SELECT text FROM messages WHERE id=? AND session_id=? AND role='user'", (message_id, sid)).fetchone()
        quote = memory_proposal(row['text']) if row else None
        if not quote:
            raise ValueError('来源不存在，或这句话不适合做记忆提议。')
        existing = conn.execute(
            "SELECT * FROM memories WHERE session_id=? AND source_message_id=? "
            "AND source IN ('对话原话 · 用户选存','对话原话 · 用户纠正') ORDER BY created_at LIMIT 1",
            (sid, message_id)).fetchone()
        created, confirmed_now = False, False
        if existing:
            if (existing['kind'] != 'fact' or existing['text'] != quote
                    or existing['source'] != '对话原话 · 用户选存'
                    or existing['source_attachment_id'] is not None
                    or existing['origin_memory_id'] is not None):
                raise ValueError('这句记忆已被修改，请到记忆中查看；不会覆盖你的修改。')
            mid = existing['id']
            if confirm and existing['status'] == 'candidate':
                ts, version = now(), existing['version'] + 1
                conn.execute("UPDATE memories SET status='confirmed',version=?,updated_at=? WHERE id=?",
                             (version, ts, mid))
                conn.execute("INSERT INTO memory_revisions(id,memory_id,session_id,text,status,version,source,created_at) VALUES(?,?,?,?,?,?,?,?)",
                             (uid('rev'), mid, sid, quote, 'confirmed', version, '对话原话 · 用户选存', ts))
                confirmed_now = True
        else:
            mid, ts = uid('mem'), now()
            status = 'confirmed' if confirm else 'candidate'
            conn.execute("INSERT INTO memories(id,session_id,kind,text,status,version,source,created_at,updated_at,source_message_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (mid, sid, 'fact', quote, status, 1, '对话原话 · 用户选存', ts, ts, message_id))
            conn.execute("INSERT INTO memory_revisions(id,memory_id,session_id,text,status,version,source,created_at) VALUES(?,?,?,?,?,?,?,?)",
                         (uid('rev'), mid, sid, quote, status, 1, '对话原话 · 用户选存', ts))
            created, confirmed_now = True, confirm
        if confirmed_now and confirmed_preference_mode(quote):
            conn.execute("UPDATE sessions SET response_mode='auto' WHERE id=?", (sid,))
        conn.commit()
        result = dict(conn.execute('SELECT * FROM memories WHERE id=?', (mid,)).fetchone())
        result.update(created=created, confirmed_now=confirmed_now)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return result


def _suggestions(sid: str, text: str) -> list[str]:
    ctx = get_session_context(sid) or {}
    base = ctx.get("starters") or ["我该先做什么？", "帮我记住这一点"]
    out = [s for s in base if s and s not in text]
    return out[:2]


def _grounded_reply(sid: str, text: str) -> str | None:
    ctx = _active_source_context(sid)
    if not ctx:
        return None
    items = ctx.get("items") or []
    insights = ctx.get("insights") or []
    sess = get_session(sid) or {}
    name = (sess.get("source_label") or "").split(" · ")[0] or ctx.get("connector_id") or "来源"
    # Never use connector-specific canned claims: they may describe a different user's data.
    first = items[0]["title"] if items else "最近的一条记录"
    top = insights[0] if insights else None

    if any(k in text for k in ("下一步", "怎么办", "建议", "先做", "优先", "这周")):
        if top:
            opp = next((i for i in insights if i.get("type") == "opportunity"), None)
            candidate = f"{opp['title']}——{opp['text']}" if opp else top["text"]
            return (f"结合你在{name}里的「{first}」，和洞察「{top['title']}」：{top['text']} "
                    f"候选下一步：{candidate} 要把它存成书签吗？")
        return f"我先只基于{name}里读到的「{first}」给一个候选：把它拆成一个小动作，今天能完成的那种。"
    if any(k in text for k in ("为什么", "依据", "根据", "来源")):
        return (f"这条判断来自{name}的 {len(items)} 条读取（如「{first}」）和 {len(insights)} 条洞察；"
                "标了「推测」的部分还不是结论，你可以改或删。")
    if any(k in text for k in ("哪件", "先聊", "聊什么")):
        return f"我在{name}里看到：{'；'.join(i['title'] for i in items[:3])}。你想先聊哪一件？"
    return None


def _model_context_stamp(sid: str, conn: sqlite3.Connection | None = None) -> str:
    """Hash the same context under a read snapshot or the final write transaction."""
    owned = conn is None
    if owned:
        list_sources(sid)  # Finish one-time legacy migration before the read snapshot.
        conn = get_db()
        conn.execute('BEGIN')
    try:
        session = conn.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
        memories = [dict(row) for row in conn.execute('SELECT * FROM memories WHERE session_id=? ORDER BY id', (sid,))]
        sources = []
        for row in conn.execute('SELECT * FROM source_attachments WHERE session_id=? ORDER BY id', (sid,)):
            item = dict(row)
            item['source_text'] = hashlib.sha256((item['source_text'] or '').encode()).hexdigest()
            sources.append(item)
        snapshot = {'session':dict(session) if session else None,'memories':memories,'sources':sources,
                    'feishu_account':feishu_account.snapshot(conn, sid),
                    'boundary':companion_boundary.public(companion_boundary.snapshot(conn,sid,followups._current(None)))}
        return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    finally:
        if owned:
            conn.rollback()
            conn.close()


def _model_reply(sid: str, text: str, user_message_id: str = "",
                 generation_stamp: list[str] | None = None,
                 current_mode: str | None = None, proposal_out: list | None = None,
                 citations_out: list | None = None, account_guard_out: list | None = None) -> tuple[str | None, str]:
    """Return the reply and whether the model succeeded, failed, or is unconfigured."""
    before = _model_context_stamp(sid)
    if generation_stamp is not None:
        generation_stamp.append(before)
    client = model.from_env()
    if client is None:
        return None, "unconfigured"
    def account_snapshot():
        account_conn = get_db()
        try:
            return feishu_account.snapshot(account_conn, sid)
        finally:
            account_conn.close()
    account_access = feishu_account.TurnAccess(account_snapshot) if account_snapshot().get('enabled') else None
    facts, inferences, questions, candidates = _memory_groups(sid, text)
    # Exclude dialogue from before a correction, deletion or revocation.
    conn = get_db()
    cutoff = (get_session(sid) or {}).get('context_after_message_rowid', 0)
    recent = [dict(r) for r in conn.execute(
        "SELECT role,text FROM messages WHERE session_id=? AND rowid>? AND id!=? AND suppressed=0 ORDER BY rowid DESC LIMIT 20",
        (sid, cutoff, user_message_id)).fetchall()][::-1]
    conn.close()
    for message in recent:
        message['text'] = agent_runtime.model_visible_text(message['text'], message['role'])
    remote_text = agent_runtime.model_visible_text(text, 'user')
    session = get_session(sid) or {}
    effective_mode, mode_from_preference = _effective_response_mode(sid, session)
    if current_mode is not None:
        effective_mode, mode_from_preference = current_mode, False
    ctx = _active_source_context(sid)
    excerpts = _source_excerpts(sid, text)
    audit(sid, "model.call",
          f"model={client.model} · facts={len(facts)} · inferences={len(inferences)} · items={len(ctx.get('items') or [])}",
          "发送必要上下文（不含正文内容）")
    try:
        system = prompts.system_prompt(session.get("persona_id", "nianxiang"), session.get("interaction_mode", "companion"))
        catalog = plugin_bridge.meme_prompt_catalog()
        if catalog:
            system += ("\n轻松聊天中如果确实合适，可以在正文末尾使用一个表情标记，例如 [表情: happy]；"
                       "认真倾诉和严肃问题不发表情。不必每次都用。仅可使用以下当前可用类别："
                       + json.dumps(catalog, ensure_ascii=False))
        user = prompts.build_user_prompt(facts, inferences, questions, recent, remote_text,
                                      items=ctx.get("items"), insights=ctx.get("insights"),
                                      candidate_facts=candidates, source_excerpts=excerpts,
                                      response_mode=effective_mode, mode_from_preference=mode_from_preference,
                                      conversation_style=session.get("conversation_style", "warm"))
        turn_citations: list[dict] = []
        if account_access is not None or agent_runtime.wants_agent_tools(text, bool(ctx)):
            out, proposal = agent_runtime.run(client, system, user, user_text=text, has_sources=bool(ctx),
                                               search=lambda query: _source_excerpts(sid, query),
                                               feishu_access=account_access, citations_out=turn_citations)
        else:
            out, proposal = client.complete(system, user), None
        out = plugin_bridge.sanitize_meme_markers(out)
        if not out.strip():
            raise ValueError("model response contained no displayable content")
        if get_session(sid) is None:
            # Do not revive a session removed while the model was running.
            return None, "deleted"
        if before != _model_context_stamp(sid) or (account_access is not None and account_access.has_context and not account_access.is_current()):
            audit(sid, "model.stale", "", "生成期间记忆或来源发生变化，未展示旧回复")
            return None, "changed"
        if proposal is not None and proposal_out is not None:
            proposal_out.append(proposal)
        if citations_out is not None:
            citations_out.extend(turn_citations)
        if account_access is not None and account_access.has_context and account_guard_out is not None:
            # The CLI account can change independently of our database. Check
            # again just before committing, without holding the SQLite lock.
            account_guard_out.append(account_access.is_current)
        audit(sid, "model.success", f"model={client.model}", "模型回复已生成")
        return out, "ok"
    except agent_runtime.FeishuContextChanged:
        if get_session(sid) is None:
            return None, "deleted"
        audit(sid, 'model.stale', '', '飞书连接已变化，停止发送本轮已读取内容')
        return None, 'changed'
    except (model.ModelError, ValueError, TypeError) as e:
        if get_session(sid) is None:
            return None, "deleted"
        audit(sid, "model.fallback", str(e)[:100], "模型不可用，降级规则引擎")
        return None, "failed"


def _urgent_safety_signal(text: str) -> bool:
    """Conservative, deliberately limited guard for explicit dangerous statements.

    This is not a classifier or guarantee; handle matching phrases before any
    command shortcut, outage, or conversation budget can mask the request.
    """
    compact = ''.join(text.lower().split())
    signals = ('自杀', '自残', '自伤', '伤害自己', '割腕', '跳楼', '不想活',
               '想死', '结束生命', '结束自己的生命', '结束自己生命', '杀了自己',
               '杀人', '杀了他', '杀了她', '杀了他们', '伤害他人', '伤害别人',
               'suicide', 'killmyself', 'hurtmyself', 'killhim', 'killher')
    return any(signal in compact for signal in signals)


def generate_reply(sid: str, text: str, *,
                   should_cancel: Callable[[], bool] | None = None,
                   reply_lock=None, time_zone: str | None = None) -> dict:
    """陪伴回复：模型优先，失败/未配置时降级规则；返回回复与状态变化（PRD F07/F10/F11）。"""
    text = text.strip()
    if _urgent_safety_signal(text):
        reply = ("我听到这里可能涉及安全，我在乎你此刻的处境。请先远离可能伤害自己或他人的物品，"
                 "联系一位信任的人陪在身边。如果你或他人正面临立即危险，请马上联系当地急救或报警。"
                 "你现在身边有人吗？")
        user_message = add_message(sid, "user", text)
        assistant_message = add_message(sid, "assistant", reply)
        set_session_state(sid, "responding")
        audit(sid, "chat.safety", "explicit safety signal", "安全回应优先于命令和模型状态")
        return {"reply": reply, "action": "safety", "state": "responding",
                "memories": list_memories(sid), "messages": get_messages(sid), "user_message_id": user_message["id"],
                "assistant_message_id": assistant_message["id"]}
    used = _chat_budget_used(sid)
    if used >= CHAT_BUDGET and companion_boundary.direct_control(text) is None:
        raise BudgetExceeded(f"近{CHAT_BUDGET_WINDOW_MINUTES}分钟已达到 {CHAT_BUDGET} 轮聊天预算上限，请稍后再试；之前的内容仍保留。")
    # Persist incoming text before remote work, so a superseding turn can use
    # it even when the old reply is cancelled. Exclude only this message from
    # the recent-history block; build_user_prompt adds it as the current turn.
    user_message = add_message(sid, "user", text, time_zone=time_zone)

    generation_stamp: list[str] = []
    proposal_out: list[dict] = []
    citations_out: list[dict] = []
    account_guards: list[Callable[[], bool]] = []

    def finish(reply: str, action: str | None, state: str, **extra) -> dict:
        # Cancellation shares reply_lock with the request ledger. Context
        # validation and the actual answer commit share one SQLite write lock;
        # revocation cannot slip between the comparison and the insert.
        with reply_lock if reply_lock is not None else nullcontext():
            if action == 'model.reply' and any(not guard() for guard in account_guards):
                reply = '刚才飞书连接发生了变化，这次旧回复没有展示。你可以重新连接后再试。'
                action, state, extra = 'model.stale', 'responding', {}
            conn = get_db()
            cancelled = False
            assistant_id = None
            try:
                conn.execute('BEGIN IMMEDIATE')
                session_row = conn.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
                session = dict(session_row) if session_row else None
                if session is None or (should_cancel is not None and should_cancel()):
                    cancelled = True
                    if session is not None:
                        conn.execute('INSERT INTO audit(id,session_id,action,detail,reason,created_at) VALUES(?,?,?,?,?,?)',
                                     (uid('aud'), sid, 'chat.cancelled', '', '新输入已到达，未保存或展示旧回复', now()))
                else:
                    if generation_stamp and generation_stamp[-1] != _model_context_stamp(sid, conn):
                        reply = '刚才记忆或来源发生了变化，这次旧回复没有展示。你可以再说一次。'
                        action, state, extra = 'model.stale', 'responding', {}
                        conn.execute('INSERT INTO audit(id,session_id,action,detail,reason,created_at) VALUES(?,?,?,?,?,?)',
                                     (uid('aud'), sid, 'model.stale', '', '提交前上下文已变化，未保存旧回复', now()))
                    assistant_id = uid('msg')
                    conn.execute('INSERT INTO messages(id,session_id,role,text,citations,suggestions,created_at,persona_id,interaction_mode) VALUES(?,?,?,?,?,?,?,?,?)',
                                 (assistant_id, sid, 'assistant', reply,
                                  json.dumps(citations_out if action == 'model.reply' else [], ensure_ascii=False), '[]', now(), session.get('persona_id') or 'nianxiang', session.get('interaction_mode') or 'companion'))
                    if action == "model.reply":
                        chat_delivery.register(conn, sid, assistant_id, reply, mode=session.get('interaction_mode') or 'companion')
                    conn.execute('UPDATE sessions SET state=? WHERE id=?', (state, sid))
                    if action == "model.reply" and proposal_out:
                        agent_runtime.persist_proposal(conn, sid, assistant_id, proposal_out[0], agent_runtime.context_stamp(conn, sid))
                    conn.execute('INSERT INTO audit(id,session_id,action,detail,reason,created_at) VALUES(?,?,?,?,?,?)',
                                 (uid('aud'), sid, 'chat.turn', text[:60], action or 'reply', now()))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            if cancelled:
                return {'cancelled': True, 'reply': '', 'action': 'cancelled',
                        'state': (session or {}).get('state', 'listening'),
                        'memories': list_memories(sid), 'messages': get_messages(sid),
                        'user_message_id': user_message['id'], 'assistant_message_id': None}
            return {'reply': reply, 'action': action, 'state': state,
                    'memories': list_memories(sid), 'messages': get_messages(sid),
                    'user_message_id': user_message['id'], 'assistant_message_id': assistant_id, **extra}

    if user_message.get('companion_boundary'):
        boundary=user_message['companion_boundary']
        answer = ('好，恢复之后只会按新的有效窗口联系，错过的不会补发。' if boundary['mode']=='active' else
                  '好，今天先不主动打扰。待办仍保留，你需要时可以查看。' if boundary['mode']=='until' else
                  '好，先暂停主动联系。待办仍保留，你可以随时恢复。')
        # Pausing outbound contact does not refuse a user's current expression.
        # A mixed turn still reaches the normal companion response; the bound
        # policy was already committed, independently of model availability.
        clauses=re.split(r'[,，。.;；!！\r\n]',text,maxsplit=1)
        explanation=clauses[1].strip(' \t\r\n，,。.;；!！') if len(clauses)>1 else ''
        if not explanation or used>=CHAT_BUDGET:
            return finish(answer,'boundary.changed','listening' if boundary['mode']=='active' else 'quiet',companion_boundary=boundary)

    if faults.active("model_timeout") and not _is_command(text):
        reply = "模型超时：这次没有完成（failed）。可以重试，或切回规则引擎。"
        audit(sid, "model.timeout", "injected", "故障演练：模型超时")
        return finish(reply, "failed", "failed", error="model_timeout")
    lower = text.lower()
    bm = latest_bookmark(sid)
    reply, action = "", None
    state = "responding"

    memory_request = _memory_request(text)
    memory_note = ''
    followup = ''
    if memory_request is not None:
        fact, followup = memory_request
        if fact:
            existing = _remember_candidate_once(sid, fact)
            memory_note = ('这条已在确认过的记忆里。' if existing == 'confirmed' else
                           '这条已在待确认记忆里。' if existing == 'candidate' else
                           '记下了，先放在待确认里，你可以随时改或删。')
        else:
            memory_note = '你想让我记住什么？'
    command = _is_command(text) and not followup
    model_text = followup or text
    requested_mode = requested_response_mode(model_text) if not command else None
    requested_style = requested_conversation_style(model_text) if not command else None
    if requested_mode:
        conn = get_db()
        conn.execute("UPDATE sessions SET response_mode=? WHERE id=?", (requested_mode, sid))
        conn.commit()
        conn.close()
    if requested_style:
        conn = get_db()
        conn.execute("UPDATE sessions SET conversation_style=? WHERE id=?", (requested_style, sid))
        conn.commit()
        conn.close()
    response_mode, _ = _effective_response_mode(sid)
    response_mode = requested_mode or response_mode
    model_reply, model_state = (None, "command") if command else _model_reply(sid, model_text, user_message["id"], generation_stamp, requested_mode, proposal_out, citations_out, account_guards)
    grounded = None if (command or model_reply or model_state == "changed" or response_mode == "listen") else _grounded_reply(sid, model_text)
    capability = None if (command or model_reply or grounded or model_state == "changed") else _capability_reply(sid, model_text)

    if model_state == "changed":
        reply = "刚才记忆或来源发生了变化，这次旧回复没有展示。你可以再说一次。"
        action = "model.stale"
    elif model_reply:
        reply = model_reply
        action = "model.reply"
    elif grounded:
        reply = grounded
        action = "context.reply"
    elif capability:
        reply = capability
        action = "capability.reply"
    elif command and memory_request is None and any(k in text for k in ("继续", "回到", "上次", "书签")):
        if bm:
            reply = (
                f"上次你停在：{bm['note'][:60]}。"
                f"当时的选择是「{bm['choice']}」，下一步是「{bm['next_step']}」。"
                "要从这里继续吗？"
            )
            action = "bookmark.recall"
        else:
            reply = "我还没有你确认过的书签。要现在标记一个吗？"
    elif command and text.strip().strip("。.!！?？ ") in ("别安排", "不用提醒", "不用提醒我"):
        reply = "好，这次不安排提醒。你想继续说的话，我在。"
        action = "action.declined"
    elif command and memory_request is None and any(k in text for k in ("停", "别", "安静", "不用")):
        reply = "好，我先安静。需要的时候叫我。"
        state = "quiet"
    elif memory_request is not None and not followup:
        reply = memory_note
        action = "memory.candidate"
    elif response_mode == "listen":
        reply = "我在听，你可以慢慢说。"
    elif any(k in model_text for k in ("下一步", "怎么办", "建议")):
        digest = _memory_digest(sid)
        reply = "我现在无法给出可靠建议。你可以先说说，最希望我帮你理清哪一部分。"
        action = "suggestion"
    else:
        reply = "我在听。"
    if model_state in ("failed", "unconfigured"):
        notice = "模型暂时不可用" if model_state == "failed" else "还没有连接对话模型"
        reply = f"{notice}，这次先用简单回复。{reply}"
    if memory_request is not None and followup and model_state != 'changed':
        reply = memory_note + reply
    return finish(reply, action, state)


def audit_list(sid: str | None = None) -> list[dict]:
    conn = get_db()
    if sid:
        rows = conn.execute(
            "SELECT * FROM audit WHERE session_id=? OR session_id IS NULL ORDER BY created_at DESC LIMIT 100",
            (sid,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM audit ORDER BY created_at DESC LIMIT 100").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------- next step & source revoke ----------------

def suggest_next_step(sid: str) -> dict:
    """基于当前理解给一条可改的下一步（PRD F10/F22）。"""
    mems = _available_memories(sid)
    confirmed = [m for m in mems if m["status"] == "confirmed"]
    based = confirmed or mems
    joined = " ".join(m["text"] for m in mems)

    # 用户刚确认的那一条优先决定下一步：纠正后下一步应随之变化（PRD F22）
    latest = max(confirmed, key=lambda m: m["updated_at"] or "") if confirmed else None
    focus = latest["text"] if latest else joined
    if "演示" in focus or "团队" in focus:
        step = "把最小闭环写成一句可演示的话，并约一个 15 分钟的团队演示"
        why = "基于你刚确认的这条理解（团队/演示）"
    elif "记忆" in focus or "上下文" in focus:
        step = "先只做一种记忆：用户确认过的事实；把「待确认 → 确认」做成一次交互"
        why = "基于你刚确认的这条理解（记忆分寸）"
    elif "原型" in focus or "交互" in focus:
        step = "把理解卡放进原型首页，只保留一个入口和一个结果对象"
        why = "基于你刚确认的这条理解（交互原型）"
    elif latest:
        step = f"把这条已确认的理解变成一个小动作：{focus[:36]}"
        why = "基于你刚确认的这条理解"
    else:
        step = "先确认一条理解，再决定要不要把它变成书签"
        why = "目前还没有足够稳定的理解"

    return {
        "step": step,
        "rationale": f"{why}；基于 {len(based)} 条理解（{'已确认' if confirmed else '待确认'}）。",
        "based_on": [
            {"id": m["id"], "text": m["text"], "version": m["version"], "status": m["status"]}
            for m in based[:5]
        ],
        "changed_by_version": max([m["version"] for m in based], default=0),
    }


def revoke_source(sid: str, source_id: str | None = None) -> dict:
    """Remove one attachment, or all attachments for legacy callers."""
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        source_context.migrate_legacy(conn, now())
        sess = conn.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
        if not sess:
            return {"ok": False, "reason": "session not found"}
        attached = source_context.rows(conn, sid)
        selected = [row for row in attached if source_id is None or row['id'] == source_id]
        if source_id is not None and not selected:
            return {'ok': False, 'reason': 'source not found'}
        if not selected:
            return {'ok': True, 'cleaned': 0, 'state': sess['state'], 'review_required': 0}
        companion_boundary.invalidate(conn,sid)
        selected_ids = {row['id'] for row in selected}
        connection_intro.cancel_for_sources(conn, sid, selected_ids)
        mids, review_ids = set(), set()
        personal = ('用户手动添加', '对话中用户要求', '对话原话 · 用户选存', '对话原话 · 用户纠正')
        for attachment in selected:
            if not attachment['legacy']:
                mids.update(row[0] for row in conn.execute(
                    'SELECT id FROM memories WHERE session_id=? AND source_attachment_id=?', (sid, attachment['id'])))
                continue
            label = attachment['label']
            source_name = label.split(' · ')[0] if ' · ' in label else ''
            known = {label} if label and label not in personal else set()
            if source_name:
                known.add(source_name + ' · 真实只读')
            provider_label = {'feishu': '飞书文档 · 已连接', 'gmail': 'Gmail · 只读',
                              'notion': 'Notion · 只读'}.get(attachment['connector_id'])
            if provider_label:
                known.add(provider_label)
            for row in conn.execute('SELECT * FROM memories WHERE session_id=?', (sid,)).fetchall():
                if row['source'] in personal or (row['source_attachment_id'] and row['source_attachment_id'] not in selected_ids):
                    continue
                original = conn.execute('SELECT text FROM memory_revisions WHERE memory_id=? AND version=1', (row['id'],)).fetchone()
                if row['source'] in known and original is not None and original['text'] == row['text']:
                    mids.add(row['id'])
                else:
                    review_ids.add(row['id'])
        review_ids -= mids
        removed_lineages = {row['id'] for mid in mids for row in _lineage_rows(conn, mid)}
        _delete_lineages(conn, list(mids))
        _invalidate_history(conn, {sid})
        review_rows = {row['id']: row for mid in review_ids for row in _lineage_rows(conn, mid)}
        _invalidate_history(conn, {row['session_id'] for row in review_rows.values()})
        _mark_memory_sources_stale(conn, list(review_rows.values()))
        for review_sid in {row['session_id'] for row in review_rows.values()}:
            conn.execute('UPDATE bookmarks SET recallable=0 WHERE session_id=?', (review_sid,))
        for row in review_rows.values():
            source = row['source'] or '未知来源'
            if not source.startswith(REVOKE_REVIEW_PREFIX):
                source = REVOKE_REVIEW_PREFIX + source
            conn.execute("UPDATE memories SET status='candidate',source=?,version=version+1,updated_at=? WHERE id=?",
                         (source, now(), row['id']))
            conn.execute('INSERT INTO memory_revisions(id,memory_id,session_id,text,status,version,source,created_at) '
                         'VALUES(?,?,?,?,?,?,?,?)', (uid('rev'), row['id'], row['session_id'], row['text'],
                         'candidate', row['version'] + 1, source, now()))
        cutoff = min(row['bookmark_start_rowid'] for row in selected)
        for bookmark in conn.execute('SELECT rowid,* FROM bookmarks WHERE session_id=?', (sid,)).fetchall():
            marker = bookmark['source_attachment_id']
            if (marker in selected_ids or bookmark['source_memory_id'] in removed_lineages or
                    (not marker and not bookmark['source_memory_id'] and bookmark['rowid'] > cutoff)):
                conn.execute('UPDATE bookmarks SET recallable=0 WHERE id=?', (bookmark['id'],))
        for attachment in selected:
            conn.execute('DELETE FROM source_attachments WHERE id=? AND session_id=?', (attachment['id'], sid))
        source_context.sync_compat(conn, sid)
        remaining = len(attached) - len(selected)
        if not remaining:
            conn.execute("UPDATE sessions SET state='revoked',source_revoked=1 WHERE id=?", (sid,))
        state = conn.execute('SELECT state FROM sessions WHERE id=?', (sid,)).fetchone()[0]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    audit(sid, 'source.revoke', f'cleaned={len(mids)} sources={len(selected)}', '用户撤回来源，派生记忆清理')
    return {'ok': True, 'cleaned': len(mids), 'state': state, 'review_required': len(review_rows),
            'remaining_sources': remaining, 'revoked_source_ids': sorted(selected_ids)}


def chat_budget_left(sid: str) -> int:
    return max(0, CHAT_BUDGET - _chat_budget_used(sid))


# ---------------- metrics (product validation) ----------------

def metrics(session_id: str | None = None) -> dict:
    conn = get_db()
    where = " WHERE session_id=?" if session_id else ""
    sess_where = " WHERE id=?" if session_id else ""
    args = (session_id,) if session_id else ()

    def one(sql: str, a=()) -> int:
        return conn.execute(sql, a).fetchone()[0] or 0

    sessions = one("SELECT COUNT(*) FROM sessions" + sess_where, args)
    messages = one("SELECT COUNT(*) FROM messages" + where, args)
    memories = one("SELECT COUNT(*) FROM memories" + where, args)
    confirmed = one("SELECT COUNT(*) FROM memories" + where + (" AND" if where else " WHERE") + " status='confirmed'", args)
    candidate = one("SELECT COUNT(*) FROM memories" + where + (" AND" if where else " WHERE") + " status='candidate'", args)
    revisions = one("SELECT COUNT(*) FROM memory_revisions" + where, args)
    corrections = one(
        "SELECT COUNT(*) FROM memory_revisions" + where + (" AND" if where else " WHERE") + " version>1", args
    )
    bm = conn.execute(
        "SELECT status, COUNT(*) FROM bookmarks" + where + " GROUP BY status", args
    ).fetchall()
    bm_map = {r[0]: r[1] for r in bm}
    audit_rows = conn.execute(
        "SELECT action, COUNT(*) FROM audit" + where + " GROUP BY action", args
    ).fetchall()
    audit_map = {r[0]: r[1] for r in audit_rows}
    # 设备是全局资源（不按会话隔离），单独统计
    device_rows = conn.execute(
        "SELECT action, COUNT(*) FROM audit WHERE action LIKE 'device.%' GROUP BY action"
    ).fetchall()
    device_map = {r[0]: r[1] for r in device_rows}
    conn.close()

    total_bm = bm_map.get("draft", 0) + bm_map.get("committed", 0)
    mem_total = confirmed + candidate
    return {
        "sessions": sessions,
        "messages": messages,
        "memories": {"total": memories, "confirmed": confirmed, "candidate": candidate},
        "revisions": revisions,
        "corrections": corrections,
        "bookmarks": {"draft": bm_map.get("draft", 0), "committed": bm_map.get("committed", 0)},
        "device": {
            "starts": device_map.get("device.start", 0),
            "stops": device_map.get("device.stop", 0),
            "buttons": device_map.get("device.button", 0),
            "displays": device_map.get("device.display", 0),
            "abstains": device_map.get("device.abstain", 0),
            "scope": "global",
        },
        "model": {"calls": audit_map.get("model.call", 0), "fallbacks": audit_map.get("model.fallback", 0)},
        "lark": {"reads": audit_map.get("lark.read", 0)},
        "rates": {
            "confirm": round(confirmed / mem_total, 3) if mem_total else 0,
            "bookmark": round(bm_map.get("committed", 0) / total_bm, 3) if total_bm else 0,
        },
        "audit_events": sum(audit_map.values()),
    }


# ---------------- actions (insight → reminder/calendar/message) ----------------

ACTION_KINDS = {"reminder", "calendar", "message"}


def create_action(sid: str, kind: str, title: str, detail: str = "", when_text: str = "") -> dict:
    if kind not in ACTION_KINDS:
        raise ValueError(f"unknown action kind: {kind}")
    aid = uid("act")
    conn = get_db()
    conn.execute(
        "INSERT INTO actions(id,session_id,kind,title,detail,status,receipt,when_text,created_at,committed_at) "
        "VALUES(?,?,?,?,?,'previewed','',?,?,NULL)",
        (aid, sid, kind, title[:200], detail[:2000], when_text[:40], now()),
    )
    conn.commit()
    conn.close()
    audit(sid, f"action.preview.{kind}", f"{aid} {title[:60]}", "用户查看动作预览")
    return {"id": aid, "kind": kind, "title": title, "detail": detail, "status": "previewed"}


def commit_action(aid: str, real: bool = False) -> dict | None:
    conn = get_db()
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute("SELECT * FROM actions WHERE id=?", (aid,)).fetchone()
    if not row:
        conn.close()
        return None
    if row['status'] != 'previewed':
        conn.close()
        d = dict(row)
        d['error'] = ('此动作已处理或结果待确认，请先检查系统，重新操作需新建预览。'
                      if row['status'] != 'committed' or (real and not row['real']) else '')
        return d
    error = ''
    if real and row['kind'] not in ('reminder', 'calendar'):
        error = '此动作不支持真实写入。'
    elif real and row['kind'] == 'calendar' and not (row['when_text'] or '').strip():
        error = '请先选择日历时间，再创建新预览。'
    if error:
        conn.execute("UPDATE actions SET status='failed', receipt='', real=0, committed_at=NULL WHERE id=?", (aid,))
        conn.commit()
        out = dict(conn.execute("SELECT * FROM actions WHERE id=?", (aid,)).fetchone())
        conn.close()
        audit(row['session_id'], f"action.failed.{row['kind']}", aid, error)
        out['error'] = error
        return out
    # Claim before calling an external app so duplicate requests cannot repeat a write.
    conn.execute("UPDATE actions SET status='executing' WHERE id=?", (aid,))
    conn.commit()
    conn.close()
    real_ok = 0
    status = 'committed'
    receipt = f"{row['kind']}:{hashlib.sha256((aid + now()).encode()).hexdigest()[:12]}"
    if real:
        try:
            result = (apple_source.create_reminder(row['title']) if row['kind'] == 'reminder'
                      else apple_source.create_event(row['title'], row['when_text']))
            if not result or result.get('ok') is not True:
                raise RuntimeError('系统未确认写入')
            real_ok = 1
            prefix = 'reminders' if row['kind'] == 'reminder' else 'calendar'
            receipt = f"{prefix}:{hashlib.sha256((aid + now()).encode()).hexdigest()[:12]}"
        except Exception as e:
            # A timeout or lost response does not prove whether the system wrote it.
            status, receipt = 'unknown', ''
            error = f"系统未确认写入，请先检查系统再决定是否重试：{str(e)[:120]}"
    conn = get_db()
    conn.execute("UPDATE actions SET status=?, receipt=?, real=?, committed_at=? WHERE id=?",
                 (status, receipt, real_ok, now() if status == 'committed' else None, aid))
    conn.commit()
    out = conn.execute("SELECT * FROM actions WHERE id=?", (aid,)).fetchone()
    conn.close()
    audit(row["session_id"], f"action.{'commit' if status == 'committed' else 'unknown'}.{row['kind']}",
          f"{aid} {receipt}", "用户确认执行" + ("（真实写入）" if real_ok else ""))
    d = dict(out)
    d["error"] = error
    return d


def list_actions(sid: str | None = None) -> list[dict]:
    conn = get_db()
    if sid:
        rows = conn.execute("SELECT * FROM actions WHERE session_id=? ORDER BY rowid DESC", (sid,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM actions ORDER BY rowid DESC LIMIT 100").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_session(sid: str) -> dict:
    """删除本次会话及其全部派生数据（PRD F14/F23）。"""
    conn = get_db()
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_turns'").fetchone():
        conn.execute("DELETE FROM chat_turns WHERE session_id=?", (sid,))
    mids = [r[0] for r in conn.execute("SELECT id FROM memories WHERE session_id=?", (sid,))]
    counts = {"memories": len(mids), "memory_revisions": conn.execute(
        "SELECT COUNT(*) FROM memory_revisions WHERE session_id=?", (sid,)).fetchone()[0]}
    _delete_lineages(conn, mids)
    counts['followups'] = followups.delete_for_session(conn, sid)
    counts.update(proactive_policy.delete_for_session(conn,sid))
    counts['mood_entries'] = moods.delete_for_session(conn, sid)
    counts['mood_operations'] = mood_operations.delete_for_session(conn, sid)
    conn.execute("DELETE FROM chat_delivery WHERE session_id=?", (sid,))
    conn.execute("DELETE FROM agent_action_proposals WHERE session_id=?", (sid,))
    for table, key in (("messages", "session_id"), ("memories", "session_id"),
                       ("memory_revisions", "session_id"), ("bookmarks", "session_id"),
                       ("actions", "session_id"), ("audit", "session_id"),
                       ("feishu_account_connections", "session_id"),
                       ("connection_intro_jobs", "session_id"),
                       ("session_context", "session_id"), ("source_attachments", "session_id"), ("sessions", "id")):
        if table not in counts:
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {key}=?", (sid,)).fetchone()[0]
        conn.execute(f"DELETE FROM {table} WHERE {key}=?", (sid,))
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": counts}


def list_sessions(limit: int = 20) -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM sessions ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        last = conn.execute(
            "SELECT text,created_at FROM messages WHERE session_id=? ORDER BY rowid DESC LIMIT 1",
            (r["id"],),
        ).fetchone()
        first_user = conn.execute(
            "SELECT text FROM messages WHERE session_id=? AND role='user' ORDER BY rowid LIMIT 1",
            (r["id"],),
        ).fetchone()
        mem_count = conn.execute("SELECT COUNT(*) c FROM memories WHERE session_id=?", (r["id"],)).fetchone()["c"]
        out.append({
            "id": r["id"],
            "mode": r["mode"],
            "interaction_mode": r["interaction_mode"],
            "source_label": r["source_label"],
            "created_at": r["created_at"],
            "title": ((r["title"] or "").strip()
                      or (first_user["text"][:46] if first_user and first_user["text"] else None)
                      or (r["source_label"] or "新会话")),
            "last_at": last["created_at"] if last else r["created_at"],
            "memories": mem_count,
        })
    conn.close()
    return out


def rename_session(sid: str, title: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT id FROM sessions WHERE id=?", (sid,)).fetchone()
    if not row:
        conn.close()
        return None
    conn.execute("UPDATE sessions SET title=? WHERE id=?", (title.strip()[:80], sid))
    conn.commit()
    conn.close()
    audit(sid, "session.rename", title.strip()[:80], "用户重命名会话")
    return {"ok": True, "id": sid, "title": title.strip()[:80]}


def carryover_memories(sid: str, limit: int = 10) -> list[dict]:
    """其他会话里用户确认过的事实，供新会话选择是否带入。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT id,text,source,session_id,updated_at,version FROM memories "
        "WHERE session_id != ? AND status='confirmed' AND kind='fact' "
        "ORDER BY updated_at DESC, rowid DESC LIMIT 100",
        (sid,),
    ).fetchall()
    existing = {r['text'].strip() for r in conn.execute(
        "SELECT text FROM memories WHERE session_id=? AND status='confirmed'", (sid,)
    ).fetchall() if r['text']}
    conn.close()
    out, seen = [], set()
    for r in rows:
        text = (r["text"] or "").strip()
        if not text or text in seen or text in existing:
            continue
        seen.add(text)
        out.append({"id": r["id"], "text": text, "source": r["source"], "from_session": r["session_id"], "updated_at": r["updated_at"], "version": r["version"]})
        if len(out) >= limit:
            break
    return out


def import_carryover(sid: str, ids: list[str], expected_versions: dict[str, int] | None = None,
                     expected_target: dict[str, int] | None = None) -> dict:
    conn = get_db()
    conn.execute("BEGIN IMMEDIATE")
    if not conn.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone():
        conn.rollback()
        conn.close()
        raise ValueError("会话已不存在，请刷新后重试")
    if expected_versions is not None:
        for mid in ids:
            row = conn.execute("SELECT session_id,status,kind,version FROM memories WHERE id=?", (mid,)).fetchone()
            if (mid not in expected_versions or not row or row['session_id'] == sid or
                    row['status'] != 'confirmed' or row['kind'] != 'fact' or
                    row['version'] != expected_versions[mid]):
                conn.rollback()
                conn.close()
                raise ValueError("记忆在选择后发生变化，请重新核对")
    if expected_target is not None:
        current = {r['id']: r['version'] for r in conn.execute(
            "SELECT id,version FROM memories WHERE session_id=? AND status='confirmed'", (sid,))}
        if current != expected_target:
            conn.rollback()
            conn.close()
            raise ValueError("本次对话的记忆发生变化，请重新核对")
    existing = {r["text"] for r in conn.execute(
        "SELECT text FROM memories WHERE session_id=? AND status='confirmed'", (sid,)
    ).fetchall()}
    origins = {r[0] for r in conn.execute("SELECT origin_memory_id FROM memories WHERE session_id=?", (sid,))}
    imported = 0
    for mid in ids:
        row = conn.execute(
            "SELECT * FROM memories WHERE id=? AND status='confirmed' AND kind='fact'", (mid,)
        ).fetchone()
        if not row or row['session_id'] == sid or row["text"] in existing or mid in origins:
            continue
        new_id, ts = uid('mem'), now()
        source = '跨会话 · 关联记忆'
        conn.execute("INSERT INTO memories(id,session_id,kind,text,status,version,source,created_at,updated_at,origin_memory_id) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?)", (new_id, sid, 'fact', row['text'], 'confirmed', 1, source, ts, ts, mid))
        conn.execute("INSERT INTO memory_revisions(id,memory_id,session_id,text,status,version,source,created_at) "
                     "VALUES(?,?,?,?,?,?,?,?)", (uid('rev'), new_id, sid, row['text'], 'confirmed', 1, source, ts))
        existing.add(row['text'])
        origins.add(mid)
        imported += 1
    conn.commit()
    conn.close()
    if imported:
        audit(sid, "memory.carryover", f"{imported} 条", "用户把之前确认的理解带进本次会话")
    return {"ok": True, "imported": imported}
