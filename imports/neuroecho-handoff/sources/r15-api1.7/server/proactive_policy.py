"""Bounded, consent-based reservations for desktop follow-up notifications.

A reservation is an attempt, never proof of delivery or of task completion.
Unknown outcomes are intentionally not retried automatically.
"""
from datetime import timedelta
import uuid

from . import followups, companion_boundary
import hashlib
import unicodedata

DEFAULTS = {
    'enabled': False, 'time_zone': 'UTC', 'quiet_start': '22:00',
    'quiet_end': '08:00', 'cooldown_minutes': 60, 'daily_limit': 3,
    'pause_until': None,
}


def init_schema(conn):
    """Install additive tables using caller-owned transaction."""
    conn.execute('''CREATE TABLE IF NOT EXISTS followup_notification_settings (
        session_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL,
        time_zone TEXT NOT NULL, quiet_start TEXT NOT NULL, quiet_end TEXT NOT NULL,
        cooldown_minutes INTEGER NOT NULL, daily_limit INTEGER NOT NULL,
        pause_until TEXT, updated_at TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1
    )''')
    columns = {row[1] for row in conn.execute('PRAGMA table_info(followup_notification_settings)')}
    if 'revision' not in columns:
        conn.execute('ALTER TABLE followup_notification_settings ADD COLUMN revision INTEGER NOT NULL DEFAULT 1')
    conn.execute('''CREATE TABLE IF NOT EXISTS followup_notification_attempts (
        session_id TEXT NOT NULL, followup_id TEXT NOT NULL, occurrence_at TEXT NOT NULL,
        claim_id TEXT NOT NULL UNIQUE, state TEXT NOT NULL,
        claimed_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY(session_id,followup_id,occurrence_at),
        CHECK(state IN ('claimed','invoking','submitted','failed'))
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_followup_notification_attempts_time ON followup_notification_attempts(session_id,claimed_at)')
    companion_boundary.init_schema(conn)
    columns={row[1] for row in conn.execute('PRAGMA table_info(followup_notification_attempts)')}
    for name,spec in [('channel',"TEXT NOT NULL DEFAULT 'system'"),('topic_key','TEXT'),
                      ('window_start','TEXT'),('window_end','TEXT'),('claim_expires_at','TEXT'),
                      ('suppression_revision','INTEGER NOT NULL DEFAULT -1'),('settings_revision','INTEGER NOT NULL DEFAULT -1')]:
        if name not in columns:conn.execute(f'ALTER TABLE followup_notification_attempts ADD COLUMN {name} {spec}')


def _exists(conn, sid):
    if not isinstance(sid, str) or not sid or len(sid) > 128:
        raise ValueError('无效的对话。')
    if not conn.execute('SELECT 1 FROM sessions WHERE id=?', (sid,)).fetchone():
        raise LookupError('对话不存在。')


def _settings(conn, sid, now):
    row = conn.execute('SELECT * FROM followup_notification_settings WHERE session_id=?', (sid,)).fetchone()
    if row is None:
        return {**DEFAULTS, 'configured': False, 'revision': 0}
    result = {key: row[key] for key in DEFAULTS}
    result['configured'] = True
    result['revision'] = row['revision']
    result['enabled'] = bool(result['enabled'])
    if result['pause_until'] and followups._utc(result['pause_until']) <= now:
        result['pause_until'] = None
    return result


def get_settings(db_path, session_id, *, clock=None):
    conn = followups._connect(db_path)
    try:
        _exists(conn, session_id)
        return _settings(conn, session_id, followups._current(clock))
    finally:
        conn.close()


def set_settings(db_path, session_id, *, enabled, time_zone, quiet_start, quiet_end,
                 cooldown_minutes, daily_limit, pause_until=None, expected_revision=None, clock=None):
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
        raise ValueError('提醒设置版本无效。')
    if type(enabled) is not bool:
        raise ValueError('提醒开关无效。')
    zone = followups._zone(time_zone)
    now = followups._current(clock)
    # The quiet helper validates both endpoints, including equal endpoints.
    followups._quiet(quiet_start, quiet_end, now, zone)
    if quiet_start is None or quiet_end is None:
        raise ValueError('请设置安静时段。')
    if type(cooldown_minutes) is not int or not 60 <= cooldown_minutes <= 1440:
        raise ValueError('提醒间隔须为 60 至 1440 分钟。')
    if type(daily_limit) is not int or not 1 <= daily_limit <= 3:
        raise ValueError('每日上限须为 1 至 3 次。')
    pause_stamp = followups._stamp(followups._utc(pause_until)) if pause_until is not None else None
    if pause_stamp and followups._utc(pause_stamp) <= now:
        pause_stamp = None
    conn = followups._connect(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        _exists(conn, session_id)
        current_revision = _settings(conn, session_id, now)['revision']
        if expected_revision is not None and expected_revision != current_revision:
            raise followups.FollowupConflict('提醒设置已在其他窗口更改，请刷新后重试。')
        conn.execute('''INSERT INTO followup_notification_settings(session_id,enabled,time_zone,quiet_start,quiet_end,cooldown_minutes,daily_limit,pause_until,updated_at,revision)
                        VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET
                        enabled=excluded.enabled,time_zone=excluded.time_zone,quiet_start=excluded.quiet_start,
                        quiet_end=excluded.quiet_end,cooldown_minutes=excluded.cooldown_minutes,
                        daily_limit=excluded.daily_limit,pause_until=excluded.pause_until,updated_at=excluded.updated_at,revision=excluded.revision''',
                     (session_id, int(enabled), time_zone, quiet_start, quiet_end, cooldown_minutes, daily_limit, pause_stamp, followups._stamp(now), current_revision + 1))
        result = _settings(conn, session_id, now)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _blocked(conn, sid, config, now, *, excluding_claim=None, channel='system'):
    if channel=='system' and not config['enabled']:
        return 'disabled'
    if config['pause_until'] and followups._utc(config['pause_until']) > now:
        return 'paused'
    zone = followups._zone(config['time_zone'])
    if followups._quiet(config['quiet_start'], config['quiet_end'], now, zone):
        return 'quiet'
    # Compare local dates rather than assuming a day has 24 hours across DST.
    rows = conn.execute("SELECT claim_id,claimed_at FROM followup_notification_attempts WHERE session_id=? AND state IN ('claimed','invoking','submitted','failed')", (sid,)).fetchall()
    claims = [followups._utc(row['claimed_at']) for row in rows if row['claim_id'] != excluding_claim]
    if sum(t.astimezone(zone).date() == now.astimezone(zone).date() for t in claims) >= config['daily_limit']:
        return 'daily_limit'
    if claims and now < max(claims) + timedelta(minutes=config['cooldown_minutes']):
        return 'cooldown'
    return None


def _topic(item):
    value=' '.join(unicodedata.normalize('NFKC',item['contact_topic']).casefold().split())
    return hashlib.sha256(value.encode()).hexdigest()


def contact_blocked(conn,sid,item,now,*,channel='system',excluding_claim=None):
    config=_settings(conn,sid,now)
    if not config['configured']:
        # The task explicitly records the user's local zone even before they
        # configure optional OS notifications. UTC is only the settings DTO's
        # unconfigured placeholder, never the contact's night-time boundary.
        config['time_zone']=item['time_zone']
    rows=conn.execute('SELECT * FROM followup_notification_attempts WHERE session_id=?',(sid,)).fetchall()
    start=followups._utc(item['due_at']);end=followups._utc(item['contact_expires_at'])
    for row in rows:
        if row['claim_id']==excluding_claim:continue
        if row['followup_id']==item['id'] and followups._utc(row['occurrence_at'])==start:return 'already_claimed'
        if row['topic_key']==_topic(item) and row['window_start'] and row['window_end'] and start<followups._utc(row['window_end']) and followups._utc(row['window_start'])<end:
            return 'topic_window_claimed'
    return _blocked(conn,sid,config,now,excluding_claim=excluding_claim,channel=channel)


def _eligible_item(conn,sid,fid,occurrence,now):
    row=conn.execute('SELECT * FROM followups WHERE session_id=? AND id=?',(sid,fid)).fetchone()
    if row is None:raise LookupError('跟进事项不存在。')
    item=followups._present(row,now)
    if followups._utc(item['due_at'])!=occurrence:return item,'occurrence_changed'
    boundary=companion_boundary.snapshot(conn,sid,now)
    reason=item['contact_reason']
    if item.get('contact_suppression_revision',-1)!=boundary['suppression_revision']:reason=reason or 'boundary_changed'
    reason=reason or companion_boundary.blocked(conn,sid,occurrence,now)
    return item,reason


def claim(db_path,session_id,followup_id,occurrence_at,*,channel='system',clock=None):
    if channel not in ('in_app','system'):raise ValueError('联系渠道无效。')
    if not isinstance(followup_id,str) or not 0<len(followup_id)<=128:raise ValueError('无效的跟进事项。')
    occurrence=followups._utc(occurrence_at);occurrence_stamp=followups._stamp(occurrence)
    now=followups._current(clock);conn=followups._connect(db_path)
    base={'channel':channel,'followup_id':followup_id,'occurrence_at':occurrence_stamp}
    try:
        conn.execute('BEGIN IMMEDIATE');_exists(conn,session_id)
        item,reason=_eligible_item(conn,session_id,followup_id,occurrence,now)
        reason=reason or contact_blocked(conn,session_id,item,now,channel=channel)
        if reason:
            conn.commit();return {**base,'claimed':False,'reason':reason,'claim_id':None,'expires_at':None}
        claim_id='fnc_'+uuid.uuid4().hex;stamp=followups._stamp(now)
        expires=followups._stamp(min(now+timedelta(seconds=60),followups._utc(item['contact_expires_at'])))
        boundary=companion_boundary.snapshot(conn,session_id,now)
        conn.execute('''INSERT INTO followup_notification_attempts
            (session_id,followup_id,occurrence_at,claim_id,state,claimed_at,updated_at,channel,topic_key,window_start,window_end,claim_expires_at,suppression_revision,settings_revision)
            VALUES(?,?,?,?,'claimed',?,?,?,?,?,?,?,?,?)''',
            (session_id,followup_id,occurrence_stamp,claim_id,stamp,stamp,channel,_topic(item),occurrence_stamp,item['contact_expires_at'],expires,boundary['suppression_revision'],_settings(conn,session_id,now)['revision']))
        conn.commit();return {**base,'claimed':True,'reason':None,'claim_id':claim_id,'expires_at':expires}
    except Exception:conn.rollback();raise
    finally:conn.close()


def _claim_reason(conn,sid,row,now):
    boundary=companion_boundary.snapshot(conn,sid,now)
    if row['suppression_revision']!=boundary['suppression_revision']:return 'boundary_changed'
    if row['settings_revision']!=_settings(conn,sid,now)['revision']:return 'settings_changed'
    if not row['claim_expires_at'] or now>=followups._utc(row['claim_expires_at']):return 'claim_expired'
    item,reason=_eligible_item(conn,sid,row['followup_id'],followups._utc(row['occurrence_at']),now)
    return reason or contact_blocked(conn,sid,item,now,channel=row['channel'],excluding_claim=row['claim_id'])


def recheck(db_path,session_id,claim_id,*,clock=None):
    now=followups._current(clock);conn=followups._connect(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE');_exists(conn,session_id)
        row=conn.execute('SELECT * FROM followup_notification_attempts WHERE session_id=? AND claim_id=?',(session_id,claim_id)).fetchone()
        meta={'claim_id':claim_id,'followup_id':row['followup_id'] if row else None,
              'occurrence_at':row['occurrence_at'] if row else None,'channel':row['channel'] if row else None,
              'expires_at':row['claim_expires_at'] if row else None}
        if row is None or row['state']!='claimed':
            conn.commit();return {**meta,'allowed':False,'reason':'not_claimed'}
        reason=_claim_reason(conn,session_id,row,now)
        if reason is None:conn.execute("UPDATE followup_notification_attempts SET state='invoking',updated_at=? WHERE claim_id=? AND state='claimed'",(followups._stamp(now),claim_id))
        conn.commit();return {**meta,'allowed':reason is None,'reason':reason}
    except Exception:conn.rollback();raise
    finally:conn.close()


def finish(db_path,session_id,claim_id,outcome,*,clock=None):
    if outcome not in ('submitted','failed'):raise ValueError('无效的提醒结果。')
    now=followups._current(clock);conn=followups._connect(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE');_exists(conn,session_id)
        row=conn.execute('SELECT * FROM followup_notification_attempts WHERE session_id=? AND claim_id=?',(session_id,claim_id)).fetchone()
        if row is None:raise LookupError('提醒尝试不存在。')
        if row['state']!=outcome:
            permitted=('invoking',) if outcome=='submitted' else ('claimed','invoking')
            if row['state'] not in permitted or _claim_reason(conn,session_id,row,now):raise followups.FollowupConflict('联系许可已失效或结果尚待核对，没有再次联系。')
            conn.execute('UPDATE followup_notification_attempts SET state=?,updated_at=? WHERE claim_id=?',(outcome,followups._stamp(now),claim_id))
        conn.commit();return {'state':outcome,'claim_id':claim_id,'channel':row['channel']}
    except Exception:conn.rollback();raise
    finally:conn.close()


def delete_for_session(conn, session_id):
    """Delete settings and attempts in the caller's deletion transaction."""
    attempts = conn.execute('DELETE FROM followup_notification_attempts WHERE session_id=?', (session_id,)).rowcount
    settings = conn.execute('DELETE FROM followup_notification_settings WHERE session_id=?', (session_id,)).rowcount
    boundary=conn.execute('DELETE FROM companion_boundary WHERE session_id=?',(session_id,)).rowcount
    return {'notification_attempts':attempts,'notification_settings':settings,'companion_boundaries':boundary}
