from types import SimpleNamespace
from server import core, chat_delivery
from fastapi.testclient import TestClient
from server.main import app


def test_api_reopens_and_stops_actual_ordered_parts(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path/'delivery.db'))
    core.init_db()
    clock = SimpleNamespace(value=100.0)
    monkeypatch.setattr(chat_delivery, 'time', SimpleNamespace(time=lambda: clock.value))
    class Fake:
        model = 'synthetic'
        def complete(self, system, prompt): return '第一段\n\n第二段\n\n第三段\n\n第四段\n\n第五段'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    client = TestClient(app)
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    res = client.post('/api/chat', json={'session_id':sid, 'text':'来聊聊'})
    assert res.status_code == 200
    assistant = res.json()['messages'][-1]
    assert assistant['bubbles'] == ['第一段'] and assistant['delivery_pending']
    clock.value = 100.9
    seen = client.get('/api/session/' + sid).json()['messages'][-1]
    assert seen['bubbles'] == ['第一段','第二段']
    stopped = client.post('/api/session/' + sid + '/delivery/stop', json={'message_id':seen['id']}).json()
    assert stopped == {'ok':True, 'stopped':True, 'message_id':seen['id'], 'reason':'stopped'}
    clock.value = 999
    final = client.get('/api/session/' + sid).json()['messages'][-1]
    assert final['bubbles'] == ['第一段','第二段'] and not final['delivery_pending']
    assert core.get_messages(sid)[-1]['text'] == '第一段\n\n第二段'


def test_context_change_drops_hidden_proposal(tmp_path, monkeypatch):
    from server import agent_runtime
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path/'delivery.db'))
    core.init_db(); sid = core.create_session(mode='empty')['session']['id']
    clock = SimpleNamespace(value=100.0)
    monkeypatch.setattr(chat_delivery, 'time', SimpleNamespace(time=lambda: clock.value))
    db=core.get_db(); db.execute('BEGIN IMMEDIATE')
    db.execute("INSERT INTO messages(id,session_id,role,text,created_at) VALUES('m',?,'assistant',?,?)", (sid,'已见\n\n没见',core.now()))
    chat_delivery.register(db,sid,'m','已见\n\n没见')
    agent_runtime.persist_proposal(db,sid,'m',{'kind':'reminder','title':'测试'},'stamp')
    core._invalidate_history(db,{sid}); db.commit()
    assert db.execute("SELECT COUNT(*) FROM agent_action_proposals").fetchone()[0] == 0
    assert db.execute("SELECT text FROM messages WHERE id='m'").fetchone()[0] == '已见'
    db.close()
