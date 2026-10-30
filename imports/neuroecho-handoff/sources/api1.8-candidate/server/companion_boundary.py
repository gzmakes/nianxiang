"""Persistent contact boundaries; never enable a notification or delete a task."""
from datetime import datetime, timedelta
import re
from . import followups

_LEGACY_PAUSE = re.compile(
    r'今天(?:先)?(?:别|不要|不用)(?:再)?'
    r'(?:问(?:我)?|主动(?:问(?:我)?(?:[/／]提醒(?:我)?)?|提醒(?:我)?|关怀(?:我)?|打扰(?:我)?))'
    r'(?:了)?'
)
_LEGACY_RESUME = re.compile(r'(?:请|可以)?恢复主动(?:关怀|打扰)(?:我)?(?:了)?')


def init_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS companion_boundary (
        session_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, mode TEXT NOT NULL,
        until_at TEXT, time_zone TEXT NOT NULL, suppression_revision INTEGER NOT NULL,
        contact_after TEXT, updated_at TEXT NOT NULL)''')
    _migrate_legacy(conn)


def _migrate_legacy(conn):
    """Keep R9's separate ask/notify boundaries conservatively in R14.

    The newer policy has only one contact scope: while either legacy scope is
    paused, both remain paused. This deliberately may suppress extra contact.
    The caller owns the transaction. Never overwrite an existing new policy or
    remove the old table; a marker prevents a deleted policy being resurrected.
    """
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='companion_boundaries'").fetchone():
        return
    columns = {row[1] for row in conn.execute('PRAGMA table_info(companion_boundaries)')}
    if 'session_id' not in columns:
        raise ValueError('旧版陪伴边界缺少对话身份，无法安全迁移。')
    conn.execute('CREATE TABLE IF NOT EXISTS companion_boundary_legacy_migrated (session_id TEXT PRIMARY KEY)')
    required = {'ask_until', 'notify_until', 'ask_time_zone', 'notify_time_zone'}
    now = followups._current(None)
    stamp = followups._stamp(now)
    names = ['session_id', 'ask_until', 'notify_until', 'ask_time_zone', 'notify_time_zone',
             'ask_suppressed_through', 'notify_suppressed_through', 'revision']
    select = ','.join(name if name in columns else 'NULL' for name in names)
    rows = conn.execute(f'SELECT {select} FROM companion_boundaries').fetchall()
    for row in rows:
        sid, ask_until, notify_until, ask_zone, notify_zone, ask_cutoff, notify_cutoff, revision = row
        if not isinstance(sid, str) or not sid:
            raise ValueError('旧版陪伴边界的对话身份无效，无法安全迁移。')
        if not conn.execute('SELECT 1 FROM sessions WHERE id=?', (sid,)).fetchone():
            continue
        if conn.execute('SELECT 1 FROM companion_boundary_legacy_migrated WHERE session_id=?', (sid,)).fetchone():
            continue
        if not conn.execute('SELECT 1 FROM companion_boundary WHERE session_id=?', (sid,)).fetchone():
            invalid = not required.issubset(columns)
            try:
                ends = [followups._utc(value) for value in (ask_until, notify_until) if value is not None]
                cutoffs = [followups._utc(value) for value in (ask_cutoff, notify_cutoff) if value is not None]
            except (TypeError, ValueError, OverflowError):
                # An unreadable legacy time must not silently re-enable contact.
                invalid, ends, cutoffs = True, [], []
            future = max((value for value in ends if value > now), default=None)
            # An expired pause also suppresses occurrences at the exact end.
            cutoff = max(cutoffs + [min(value, now) for value in ends], default=None)
            zone = 'UTC'
            for candidate in (ask_zone, notify_zone):
                if candidate:
                    try:
                        followups._zone(candidate)
                        zone = candidate
                        break
                    except (TypeError, ValueError):
                        invalid = True
            mode = 'paused' if invalid else 'until' if future else 'active'
            version = revision if type(revision) is int and revision > 0 else 1
            conn.execute('INSERT INTO companion_boundary VALUES(?,?,?,?,?,?,?,?)',
                         (sid, version, mode, followups._stamp(future) if future and not invalid else None,
                          zone, 1, followups._stamp(cutoff) if cutoff else None, stamp))
        conn.execute('INSERT INTO companion_boundary_legacy_migrated VALUES(?)', (sid,))


def exists(conn):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='companion_boundary'").fetchone())


def delete_legacy_for_session(conn, sid):
    """Delete only this conversation's old metadata in caller's transaction."""
    for name in ('companion_boundaries', 'companion_boundary_legacy_migrated'):
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone():
            # Both identifiers are static strings above, never caller input.
            conn.execute(f'DELETE FROM {name} WHERE session_id=?', (sid,))


def snapshot(conn, sid, now):
    row = conn.execute('SELECT * FROM companion_boundary WHERE session_id=?',(sid,)).fetchone() if exists(conn) else None
    value = dict(row) if row else dict(revision=0,mode='active',until_at=None,time_zone='UTC',suppression_revision=0,contact_after=None)
    if value['mode']=='until' and followups._utc(value['until_at']) <= now:
        # Automatic resumption never makes items due during the silence eligible.
        cutoff = max(filter(None,(value['contact_after'],value['until_at'])),key=followups._utc)
        value.update(mode='active',until_at=None,contact_after=cutoff)
    return value


def public(value):
    return {key:value[key] for key in ('revision','mode','time_zone','suppression_revision')} | {'until':value['until_at']}


def _require_session(conn,sid):
    if not conn.execute('SELECT 1 FROM sessions WHERE id=?',(sid,)).fetchone():
        raise LookupError('对话不存在。')


def get(db_path,sid,*,clock=None):
    conn=followups._connect(db_path)
    try:
        _require_session(conn,sid)
        return public(snapshot(conn,sid,followups._current(clock)))
    finally:conn.close()


class BoundaryConflict(ValueError):
    def __init__(self,current_revision):
        super().__init__('陪伴边界已在其他窗口更改，请刷新后核对。')
        self.current_revision=current_revision


def _invalidate_pending(conn,sid):
    # Context stamps bind in-flight generation. Existing queued parts/proposals
    # are withdrawn now, inside the same transaction as the boundary update.
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_action_proposals'").fetchone():
        conn.execute('DELETE FROM agent_action_proposals WHERE session_id=?',(sid,))
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_delivery'").fetchone():
        from . import chat_delivery
        chat_delivery.interrupt(conn,sid)


def _store(conn,sid,old,mode,until,zone,now):
    stamp=followups._stamp(now)
    cutoff=max(filter(None,(old.get('contact_after'),stamp)),key=followups._utc)
    conn.execute('''INSERT INTO companion_boundary VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(session_id) DO UPDATE SET revision=excluded.revision,mode=excluded.mode,
        until_at=excluded.until_at,time_zone=excluded.time_zone,suppression_revision=excluded.suppression_revision,
        contact_after=excluded.contact_after,updated_at=excluded.updated_at''',
        (sid,old['revision']+1,mode,until,zone,old['suppression_revision']+1,cutoff,stamp))
    _invalidate_pending(conn,sid)
    return public(snapshot(conn,sid,now))


def put(db_path,sid,*,expected_revision,mode,until,time_zone,clock=None):
    if type(expected_revision) is not int or expected_revision<0:raise ValueError('边界版本无效。')
    if mode not in ('active','paused','until'):raise ValueError('边界模式无效。')
    followups._zone(time_zone)
    now=followups._current(clock)
    if mode=='until':
        if until is None or followups._utc(until)<=now:raise ValueError('请明确选择未来的恢复时间。')
        until=followups._stamp(followups._utc(until))
    elif until is not None:raise ValueError('此模式不接受恢复时间。')
    conn=followups._connect(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE');_require_session(conn,sid)
        old=snapshot(conn,sid,now)
        if old['revision']!=expected_revision:raise BoundaryConflict(old['revision'])
        result=_store(conn,sid,old,mode,until,time_zone,now);conn.commit();return result
    except Exception:conn.rollback();raise
    finally:conn.close()


def invalidate(conn,sid,*,now=None):
    """Source withdrawal invalidates queued claims without changing task data."""
    now=now or followups._current(None)
    if not exists(conn):return
    old=snapshot(conn,sid,now)
    _store(conn,sid,old,old['mode'],old['until_at'],old['time_zone'],now)


def direct_control(text):
    # Only a complete opening command clause counts. Explanations after it may
    # contain quotes/questions; they cannot erase an already explicit refusal.
    if not isinstance(text,str):return None
    # R9 compatibility: only the entire standalone command is accepted. In
    # particular, do not silently discard a second request about another day.
    whole=re.sub(r'\s+','',text.strip())
    whole=re.sub(r'[。！!]+$','',whole)
    if _LEGACY_PAUSE.fullmatch(whole):return 'today'
    if _LEGACY_RESUME.fullmatch(whole):return 'active'
    opening=re.split(r'[,，。.;；!！\r\n]',text.strip(),maxsplit=1)[0].strip()
    if any(ch in opening for ch in '“”「」『』"\'') or opening.endswith(('?','？','吗','么')):return None
    value=re.sub(r'\s+','',opening)
    value=re.sub(r'^(?:请你|请)','',value)
    if value in {'今天先别问','今天别问','今天先别问我','今天别提醒我','今天不要提醒我','今天不打扰','今天先不打扰','今天先别问了','今天别问了','今天不要问了','今天先不要问'}:return 'today'
    if value in {'先别问','先别问我','不用提醒我','不要提醒我','先安静','先安静一会','暂停主动提醒','暂停主动联系','停止主动提醒','不用提醒','别提醒','别问了','先安静一下'}:return 'paused'
    if value in {'恢复主动提醒','恢复主动联系','可以提醒我了'}:return 'active'
    return None


def apply_user_control(conn,sid,text,*,time_zone=None,clock=None):
    control=direct_control(text)
    if control is None:return None
    now=followups._current(clock);old=snapshot(conn,sid,now)
    zone_name=time_zone or old['time_zone'];zone=followups._zone(zone_name)
    until=None;mode=control
    if control=='today':
        tomorrow=now.astimezone(zone).date()+timedelta(days=1)
        until=followups._stamp(datetime.combine(tomorrow,datetime.min.time(),zone).astimezone(now.tzinfo))
        mode='until'
    return _store(conn,sid,old,mode,until,zone_name,now)


def blocked(conn,sid,due,now):
    value=snapshot(conn,sid,now)
    if value['mode']=='paused':return 'boundary_paused'
    if value['mode']=='until':return 'boundary_until'
    if value['contact_after'] and due <= followups._utc(value['contact_after']):return 'suppressed_occurrence'
    return None
