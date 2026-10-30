"""A delayed stop can truncate only its observed, still-current reply."""
import concurrent.futures
import threading
import time

from fastapi.testclient import TestClient
import pytest

from server import agent_runtime, chat_delivery, core, fallback, main


@pytest.fixture()
def conversation():
    core.init_db()
    sid = core.create_session('empty')['session']['id']
    return TestClient(main.app), sid


def pending(sid, text='合成首段\n\n合成后段'):
    message = core.add_message(sid, 'assistant', text)
    with core.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        chat_delivery.register(conn, sid, message['id'], text, at=time.time() + 3600)
        agent_runtime.persist_proposal(conn, sid, message['id'], {'kind':'reminder','title':'合成草稿'}, 'stamp')
    return message


def state(sid):
    with core.get_db() as conn:
        return tuple(tuple(tuple(row) for row in conn.execute(sql, (sid,))) for sql in (
            'SELECT * FROM messages WHERE session_id=? ORDER BY rowid',
            'SELECT * FROM chat_delivery WHERE session_id=? ORDER BY rowid',
            'SELECT * FROM agent_action_proposals WHERE session_id=? ORDER BY rowid'))


@pytest.mark.parametrize('payload', [None, {}, {'message_id':None}])
def test_legacy_stop_is_explicit_non_mutating_noop(conversation, payload):
    client, sid = conversation
    pending(sid)
    before = state(sid)
    response = client.post(f'/api/session/{sid}/delivery/stop', **({'json':payload} if payload is not None else {}))
    assert response.status_code == 200
    assert response.json() == {'ok':True,'stopped':False,'message_id':None,'reason':'message_id_required'}
    assert state(sid) == before


def test_delayed_target_does_not_touch_any_part_of_new_reply(conversation):
    client, sid = conversation
    old = pending(sid)
    new = pending(sid, '新首段\n\n新后段')
    before = state(sid)
    result = client.post(f'/api/session/{sid}/delivery/stop', json={'message_id':old['id']})
    assert result.json() == {'ok':True,'stopped':False,'message_id':old['id'],'reason':'not_current'}
    assert state(sid) == before
    assert core.get_messages(sid)[-1]['id'] == new['id']
    assert core.get_messages(sid)[-1]['delivery_pending'] is True


def test_exact_target_stops_once_and_removes_only_its_proposal(conversation):
    client, sid = conversation
    old = pending(sid)
    new = pending(sid, '新首段\n\n新后段')
    before = state(sid)
    result = client.post(f'/api/session/{sid}/delivery/stop', json={'message_id':new['id']})
    assert result.json() == {'ok':True,'stopped':True,'message_id':new['id'],'reason':'stopped'}
    after = state(sid)
    assert after[0][-1][3] == '新首段'
    assert after[0][:-1] == before[0][:-1] and after[1][:-1] == before[1][:-1]
    assert len(after[2]) == 1 and after[2][0][0] == old['id']
    result = client.post(f'/api/session/{sid}/delivery/stop', json={'message_id':new['id']})
    assert result.json()['reason'] == 'not_pending' and result.json()['stopped'] is False
    assert state(sid) == after


def test_delivered_or_wrong_session_target_never_changes_state(conversation):
    client, sid = conversation
    message = core.add_message(sid, 'assistant', '单段完整内容')
    before = state(sid)
    assert client.post(f'/api/session/{sid}/delivery/stop',json={'message_id':message['id']}).json()['reason'] == 'not_pending'
    assert state(sid) == before
    delivered = core.add_message(sid, 'assistant', '已经呈现\n\n已经送完')
    with core.get_db() as conn:
        chat_delivery.register(conn,sid,delivered['id'],delivered['text'],at=0)
    before = state(sid)
    assert client.post(f'/api/session/{sid}/delivery/stop',json={'message_id':delivered['id']}).json()['reason'] == 'not_pending'
    assert state(sid) == before
    other = core.create_session('empty')['session']['id']
    foreign = pending(other)
    assert client.post(f'/api/session/{sid}/delivery/stop',json={'message_id':foreign['id']}).json()['reason'] == 'not_current'
    assert state(sid) == before
    assert client.post('/api/session/nonexistent/delivery/stop',json={'message_id':message['id']}).status_code == 404


@pytest.mark.parametrize('value', ['', 42, 'x'*129])
def test_invalid_message_id_is_rejected_without_mutation(conversation, value):
    client, sid = conversation
    pending(sid)
    before = state(sid)
    assert client.post(f'/api/session/{sid}/delivery/stop',json={'message_id':value}).status_code == 422
    assert state(sid) == before


def test_late_stop_rechecks_current_target_after_waiting_for_writer(conversation, monkeypatch):
    client, sid = conversation
    old = pending(sid)
    conn = core.get_db()
    conn.execute('BEGIN IMMEDIATE')
    new_id = core.uid('msg')
    conn.execute('INSERT INTO messages(id,session_id,role,text,created_at) VALUES(?,?,?,?,?)',
                 (new_id, sid, 'assistant', '新首段\n\n新后段', core.now()))
    chat_delivery.register(conn,sid,new_id,'新首段\n\n新后段',at=time.time()+3600)
    attempting_write = threading.Event()
    original_get_db = core.get_db
    class WriteAttempt:
        def __init__(self, connection):
            self.connection = connection
        def __getattr__(self, name):
            return getattr(self.connection, name)
        def execute(self, sql, *args):
            if sql == 'BEGIN IMMEDIATE':
                attempting_write.set()
            return self.connection.execute(sql,*args)
    monkeypatch.setattr(core,'get_db',lambda:WriteAttempt(original_get_db()))
    def stop_old():
        return client.post(f'/api/session/{sid}/delivery/stop',json={'message_id':old['id']})
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(stop_old)
            reached_lock = attempting_write.wait(2)
            conn.commit()
            assert reached_lock, 'The HTTP handler must reach its write lock while the newer reply is uncommitted'
            result = future.result(timeout=5)
        assert result.json()['reason'] == 'not_current' and result.json()['stopped'] is False
        assert core.get_messages(sid)[-1]['id'] == new_id
        assert core.get_messages(sid)[-1]['delivery_pending'] is True
    finally:
        conn.close()


def test_fallback_stop_uses_identical_target_guard_without_starting_server(conversation):
    _, sid = conversation
    message = pending(sid)
    handler = object.__new__(fallback.Handler)
    handler.path = f'/api/session/{sid}/delivery/stop'
    response = []
    handler._body = lambda: {}
    handler._send = lambda code, body: response.append((code,body))
    before = state(sid)
    handler.do_POST()
    assert response[-1][1]['reason'] == 'message_id_required' and state(sid) == before
    handler._body = lambda: {'message_id':message['id']}
    handler.do_POST()
    assert response[-1] == (200,{'ok':True,'stopped':True,'message_id':message['id'],'reason':'stopped'})


def test_stop_schema_and_capability_expose_message_binding(conversation):
    client, _ = conversation
    capabilities = client.get('/api/capabilities').json()
    assert capabilities['features']['chat_delivery_targeted_stop'] is True
    schema = client.get('/openapi.json').json()
    response = schema['paths']['/api/session/{sid}/delivery/stop']['post']['responses']['200']
    assert response['content']['application/json']['schema']['$ref'].endswith('/DeliveryStopResponse')
    assert set(schema['components']['schemas']['DeliveryStopResponse']['required']) == {'ok','stopped','message_id','reason'}
