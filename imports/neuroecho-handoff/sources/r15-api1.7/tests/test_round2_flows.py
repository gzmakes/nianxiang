import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from server import core, main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path/'flow.db'))
    core.init_db()
    monkeypatch.setattr(main, '_enrich', lambda value: value)
    return TestClient(main.app)


def empty(client):
    return client.post('/api/session', json={'mode':'empty'}).json()['session']['id']


def source(cid):
    return {'ok':True, 'connector':{'id':cid,'name':cid}, 'title':'合成资料',
            'items':[{'title':'合成标题','summary':'合成内容','meta':'test'}],
            'understanding':{'facts':['合成资料的事实'],'inferences':[],'questions':[]},
            'insights':[], 'starters':[]}


@pytest.mark.parametrize('cid', ['gmail','notion','git','github','apple_calendar','apple_reminders'])
def test_any_supported_source_keeps_current_dialog_and_user_memory(client, cid):
    sid=empty(client)
    prior=core.add_message(sid,'user','我今天想先把话讲完')
    personal=core.add_memory(sid,'fact','我希望先听我说',source='用户手动添加',status='confirmed')
    preview=main._save_preview(cid, source(cid))
    endpoint='/api/'+cid+'/start' if cid in ('gmail','notion') else '/api/onboarding/real/start'
    payload={'preview_id':preview,'session_id':sid}
    if cid not in ('gmail','notion'): payload['source_id']=cid
    response=client.post(endpoint,json=payload)
    assert response.status_code==200,response.text
    result=response.json()
    assert result['session']['id']==sid
    assert prior['id'] in [message['id'] for message in result['messages']]
    assert personal['id'] in [memory['id'] for memory in result['memories']]
    core.revoke_source(sid)
    assert personal['id'] in [memory['id'] for memory in core.list_memories(sid)]
    assert not core.get_session_context(sid)


def test_second_reviewed_source_keeps_the_first_source_and_dialog(client):
    sid=empty(client)
    core.attach_source_to_empty_session(sid,'已有来源','text',source('git')['understanding'],[],[],[])
    preview=main._save_preview('gmail',source('gmail'))
    result=client.post('/api/gmail/start',json={'session_id':sid,'preview_id':preview})
    assert result.status_code==200,result.text
    assert len(result.json()['context']['sources'])==2
    assert result.json()['session']['id']==sid


def test_request_replay_and_precise_answer_identity(client,monkeypatch):
    calls=[]
    class Model:
        model='synthetic'
        def complete(self,system,prompt):
            calls.append(prompt)
            return '合成模型回复'
    monkeypatch.setattr(core.model,'from_env',lambda:Model())
    sid=empty(client)
    payload={'session_id':sid,'request_id':str(uuid.uuid4()),'text':'想把今天的一段经历讲完'}
    first=client.post('/api/chat',json=payload).json()
    second=client.post('/api/chat',json=payload).json()
    assert len(calls)==1
    assert first['assistant_message_id'] in [m['id'] for m in core.get_messages(sid)]
    assert second['reply']==first['reply']
    assert sum(m['role']=='user' for m in core.get_messages(sid))==1
    assert client.post('/api/chat',json={**payload,'text':'不同内容'}).status_code==409


def test_supplement_before_display_suppresses_completed_reply_and_model_history(client,monkeypatch):
    prompts=[]
    class Model:
        model='synthetic'
        def complete(self,system,prompt):
            prompts.append(prompt)
            return '旧回复不应再次进入模型' if len(prompts)==1 else '我听见你的补充了'
    monkeypatch.setattr(core.model,'from_env',lambda:Model())
    sid=empty(client);rid=str(uuid.uuid4())
    body={'session_id':sid,'request_id':rid,'text':'今天有点乱'}
    first=client.post('/api/chat',json=body).json()
    cancel=client.post('/api/chat/turn/'+rid+'/cancel',json={'session_id':sid}).json()
    assert cancel['result']['cancelled']
    assert first['assistant_message_id'] not in [m['id'] for m in core.get_messages(sid)]
    replay=client.post('/api/chat',json=body).json()
    assert replay['cancelled'] and not replay['reply']
    client.post('/api/chat',json={'session_id':sid,'request_id':str(uuid.uuid4()),'text':'我补充一下刚才的事'})
    assert '旧回复不应再次进入模型' not in prompts[-1]
    assert '今天有点乱' in prompts[-1]


def test_cancelling_inflight_turn_retains_input_and_recovers_cancelled_state(client,monkeypatch):
    started,release=threading.Event(),threading.Event()
    class Model:
        model='synthetic'
        def complete(self,system,prompt):
            started.set();assert release.wait(4);return '不应保存的旧回复'
    monkeypatch.setattr(core.model,'from_env',lambda:Model())
    sid=empty(client);rid=str(uuid.uuid4())
    with ThreadPoolExecutor() as pool:
        future=pool.submit(client.post,'/api/chat',json={'session_id':sid,'request_id':rid,'text':'我还没讲完'})
        assert started.wait(3)
        pending=client.post('/api/chat/turn/'+rid+'/cancel',json={'session_id':sid}).json()
        assert pending['status']=='running' and pending['cancel_requested']
        release.set();result=future.result().json()
    assert result['cancelled']
    assert not any(m['text']=='不应保存的旧回复' for m in core.get_messages(sid))
    status=client.get('/api/chat/turn/'+rid,params={'session_id':sid}).json()
    assert status['status']=='cancelled' and status['result']['user_message_id']==result['user_message_id']
    core.delete_session(sid)
    assert client.get('/api/chat/turn/'+rid,params={'session_id':sid}).status_code==404


def test_recent_context_preserves_more_than_three_exchanges(client,monkeypatch):
    captured=[]
    class Model:
        model='synthetic'
        def complete(self,system,prompt): captured.append(prompt);return '合成回复'
    monkeypatch.setattr(core.model,'from_env',lambda:Model())
    sid=empty(client)
    core.add_message(sid,'user','周末的小故事叫“合成的风筝”')
    for i in range(8): core.add_message(sid,'assistant' if i%2 else 'user','合成的日常聊天'+str(i))
    client.post('/api/chat',json={'session_id':sid,'request_id':str(uuid.uuid4()),'text':'刚才那个故事叫什么？'})
    assert '合成的风筝' in captured[-1]
