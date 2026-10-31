"""Content-free, transaction-bound invalidation cursors for one conversation.

The database retains only the latest revision for each named domain, never an
unbounded event log or any old user content. Cursors are invalidation hints,
not authorization, write receipts or a merge protocol.
"""
from __future__ import annotations

import base64
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import uuid

from . import companion_boundary, followups

DOMAINS = ('conversation','messages','memories','sources','moods','followups','boundary','actions','turns')
MAX_CURSOR_LENGTH = 2048
RETENTION_REVISIONS = 4096
TABLES = {
    'sessions':('id',('conversation',)),
    'messages':('session_id',('messages',)),
    'memories':('session_id',('memories',)),
    'memory_revisions':('session_id',('memories',)),
    'session_context':('session_id',('sources',)),
    'source_attachments':('session_id',('sources',)),
    'feishu_account_connections':('session_id',('sources',)),
    'mood_entries':('session_id',('moods',)),
    'mood_operations':('session_id',('moods',)),
    'followups':('session_id',('followups',)),
    'followup_notification_settings':('session_id',('followups',)),
    'followup_notification_attempts':('session_id',('followups',)),
    'companion_boundary':('session_id',('boundary','followups')),
    'actions':('session_id',('actions',)),
    'bookmarks':('session_id',('actions',)),
    'agent_action_proposals':('session_id',('messages','actions')),
    'chat_delivery':('session_id',('messages',)),
    'chat_turns':('session_id',('turns',)),
}


class InvalidCursor(ValueError):
    pass


class ConversationNotInitialized(LookupError):
    pass


def _quote(name):
    return '"'+name.replace('"','""')+'"'


def _mark(sid,domain,condition='1'):
    # All identifiers/SQL fragments come from this module's fixed table map.
    valid=f'({condition}) AND {sid} IS NOT NULL AND EXISTS(SELECT 1 FROM sessions WHERE id={sid})'
    return f'''
        UPDATE conversation_change_clock SET sequence=sequence+1 WHERE singleton=1 AND {valid};
        INSERT INTO conversation_change_domains(session_id,domain,revision)
        SELECT {sid},'{domain}',sequence FROM conversation_change_clock WHERE singleton=1 AND {valid}
        ON CONFLICT(session_id,domain) DO UPDATE SET revision=excluded.revision;
    '''


def init_schema(conn):
    """Install using the caller's transaction. No executescript implicit commit."""
    conn.execute('''CREATE TABLE IF NOT EXISTS conversation_change_clock(
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), sequence INTEGER NOT NULL CHECK(sequence>=0),
        epoch TEXT NOT NULL, trigger_schema TEXT NOT NULL)''')
    conn.execute('INSERT OR IGNORE INTO conversation_change_clock VALUES(1,0,?,?)',('chg_'+uuid.uuid4().hex,''))
    allowed=','.join("'"+domain+"'" for domain in DOMAINS)
    conn.execute(f'''CREATE TABLE IF NOT EXISTS conversation_change_domains(
        session_id TEXT NOT NULL, domain TEXT NOT NULL CHECK(domain IN ({allowed})),
        revision INTEGER NOT NULL CHECK(revision>0), PRIMARY KEY(session_id,domain))''')
    present={}
    for table in (*TABLES,'app_state'):
        columns=tuple(row[1] for row in conn.execute(f'PRAGMA table_info({_quote(table)})'))
        if columns:present[table]=columns
    signature=hashlib.sha256(json.dumps(present,sort_keys=True).encode()).hexdigest()
    previous=conn.execute('SELECT trigger_schema FROM conversation_change_clock WHERE singleton=1').fetchone()[0]
    if signature==previous:return
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'cc_v1_*'").fetchall():
        conn.execute(f'DROP TRIGGER {_quote(name)}')
    for table,(key,domains) in TABLES.items():
        if table not in present:continue
        quoted=_quote(table);new='NEW.'+_quote(key);old='OLD.'+_quote(key)
        changed=' OR '.join(f'NEW.{_quote(column)} IS NOT OLD.{_quote(column)}' for column in present[table])
        for operation in ('INSERT','UPDATE','DELETE'):
            if table=='sessions' and operation=='DELETE':
                body=f'''UPDATE conversation_change_clock SET sequence=sequence+1 WHERE singleton=1;
                    DELETE FROM conversation_change_domains WHERE session_id={old};'''
            elif operation=='INSERT':body=''.join(_mark(new,domain) for domain in domains)
            elif operation=='DELETE':body=''.join(_mark(old,domain) for domain in domains)
            else:body=''.join(_mark(old,domain,f'{old} IS NOT {new}')+_mark(new,domain) for domain in domains)
            when=f' WHEN {changed}' if operation=='UPDATE' else ''
            conn.execute(f'CREATE TRIGGER {_quote("cc_v1_"+table+"_"+operation.lower())} AFTER {operation} ON {quoted}{when} BEGIN {body} END')
    if 'app_state' in present:
        for operation in ('INSERT','UPDATE','DELETE'):
            body=''
            if operation in ('UPDATE','DELETE'):
                body+=_mark('OLD.value','conversation',"OLD.key='canonical_conversation'" + (" AND (OLD.key IS NOT NEW.key OR OLD.value IS NOT NEW.value)" if operation=='UPDATE' else ''))
            if operation in ('INSERT','UPDATE'):
                body+=_mark('NEW.value','conversation',"NEW.key='canonical_conversation'" + (" AND (OLD.key IS NOT NEW.key OR OLD.value IS NOT NEW.value)" if operation=='UPDATE' else ''))
            conn.execute(f'CREATE TRIGGER {_quote("cc_v1_app_state_"+operation.lower())} AFTER {operation} ON app_state BEGIN {body} END')
    conn.execute('UPDATE conversation_change_clock SET trigger_schema=?,epoch=? WHERE singleton=1',
                 (signature,'chg_'+uuid.uuid4().hex if previous else conn.execute('SELECT epoch FROM conversation_change_clock WHERE singleton=1').fetchone()[0]))


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()


def _temporal(conn,sid,current):
    """Fingerprint derived visibility only; never fetch or encode message bodies."""
    delivery=[]
    for row in conn.execute('SELECT message_id,start,offsets,stopped FROM chat_delivery WHERE session_id=? ORDER BY message_id',(sid,)):
        offsets=json.loads(row['offsets'])
        if not isinstance(offsets,list) or not offsets or not all(type(value) in (int,float) and math.isfinite(value) for value in offsets):
            raise ValueError('Invalid delivery metadata.')
        elapsed=max(0,current.timestamp()-row['start'])
        count=min(len(offsets),max(1,sum(value<=elapsed for value in offsets)))
        delivery.append((row['message_id'],count,count<len(offsets) and not row['stopped']))
    tasks=[]
    for row in conn.execute('SELECT * FROM followups WHERE session_id=? ORDER BY id',(sid,)):
        item=followups._present(row,current,conn)
        tasks.append((item['id'],item['due'],item['quiet'],item['review_available'],item['contact_eligible'],item['contact_reason']))
    boundary=companion_boundary.public(companion_boundary.snapshot(conn,sid,current))
    return [_digest(delivery),_digest(tasks),_digest(boundary)]


def _encode(instance,sid,epoch,revision,temporal):
    data=json.dumps([1,instance,sid,epoch,revision,temporal],separators=(',',':'),ensure_ascii=True).encode()
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _decode(cursor):
    try:
        if not isinstance(cursor,str) or not 1<=len(cursor)<=MAX_CURSOR_LENGTH or not re.fullmatch(r'[A-Za-z0-9_-]+',cursor):raise ValueError()
        raw=base64.b64decode(cursor+'='*(-len(cursor)%4),altchars=b'-_',validate=True)
        value=json.loads(raw)
        if not isinstance(value,list) or len(value)!=6:raise ValueError()
        version,instance,sid,epoch,revision,temporal=value
        if (type(version) is not int or version!=1 or not all(isinstance(item,str) and 1<=len(item)<=128 for item in (instance,sid,epoch))
                or type(revision) is not int or not 0<=revision<=2**63-1 or not isinstance(temporal,list) or len(temporal)!=3
                or not all(isinstance(item,str) and re.fullmatch(r'[a-f0-9]{64}',item) for item in temporal)):raise ValueError()
        # Reject alternative encodings of the same opaque token.
        if _encode(instance,sid,epoch,revision,temporal)!=cursor:raise ValueError()
        return value
    except (ValueError,TypeError,UnicodeError,RecursionError):raise InvalidCursor('Invalid change cursor.') from None


def read(database,after=None,*,clock=None):
    """One read snapshot. All persistent state was prepared before listening."""
    previous=_decode(after) if after is not None else None
    current=clock() if clock else datetime.now(timezone.utc)
    if not isinstance(current,datetime) or current.tzinfo is None:raise ValueError('Aware clock required.')
    uri=Path(database).resolve().as_uri()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True,timeout=5)) as conn:
        conn.row_factory=sqlite3.Row;conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN')
        canonical=conn.execute("SELECT s.id FROM app_state a JOIN sessions s ON s.id=a.value WHERE a.key='canonical_conversation'").fetchone()
        if canonical is None:raise ConversationNotInitialized('Conversation is not initialized.')
        sid=canonical[0]
        instance=conn.execute('SELECT instance_id FROM paired_service WHERE singleton=1').fetchone()[0]
        state=conn.execute('SELECT sequence,epoch FROM conversation_change_clock WHERE singleton=1').fetchone()
        revisions={row['domain']:row['revision'] for row in conn.execute('SELECT domain,revision FROM conversation_change_domains WHERE session_id=?',(sid,))}
        revision=max(revisions.values(),default=0)
        temporal=_temporal(conn,sid,current)
        reason=None
        if previous is None:reason='initial'
        elif previous[1:4]!=[instance,sid,state['epoch']]:reason='identity_changed'
        elif previous[4]>revision:reason='ahead'
        elif previous[4]<max(0,revision-RETENTION_REVISIONS):reason='too_old'
        domains=list(DOMAINS) if reason else [domain for domain in DOMAINS if revisions.get(domain,0)>previous[4]]
        if reason is None:
            for index,domain in enumerate(('messages','followups','boundary')):
                if previous[5][index]!=temporal[index] and domain not in domains:domains.append(domain)
            domains=[domain for domain in DOMAINS if domain in domains]
        return {'service_instance_id':instance,'conversation_id':sid,
                'cursor':_encode(instance,sid,state['epoch'],revision,temporal),
                'reset_required':reason is not None,'domains':domains,'reset_reason':reason}
