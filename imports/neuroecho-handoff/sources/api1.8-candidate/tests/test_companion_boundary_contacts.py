"""F5 policy acceptance: synthetic clocks/SQLite, never actual notifications."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import sqlite3
import threading

from fastapi.testclient import TestClient
import pytest

from server import agent_runtime, companion_boundary as boundary, core, followups, main, proactive_policy as policy

NOW=datetime(2026,10,30,12,tzinfo=timezone.utc)


@pytest.fixture()
def app_context(monkeypatch):
    clock=[NOW]
    monkeypatch.setattr(followups,'_current',lambda callback:callback() if callback else clock[0])
    monkeypatch.setattr(core.model,'from_env',lambda:None)
    core.init_db()
    sid=core.create_session('empty')['session']['id']
    return TestClient(main.app),sid,clock


def create(sid,clock,**kw):
    body=dict(content='合成联系',due_at=(clock[0]+timedelta(minutes=1)).isoformat(),request_id=core.uid('request'),allow_contact=True)
    body.update(kw)
    return followups.create(core.DB_PATH,sid,**body)


def claim(sid,item,channel='in_app'):
    return policy.claim(core.DB_PATH,sid,item['id'],item['due_at'],channel=channel)


def change(sid,mode='paused',until=None):
    old=boundary.get(core.DB_PATH,sid)
    return boundary.put(core.DB_PATH,sid,expected_revision=old['revision'],mode=mode,until=until,time_zone=old['time_zone'])


def test_default_passive_tasks_migration_and_idempotent_fields(app_context):
    _,sid,clock=app_context
    item=create(sid,clock,allow_contact=False)
    clock[0]+=timedelta(minutes=2)
    row=followups.list_for_session(core.DB_PATH,sid)[0]
    assert row['due'] and row['review_available'] and not row['available']
    assert claim(sid,item)['reason']=='contact_not_allowed'
    again=followups.create(core.DB_PATH,sid,item['content'],item['due_at'],item['request_id'])
    assert again['id']==item['id']
    with pytest.raises(followups.FollowupConflict):
        followups.create(core.DB_PATH,sid,item['content'],item['due_at'],item['request_id'],allow_contact=True)
    with core.get_db() as conn:
        before=[dict(x) for x in conn.execute('SELECT * FROM followups')]
        followups.init_schema(conn);policy.init_schema(conn)
        assert [dict(x) for x in conn.execute('SELECT * FROM followups')]==before


def test_legacy_schema_adds_contact_false_without_rewriting_tasks(tmp_path):
    path=tmp_path/'old.db';conn=sqlite3.connect(path)
    conn.execute('''CREATE TABLE followups(id TEXT PRIMARY KEY,session_id TEXT,request_id TEXT,content TEXT,due_at TEXT,status TEXT,created_at TEXT,updated_at TEXT)''')
    conn.execute('INSERT INTO followups VALUES(?,?,?,?,?,?,?,?)',('f','s','r','旧任务',NOW.isoformat(),'pending','old','old'))
    followups.init_schema(conn);policy.init_schema(conn);conn.commit()
    row=conn.execute('SELECT allow_contact,contact_window_minutes,content,status,request_id FROM followups').fetchone()
    assert row==(0,30,'旧任务','pending','r')
    conn.close()


@pytest.mark.parametrize('field,value', [('allow_contact',1),('contact_window_minutes',4),('contact_window_minutes',181),('contact_window_minutes',True),('contact_topic','')])
def test_contact_validation_is_strict(app_context,field,value):
    _,sid,clock=app_context
    with pytest.raises(ValueError):create(sid,clock,**{field:value})


def test_boundary_confirmed_api_cas_and_no_task_side_effect(app_context):
    client,sid,clock=app_context;item=create(sid,clock)
    url='/api/companion-boundary';old=client.get(url,params={'session_id':sid}).json()
    assert old==dict(revision=0,mode='active',until=None,time_zone='UTC',suppression_revision=0)
    body={'session_id':sid,'expected_revision':0,'confirmed':False,'mode':'paused','until':None,'time_zone':'Asia/Shanghai'}
    assert client.put(url,json=body).status_code==400
    result=client.put(url,json={**body,'confirmed':True})
    assert result.status_code==200 and result.json()['suppression_revision']==1
    conflict=client.put(url,json={**body,'confirmed':True,'mode':'active'})
    assert conflict.status_code==409 and conflict.json()['error_code']=='boundary_conflict' and conflict.json()['current_revision']==1
    assert followups.list_for_session(core.DB_PATH,sid)[0]['status']=='pending'
    assert client.get(url,params={'session_id':'missing'}).status_code==404


def test_concurrent_cas_and_session_isolation(app_context):
    _,sid,_=app_context
    def put(mode):
        try:return boundary.put(core.DB_PATH,sid,expected_revision=0,mode=mode,until=None,time_zone='UTC')
        except boundary.BoundaryConflict:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(put,['paused','active']))
    assert results.count('conflict')==1
    other=core.create_session('empty')['session']['id']
    assert boundary.get(core.DB_PATH,other)['revision']==0


def test_chat_control_is_immediate_even_budget_exhausted_and_model_off(app_context,monkeypatch):
    client,sid,clock=app_context
    item=create(sid,clock);clock[0]+=timedelta(minutes=1);reserved=claim(sid,item)
    assert reserved['claimed']
    monkeypatch.setattr(core,'CHAT_BUDGET',0)
    monkeypatch.setattr(core.model,'from_env',lambda:pytest.fail('A refusal must not depend on a model request'))
    response=client.post('/api/chat',json={'session_id':sid,'text':'今天先别问','time_zone':'Asia/Shanghai','request_id':'r9-refusal-clock'})
    assert response.status_code==200 and response.json()['action']=='boundary.changed'
    status=boundary.get(core.DB_PATH,sid)
    assert status['mode']=='until' and status['until'].startswith('2026-10-30T16:00:00')
    assert policy.recheck(core.DB_PATH,sid,reserved['claim_id'])['reason']=='boundary_changed'
    assert followups.list_for_session(core.DB_PATH,sid)[0]['status']=='pending'
    # The saved ID cannot be replayed with a different device-time-zone payload.
    assert client.post('/api/chat',json={'session_id':sid,'text':'今天先别问','time_zone':'UTC','request_id':'r9-refusal-clock'}).status_code==409


@pytest.mark.parametrize('text',['同事说今天先别问','“今天先别问”','今天先别问？','文件内容：不用提醒我','如果今天先别问会怎样','我不希望你马上给建议'])
def test_only_direct_user_control_changes_boundary(app_context,text):
    _,sid,_=app_context
    core.add_message(sid,'user',text)
    assert boundary.get(core.DB_PATH,sid)['revision']==0


@pytest.mark.parametrize('text,mode',[
    ('今天先别问了，我想自己待一会儿。','until'),
    ('今天先别问，我想“自己静一静”。','until'),
    ('先安静一下，我会回来。','paused'),
    ('先安静一下\n我会回来。','paused'),
])
def test_opening_direct_clause_survives_explanation_or_later_quotes(app_context,text,mode):
    _,sid,_=app_context
    core.add_message(sid,'user',text,time_zone='Asia/Shanghai')
    assert boundary.get(core.DB_PATH,sid)['mode']==mode


@pytest.mark.parametrize('text',[
    '今天先别问是什么意思？','朋友说今天先别问，我不知道怎么办。',
    '“今天先别问”，他这样说。','今天先别问吗，我在问这个表达。',
])
def test_quoted_recounted_or_question_opening_is_not_a_command(app_context,text):
    _,sid,_=app_context
    core.add_message(sid,'user',text)
    assert boundary.get(core.DB_PATH,sid)['revision']==0


def test_old_pending_fingerprint_does_not_gain_null_zone(app_context):
    client,sid,_=app_context;request='r9-old-pending-record';text='旧的未决合成请求'
    main._turn_store().claim(sid,request,text,options={'memory_proposals':False})
    result=client.post('/api/chat',json={'session_id':sid,'text':text,'request_id':request})
    assert result.status_code==202 and result.json()['status']=='running'
    assert client.post('/api/chat',json={'session_id':sid,'text':text,'request_id':request,'time_zone':'UTC'}).status_code==409


def test_cross_channel_atomic_claim_and_topic_normalization(app_context):
    _,sid,clock=app_context
    policy.set_settings(core.DB_PATH,sid,enabled=True,time_zone='UTC',quiet_start='22:00',quiet_end='08:00',cooldown_minutes=60,daily_limit=3)
    one=create(sid,clock,contact_topic=' ＰＬＡＮ  Alpha ')
    two=create(sid,clock,contact_topic='plan alpha')
    clock[0]+=timedelta(minutes=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda pair:claim(sid,*pair),[(one,'in_app'),(two,'system')]))
    assert sum(x['claimed'] for x in results)==1
    assert next(x for x in results if not x['claimed'])['reason']=='topic_window_claimed'
    winner=next(x for x in results if x['claimed'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        checks=list(pool.map(lambda _:policy.recheck(core.DB_PATH,sid,winner['claim_id']),range(2)))
    assert sum(x['allowed'] for x in checks)==1
    first=policy.finish(core.DB_PATH,sid,winner['claim_id'],'submitted')
    assert policy.finish(core.DB_PATH,sid,winner['claim_id'],'submitted')==first


def test_exact_expiry_and_short_claim_ttl_no_catchup(app_context):
    _,sid,clock=app_context;item=create(sid,clock,contact_window_minutes=5)
    clock[0]+=timedelta(minutes=1);reserved=claim(sid,item);assert reserved['claimed']
    clock[0]+=timedelta(seconds=60)
    assert policy.recheck(core.DB_PATH,sid,reserved['claim_id'])['reason']=='claim_expired'
    clock[0]=followups._utc(item['due_at'])+timedelta(minutes=5)
    assert claim(sid,item)['reason']=='expired'
    assert followups.list_for_session(core.DB_PATH,sid)[0]['review_available']
    assert not followups.list_for_session(core.DB_PATH,sid)[0]['available']


def test_pause_restore_does_not_revive_existing_claim_or_missed_task(app_context):
    _,sid,clock=app_context;item=create(sid,clock)
    clock[0]+=timedelta(minutes=1);reserved=claim(sid,item)
    change(sid);clock[0]+=timedelta(seconds=1);change(sid,'active')
    assert policy.recheck(core.DB_PATH,sid,reserved['claim_id'])['reason']=='boundary_changed'
    with pytest.raises(followups.FollowupConflict):policy.finish(core.DB_PATH,sid,reserved['claim_id'],'submitted')
    assert claim(sid,item)['claimed'] is False
    fresh=create(sid,clock,contact_topic='另一话题');clock[0]+=timedelta(minutes=1)
    # Failed/unknown attempts still consume cooldown, even after a resume.
    assert claim(sid,fresh)['reason']=='cooldown'


def test_until_expiry_does_not_replay_items_due_during_silence(app_context):
    _,sid,clock=app_context
    change(sid,'until',(clock[0]+timedelta(minutes=3)).isoformat())
    item=create(sid,clock)
    clock[0]+=timedelta(minutes=3)
    assert boundary.get(core.DB_PATH,sid)['mode']=='active'
    assert claim(sid,item)['reason']=='suppressed_occurrence'


def test_source_revocation_invalidates_claim_and_queued_proposal(app_context):
    _,sid,clock=app_context
    core.attach_source_to_empty_session(sid,'合成来源','演示资料',core.build_understanding('演示资料','paste'),[],[],[])
    source=core.list_sources(sid)[0]['id'];item=create(sid,clock)
    future=create(sid,clock,due_at=(clock[0]+timedelta(minutes=10)).isoformat(),contact_topic='未来已排队')
    message=core.add_message(sid,'assistant','合成旧建议')
    with core.get_db() as conn:
        agent_runtime.persist_proposal(conn,sid,message['id'],{'kind':'reminder','title':'旧草稿'},agent_runtime.context_stamp(conn,sid))
    clock[0]+=timedelta(minutes=1);reserved=claim(sid,item);assert reserved['claimed']
    core.revoke_source(sid,source)
    assert policy.recheck(core.DB_PATH,sid,reserved['claim_id'])['reason']=='boundary_changed'
    with core.get_db() as conn:assert conn.execute('SELECT COUNT(*) FROM agent_action_proposals WHERE session_id=?',(sid,)).fetchone()[0]==0
    clock[0]+=timedelta(minutes=10)
    assert claim(sid,future)['reason']=='boundary_changed'
    assert followups.list_for_session(core.DB_PATH,sid)[0]['status']=='pending'


def test_future_unclaimed_contact_also_expires_after_refusal_or_source_change(app_context):
    _,sid,clock=app_context
    item=create(sid,clock)
    change(sid);change(sid,'active')
    clock[0]+=timedelta(minutes=1)
    assert claim(sid,item)['reason']=='boundary_changed'
    assert followups.list_for_session(core.DB_PATH,sid)[0]['review_available']
    # Replaying the same request is not a new consent, even with allow_contact true.
    again=followups.create(core.DB_PATH,sid,item['content'],item['due_at'],item['request_id'],allow_contact=True)
    assert again['id']==item['id'] and not again['contact_eligible']


def test_quiet_window_elapsed_never_catches_up_after_open(app_context):
    _,sid,clock=app_context
    item=create(sid,clock,quiet_start='12:00',quiet_end='12:10',contact_window_minutes=5)
    clock[0]+=timedelta(minutes=1)
    assert claim(sid,item)['reason']=='item_quiet'
    clock[0]+=timedelta(minutes=10)
    assert claim(sid,item)['reason']=='expired'
    assert followups.list_for_session(core.DB_PATH,sid)[0]['status']=='pending'


def test_refusal_and_user_turn_rollback_together_on_invalid_zone(app_context):
    _,sid,_=app_context
    before=core.get_messages(sid)
    with pytest.raises(ValueError):core.add_message(sid,'user','今天先别问',time_zone='not/a-zone')
    assert core.get_messages(sid)==before and boundary.get(core.DB_PATH,sid)['revision']==0


@pytest.mark.parametrize('utc,zone,expected',[
    ('2026-03-08T06:00:00+00:00','America/New_York','2026-03-09T04:00:00'),
    ('2026-11-01T05:00:00+00:00','America/New_York','2026-11-02T05:00:00'),
])
def test_today_uses_next_local_midnight_across_dst(app_context,utc,zone,expected):
    _,sid,clock=app_context;clock[0]=datetime.fromisoformat(utc)
    core.add_message(sid,'user','今天先别问',time_zone=zone)
    assert boundary.get(core.DB_PATH,sid)['until'].startswith(expected)


def test_refusal_during_generation_cannot_commit_stale_reply(app_context,monkeypatch):
    _,sid,_=app_context;started=threading.Event();release=threading.Event()
    class Fake:
        model='synthetic'
        def complete(self,*args):started.set();assert release.wait(3);return '不应保存的旧提醒草稿'
    monkeypatch.setattr(core.model,'from_env',lambda:Fake())
    with ThreadPoolExecutor(max_workers=1) as pool:
        running=pool.submit(core.generate_reply,sid,'帮我想想今天做什么')
        try:
            assert started.wait(3)
            core.add_message(sid,'user','先安静')
        finally:release.set()
        result=running.result(timeout=5)
    assert result['action']=='model.stale'
    assert all('不应保存' not in x['text'] for x in core.get_messages(sid))


def test_contact_api_typed_receipts_no_os_and_boundary_invalidates_late_finish(app_context):
    client,sid,clock=app_context;item=create(sid,clock);clock[0]+=timedelta(minutes=1)
    result=client.post(f"/api/followups/{item['id']}/contact/claim",json={'session_id':sid,'occurrence_at':item['due_at'],'channel':'in_app'})
    assert result.status_code==200 and result.json()['claimed'] and result.json()['channel']=='in_app'
    cid=result.json()['claim_id']
    check=client.post(f'/api/followup-contacts/{cid}/recheck',json={'session_id':sid}).json()
    assert check['allowed'] and check['followup_id']==item['id'] and check['claim_id']==cid
    change(sid)
    finish=client.post(f'/api/followup-contacts/{cid}/finish',json={'session_id':sid,'state':'submitted'})
    assert finish.status_code==409 and finish.json()['error_code']=='contact_conflict'
    assert client.get('/api/capabilities').json()['contract_version']=='1.8.0'


@pytest.mark.parametrize('utc,reason',[
    ('2026-10-30T18:00:00+00:00','quiet'),  # 02:00 Shanghai; UTC itself is daytime.
    ('2026-10-30T02:00:00+00:00',None),     # 10:00 Shanghai; UTC itself is quiet.
])
def test_unconfigured_notifications_use_explicit_contact_zone(app_context,utc,reason):
    _,sid,clock=app_context;clock[0]=datetime.fromisoformat(utc)
    item=create(sid,clock,time_zone='Asia/Shanghai')
    clock[0]+=timedelta(minutes=1)
    assert policy.get_settings(core.DB_PATH,sid)['configured'] is False
    result=claim(sid,item)
    assert result['reason']==reason and result['claimed'] is (reason is None)
    presented=followups.list_for_session(core.DB_PATH,sid)[0]
    # A successful claim consumes the opportunity; a blocked one stays quiet.
    assert not presented['contact_eligible']
    assert presented['contact_reason']==('already_claimed' if reason is None else reason)


def test_explicit_notification_settings_zone_overrides_contact_default(app_context):
    _,sid,clock=app_context;clock[0]=datetime.fromisoformat('2026-10-30T18:00:00+00:00')
    policy.set_settings(core.DB_PATH,sid,enabled=False,time_zone='UTC',quiet_start='22:00',quiet_end='08:00',cooldown_minutes=60,daily_limit=3)
    item=create(sid,clock,time_zone='Asia/Shanghai');clock[0]+=timedelta(minutes=1)
    assert claim(sid,item)['claimed']  # User explicitly configured UTC; do not silently replace it.
