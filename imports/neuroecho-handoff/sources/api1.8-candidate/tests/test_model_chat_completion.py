"""Mock the wire contract without sockets, credentials, or real user data."""
import json
import pytest
from server import model


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return self.payload


def test_deepseek_chat_uses_nonthinking_budget(monkeypatch):
    requests = []
    def urlopen(request, timeout):
        requests.append(json.loads(request.data))
        return Response(json.dumps({'choices': [{'finish_reason': 'stop',
                                                  'message': {'content': '我在。'}}]}).encode())
    monkeypatch.setattr(model, '_open_model_request', urlopen)
    client = model.ModelClient('https://api.deepseek.com/v1', 'synthetic', 'deepseek-flash')
    assert client.complete('persona', 'hello') == '我在。'
    assert requests[0]['model'] == 'deepseek-flash'
    assert requests[0]['max_tokens'] == 1200
    assert requests[0]['thinking'] == {'type': 'disabled'}
    assert requests[0]['messages'][0]['content'] == 'persona'


def test_other_openai_compatible_provider_gets_no_deepseek_only_options(monkeypatch):
    requests = []
    def urlopen(request, timeout):
        requests.append(json.loads(request.data))
        return Response(b'{"choices":[{"finish_reason":"stop","message":{"content":"OK"}}]}')
    monkeypatch.setattr(model, '_open_model_request', urlopen)
    assert model.ModelClient('https://example.invalid/v1', 'synthetic', 'x').complete('s', 'u') == 'OK'
    assert 'thinking' not in requests[0]


@pytest.mark.parametrize('payload', [
    {'choices': [{'finish_reason': 'length', 'message': {'content': '不完整的回答'}}]},
    {'choices': [{'finish_reason': 'length', 'message': {'content': None}}]},
])
def test_truncated_response_is_never_treated_as_complete(monkeypatch, payload):
    monkeypatch.setattr(model, '_open_model_request', lambda *a, **kw: Response(json.dumps(payload).encode()))
    with pytest.raises(model.ModelError, match='incomplete'):
        model.ModelClient('https://example.invalid/v1', 'synthetic', 'x').complete('s', 'u')


@pytest.mark.parametrize('response', [b'\xff', b'{"choices":["not a choice"]}'])
def test_malformed_provider_response_raises_model_error(monkeypatch, response):
    monkeypatch.setattr(model, '_open_model_request', lambda *a, **kw: Response(response))
    with pytest.raises(model.ModelError):
        model.ModelClient('https://example.invalid/v1', 'synthetic', 'x').complete('s', 'u')


def test_truncation_shows_failure_in_chat_and_does_not_save_partial(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from server import core
    from server.main import app
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'chat.db'))
    core.init_db()
    fake = model.ModelClient('https://example.invalid/v1', 'synthetic', 'x')
    monkeypatch.setattr(model, 'from_env', lambda: fake)
    body = {'choices': [{'finish_reason': 'length', 'message': {'content': '半句没有说完'}}]}
    monkeypatch.setattr(model, '_open_model_request', lambda *a, **kw: Response(json.dumps(body).encode()))
    client = TestClient(app)
    sid = client.post('/api/session', json={'mode': 'empty'}).json()['session']['id']
    result = client.post('/api/chat', json={'session_id': sid, 'text': '我今天有点累'}).json()
    assert '模型暂时不可用' in result['reply']
    assert '半句没有说完' not in result['reply']
