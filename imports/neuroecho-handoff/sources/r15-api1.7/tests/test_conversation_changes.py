"""Real temporary SQLite/HTTP cursor regressions; no accounts/model/CLI/OS calls."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import base64
import json
import sqlite3
from threading import Event

from fastapi.testclient import TestClient
import pytest

from server import core,main,conversation_changes as changes,paired_access,paired_app,moods,followups,companion_boundary,chat_delivery


@pytest.fixture
def owner():
    with TestClient(main.app) as client:
        yield client


def feed(client,after=None):
    response=client.get('/api/conversation/changes',params={'after':after} if after is not None else {})
    assert response.status_code==200,response.text
    assert response.headers['cache-control']=='no-store'
    return response.json()


def sql(statement,args=()):
    with sqlite3.connect(core.DB_PATH,timeout=5) as conn:conn.execute(statement,args)


def test_initial_stable_cursor_no_content_or_probes_or_read_writes(owner,monkeypatch):
    for target,name in ((main.real_sources,'sources'),(core,'audit')):
        monkeypatch.setattr(target,name,lambda *a,**k:pytest.fail('read feed must not probe or write audit'))
    first=feed(owner)
    assert first['reset_required'] and first['reset_reason']=='initial'
    assert first['domains']==list(changes.DOMAINS)
    assert first['conversation_id']==core.conversation_id()
    assert len(first['cursor'])<=2048
    again=feed(owner,first['cursor'])
    assert again['cursor']==first['cursor'] and again['domains']==[] and not again['reset_required']
    assert again['reset_reason'] is None
    assert owner.get('/api/capabilities').json()['features']['conversation_change_cursor'] is True
    assert owner.get('/api/capabilities').json()['contract_version']=='1.7.0'
    with sqlite3.connect(core.DB_PATH) as conn:
        before=conn.execute('SELECT * FROM conversation_change_clock').fetchall()
    for _ in range(3):feed(owner,first['cursor'])
    with sqlite3.connect(core.DB_PATH) as conn:assert conn.execute('SELECT * FROM conversation_change_clock').fetchall()==before


def test_reading_old_snapshot_does_not_create_a_cursor_poll_loop(owner):
    baseline=feed(owner)
    for _ in range(3):
        assert owner.get('/api/conversation').status_code==200
        assert feed(owner,baseline['cursor'])['domains']==[]


@pytest.mark.parametrize('domain',['conversation','messages','memories','sources','moods','followups','boundary','actions','turns'])
def test_real_table_writes_invalidate_named_domains(owner,domain):
    before=feed(owner);sid=before['conversation_id']
    if domain=='conversation':sql('UPDATE sessions SET title=? WHERE id=?',('new title',sid))
    elif domain=='messages':core.add_message(sid,'user','synthetic message')
    elif domain=='memories':core.add_memory(sid,'fact','synthetic preference')
    elif domain=='sources':core.attach_sources_to_session(sid,[{'connector_id':'local_files','label':'synthetic','text':'source text','understanding':{'facts':[],'inferences':[],'questions':[]},'items':[],'insights':[],'starters':[]}])
    elif domain=='moods':moods.save(core.DB_PATH,sid,'2026-10-30',.2,.3,'synthetic mood',None)
    elif domain=='followups':followups.create(core.DB_PATH,sid,'synthetic', '2099-01-01T12:00:00+00:00','changes-followup-001')
    elif domain=='boundary':companion_boundary.put(core.DB_PATH,sid,expected_revision=0,mode='paused',until=None,time_zone='UTC')
    elif domain=='actions':core.create_action(sid,'reminder','synthetic draft')
    elif domain=='turns':main._turn_store().claim(sid,'changes-turn-001','synthetic')
    after=feed(owner,before['cursor'])
    assert not after['reset_required'] and domain in after['domains']
    assert after['cursor']!=before['cursor']
    assert feed(owner,after['cursor'])['domains']==[]


def test_memory_cas_delete_and_source_withdrawal_propagate_without_retained_content(owner):
    sid=feed(owner)['conversation_id'];memory=core.add_memory(sid,'fact','PRIVATE_SYNTHETIC_MEMORY_ONLY')
    baseline=feed(owner)
    response=owner.patch('/api/memory/'+memory['id'],json={'text':'corrected synthetic','expected_version':memory['version']})
    assert response.status_code==200
    assert 'memories' in feed(owner,baseline['cursor'])['domains']
    baseline=feed(owner)
    assert owner.delete('/api/memory/'+memory['id'],params={'expected_version':response.json()['version']}).status_code==200
    assert 'memories' in feed(owner,baseline['cursor'])['domains']
    core.attach_sources_to_session(sid,[{'connector_id':'local_files','label':'source','text':'PRIVATE_SYNTHETIC_SOURCE_ONLY','understanding':{'facts':[],'inferences':[],'questions':[]},'items':[],'insights':[],'starters':[]}])
    source=core.list_sources(sid)[0];baseline=feed(owner)
    response=owner.post('/api/source/revoke',json={'session_id':sid,'source_id':source['id']});assert response.status_code==200
    after=feed(owner,baseline['cursor']);assert 'sources' in after['domains'] and 'boundary' in after['domains']
    with sqlite3.connect(core.DB_PATH) as conn:
        columns=[row[1] for row in conn.execute('PRAGMA table_info(conversation_change_domains)')]
        assert columns==['session_id','domain','revision']
        metadata=repr(conn.execute('SELECT * FROM conversation_change_domains').fetchall())+repr(conn.execute('SELECT * FROM conversation_change_clock').fetchall())
    assert 'PRIVATE_SYNTHETIC' not in metadata and 'PRIVATE_SYNTHETIC' not in after['cursor']


def test_uncommitted_or_rolled_back_mutations_never_leak_invalidation(owner):
    before=feed(owner);sid=before['conversation_id']
    conn=sqlite3.connect(core.DB_PATH);conn.execute('BEGIN IMMEDIATE');conn.execute('UPDATE sessions SET title=? WHERE id=?',('uncommitted',sid))
    assert feed(owner,before['cursor'])['cursor']==before['cursor']
    conn.rollback();conn.close()
    assert feed(owner,before['cursor'])['cursor']==before['cursor']
    sql('UPDATE sessions SET title=? WHERE id=?',('committed',sid))
    assert feed(owner,before['cursor'])['domains']==['conversation']


def test_snapshot_write_between_feed_reads_is_not_lost(owner,monkeypatch):
    before=feed(owner);original=changes._temporal;done=[]
    def interleaved(conn,sid,current):
        if not done:
            done.append(True);core.add_memory(sid,'fact','committed after reader snapshot')
        return original(conn,sid,current)
    monkeypatch.setattr(changes,'_temporal',interleaved)
    snapshot=feed(owner,before['cursor'])
    assert snapshot['domains']==[] and snapshot['cursor']==before['cursor']
    assert 'memories' in feed(owner,snapshot['cursor'])['domains']


def test_other_sid_changes_do_not_advance_canonical_cursor(owner):
    before=feed(owner)
    other=core.create_session(mode='empty')['session']['id'];assert other!=before['conversation_id']
    core.add_memory(other,'fact','different conversation synthetic')
    core.add_message(other,'user','other conversation only')
    after=feed(owner,before['cursor'])
    assert after['domains']==[] and after['cursor']==before['cursor']


def test_concurrent_commits_keep_monotonic_head_and_bounded_metadata(owner):
    before=feed(owner);sid=before['conversation_id']
    def write(index):core.add_memory(sid,'fact','parallel synthetic '+str(index))
    with ThreadPoolExecutor(6) as pool:list(pool.map(write,range(30)))
    after=feed(owner,before['cursor']);assert 'memories' in after['domains']
    assert changes._decode(after['cursor'])[4]>changes._decode(before['cursor'])[4]
    with sqlite3.connect(core.DB_PATH) as conn:
        assert conn.execute('SELECT COUNT(*) FROM conversation_change_domains WHERE session_id=?',(sid,)).fetchone()[0]<=len(changes.DOMAINS)
    assert feed(owner,after['cursor'])['domains']==[]


def test_noop_sql_updates_do_not_advance_cursor(owner):
    before=feed(owner);sid=before['conversation_id']
    sql('UPDATE sessions SET title=title,state=state WHERE id=?',(sid,))
    assert feed(owner,before['cursor'])['cursor']==before['cursor']


@pytest.mark.parametrize('cursor',['','not+base64','x'*2049,'e30','W10','true'])
def test_malformed_cursors_are_bounded_stable_errors_without_echo(owner,cursor):
    response=owner.get('/api/conversation/changes',params={'after':cursor})
    assert response.status_code==400 and response.json()['error_code']=='invalid_changes_cursor'
    assert response.headers['cache-control']=='no-store'
    assert response.json()['detail']=='Invalid change cursor.'


def test_duplicate_cursor_is_rejected(owner):
    cursor=feed(owner)['cursor'];response=owner.get('/api/conversation/changes',params=[('after',cursor),('after',cursor)])
    assert response.status_code==400 and response.json()['error_code']=='invalid_changes_cursor'


@pytest.mark.parametrize('reason',['identity_changed','ahead','too_old'])
def test_reset_reasons_are_explicit_and_request_full_reread(owner,reason):
    baseline=feed(owner);value=changes._decode(baseline['cursor'])
    if reason=='identity_changed':value[1]='svc_different'
    elif reason=='ahead':value[4]+=100
    else:
        value[4]=0
        sql('UPDATE conversation_change_clock SET sequence=10000 WHERE singleton=1')
        sql('UPDATE sessions SET title=? WHERE id=?',('revision beyond retained window',baseline['conversation_id']))
    after=feed(owner,changes._encode(*value[1:]))
    assert after['reset_required'] and after['reset_reason']==reason and after['domains']==list(changes.DOMAINS)


def test_restart_migration_and_new_database_identity(owner,monkeypatch,tmp_path):
    baseline=feed(owner);sid=baseline['conversation_id'];core.add_message(sid,'user','preserve current content')
    baseline=feed(owner);core.init_db();paired_access.initialize(core.DB_PATH)
    assert feed(owner,baseline['cursor'])['cursor']==baseline['cursor']
    # A new independently initialized database gets its own stable identity.
    monkeypatch.setattr(core,'DB_PATH',str(tmp_path/'replacement.db'));core.init_db();paired_access.initialize(core.DB_PATH);main._turn_store();core.conversation_id()
    after=feed(owner,baseline['cursor'])
    assert after['reset_reason']=='identity_changed' and after['service_instance_id']!=baseline['service_instance_id']


def test_additive_migration_preserves_rows_and_epoch_reset(owner):
    sid=feed(owner)['conversation_id'];moods.save(core.DB_PATH,sid,'2026-10-30',.2,.3,'preserve synthetic diary',None)
    baseline=feed(owner)
    with sqlite3.connect(core.DB_PATH) as conn:
        preserved=conn.execute('SELECT * FROM mood_entries').fetchall()
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'cc_v1_*'").fetchall():conn.execute('DROP TRIGGER "'+name+'"')
        conn.execute('DROP TABLE conversation_change_domains');conn.execute('DROP TABLE conversation_change_clock')
    core.init_db()
    with sqlite3.connect(core.DB_PATH) as conn:assert conn.execute('SELECT * FROM mood_entries').fetchall()==preserved
    assert feed(owner,baseline['cursor'])['reset_reason']=='identity_changed'


def test_deleted_session_cleans_metadata_without_resetting_global_clock(owner):
    baseline=feed(owner);sid=baseline['conversation_id'];core.add_memory(sid,'fact','delete synthetic')
    with sqlite3.connect(core.DB_PATH) as conn:before=conn.execute('SELECT sequence FROM conversation_change_clock').fetchone()[0]
    core.delete_session(sid)
    with sqlite3.connect(core.DB_PATH) as conn:
        assert conn.execute('SELECT COUNT(*) FROM conversation_change_domains WHERE session_id=?',(sid,)).fetchone()[0]==0
        assert conn.execute('SELECT sequence FROM conversation_change_clock').fetchone()[0]>before
    response=owner.get('/api/conversation/changes',params={'after':baseline['cursor']})
    assert response.status_code==409 and response.json()['error_code']=='conversation_not_initialized'
    core.conversation_id();assert feed(owner,baseline['cursor'])['reset_reason']=='identity_changed'


def test_time_alone_changes_delivery_followups_and_boundary_without_writing(owner):
    sid=feed(owner)['conversation_id'];now=datetime(2026,10,30,12,tzinfo=timezone.utc)
    companion_boundary.put(core.DB_PATH,sid,expected_revision=0,mode='until',until=(now+timedelta(minutes=1)).isoformat(),time_zone='UTC',clock=lambda:now)
    message=core.add_message(sid,'assistant','第一段\n\n第二段')
    conn=core.get_db();chat_delivery.register(conn,sid,message['id'],'第一段\n\n第二段',at=now.timestamp());conn.commit();conn.close()
    followups.create(core.DB_PATH,sid,'synthetic scheduled', (now+timedelta(minutes=1)).isoformat(),'time-contact-001',clock=lambda:now)
    first=changes.read(core.DB_PATH,clock=lambda:now)
    with sqlite3.connect(core.DB_PATH) as conn:before=conn.execute('SELECT * FROM conversation_change_clock').fetchall()
    second=changes.read(core.DB_PATH,first['cursor'],clock=lambda:now+timedelta(minutes=2))
    assert {'messages','followups','boundary'}<=set(second['domains']) and not second['reset_required']
    with sqlite3.connect(core.DB_PATH) as conn:assert conn.execute('SELECT * FROM conversation_change_clock').fetchall()==before
    assert changes.read(core.DB_PATH,second['cursor'],clock=lambda:now+timedelta(minutes=2))['domains']==[]


def test_paired_feed_is_allowed_but_identity_sid_and_local_operations_still_blocked(owner):
    grant=owner.post('/api/paired-devices',json={'label':'synthetic remote','confirmed':True}).json()
    remote=TestClient(paired_app.create_remote_app(main.app,lambda:core.DB_PATH,allowed_origins={'https://phone.test'}),base_url='https://phone.test')
    headers={'Authorization':'Bearer '+grant['token'],'X-Echo-Service-Instance':grant['service_instance_id']}
    try:
        baseline=remote.get('/api/conversation/changes',headers=headers);assert baseline.status_code==200
        assert baseline.json()['conversation_id']==grant['conversation_id']
        assert remote.get('/api/conversation/changes',headers={**headers,'X-Echo-Service-Instance':'wrong'}).status_code==409
        assert remote.get('/api/conversation/changes',headers=headers,params={'session_id':'wrong'}).status_code==403
        assert remote.post('/api/conversation/changes',headers=headers).status_code==403
        assert remote.get('/api/settings/model',headers=headers).status_code==403
        core.add_memory(grant['conversation_id'],'fact','remote update discovery')
        after=remote.get('/api/conversation/changes',headers=headers,params={'after':baseline.json()['cursor']})
        assert after.status_code==200 and 'memories' in after.json()['domains']
        assert after.json()['service_instance_id']==grant['service_instance_id']
    finally:remote.close()


def test_unknown_mood_cancel_and_turn_status_invalidate_without_new_content(owner):
    sid=feed(owner)['conversation_id'];baseline=feed(owner)
    response=owner.post('/api/mood-operations/changes-retire-001/cancel',json={
        'session_id':sid,'operation_sha256':'a'*64,'kind':'save','confirmed':True})
    assert response.status_code==200 and response.json()['state']=='cancelled'
    assert feed(owner,baseline['cursor'])['domains']==['moods']
    assert owner.get('/api/moods',params={'session_id':sid}).json()['moods']==[]
    store=main._turn_store();store.claim(sid,'changes-cancel-001','synthetic turn')
    baseline=feed(owner);store.request_cancel(sid,'changes-cancel-001')
    assert feed(owner,baseline['cursor'])['domains']==['turns']


def test_real_revision_retention_is_bounded_and_reset_works(owner):
    baseline=feed(owner);sid=baseline['conversation_id']
    with sqlite3.connect(core.DB_PATH) as conn:
        for index in range(changes.RETENTION_REVISIONS+1):
            conn.execute('UPDATE sessions SET title=? WHERE id=?',('synthetic '+str(index),sid))
        assert conn.execute('SELECT COUNT(*) FROM conversation_change_domains WHERE session_id=?',(sid,)).fetchone()[0]<=len(changes.DOMAINS)
    after=feed(owner,baseline['cursor'])
    assert after['reset_reason']=='too_old' and after['domains']==list(changes.DOMAINS)
    assert feed(owner,after['cursor'])['cursor']==after['cursor']


def test_future_column_migration_resets_once_and_tracks_new_metadata(owner):
    baseline=feed(owner)
    sql('ALTER TABLE sessions ADD COLUMN future_metadata TEXT')
    core.init_db()
    after=feed(owner,baseline['cursor']);assert after['reset_reason']=='identity_changed'
    sql('UPDATE sessions SET future_metadata=? WHERE id=?',('new metadata',after['conversation_id']))
    assert feed(owner,after['cursor'])['domains']==['conversation']


def test_quiet_time_transition_invalidates_without_starting_contact(owner):
    sid=feed(owner)['conversation_id'];now=datetime(2026,10,30,20,tzinfo=timezone.utc)
    followups.create(core.DB_PATH,sid,'quiet synthetic',(now+timedelta(minutes=1)).isoformat(),'quiet-changes-001',
                     quiet_start='22:00',quiet_end='08:00',clock=lambda:now)
    first=changes.read(core.DB_PATH,clock=lambda:now+timedelta(hours=1))
    second=changes.read(core.DB_PATH,first['cursor'],clock=lambda:now+timedelta(hours=2))
    assert second['domains']==['followups']
    with sqlite3.connect(core.DB_PATH) as conn:
        assert conn.execute('SELECT COUNT(*) FROM followup_notification_attempts').fetchone()[0]==0
        assert conn.execute('SELECT status FROM followups').fetchone()[0]=='pending'



def test_tracker_reinstall_preserves_unrelated_custom_triggers(owner):
    sql('CREATE TRIGGER ccXv1Yforeign AFTER INSERT ON messages BEGIN SELECT 1; END')
    sql('ALTER TABLE sessions ADD COLUMN test_reinstall TEXT')
    core.init_db()
    with sqlite3.connect(core.DB_PATH) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name='ccXv1Yforeign'").fetchone()
