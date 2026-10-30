"""Transport constraints tested with synthetic settings and request stubs only."""
import json
from pathlib import Path
import urllib.request

import pytest
from fastapi.testclient import TestClient
from server import core, main, model, model_settings


@pytest.mark.parametrize('url', [
    'http://example.invalid/v1', 'http://localhost.example.invalid/v1',
    'http://localhost./v1', 'http://127.0.0.2/v1', 'http://127.1/v1',
    'http://0x7f000001/v1', 'http://[::ffff:127.0.0.1]/v1',
    'http://%6cocalhost/v1', 'http://localhost:0/v1',
    'http://localhost@remote.invalid/v1', 'http://remote.invalid\\@localhost/v1',
    'https://remote.invalid/v1?credential=x', 'https://remote.invalid/v1#fragment',
    'https://remote.invalid/with\tcontrol', 'ftp://localhost/v1',
])
def test_invalid_or_unsafe_addresses_rejected_at_save_and_before_request(url, tmp_path, monkeypatch):
    core.init_db()
    monkeypatch.setattr(model, '_open_model_request', lambda *a, **kw: pytest.fail('unsafe URL attempted a request'))
    with TestClient(main.app) as client:
        response = client.post('/api/settings/model', json={'base_url':url, 'api_key':'synthetic', 'model':'m'})
        assert response.status_code == 400
        assert not Path(model_settings.PATH).exists()
    with pytest.raises(ValueError):
        model_settings.save(url, 'synthetic', 'm')
    client = model.ModelClient(url, 'synthetic', 'm')
    with pytest.raises(model.ModelError):
        client.complete('private synthetic context', 'text')
    with pytest.raises(model.ModelError):
        client.complete_tools([{'role':'user','content':'private synthetic context'}], [])


@pytest.mark.parametrize('url', [
    'https://remote.invalid/v1', 'https://localhost:8443/v1',
    'http://localhost:11434/v1', 'http://LOCALHOST/v1',
    'http://127.0.0.1:11434/v1', 'http://[::1]:11434/v1',
])
def test_https_and_exact_loopback_http_are_allowed(url):
    assert model_settings.is_safe_model_url(url)
    assert model_settings.save(url, 'synthetic', 'm')['configured'] is True


@pytest.mark.parametrize('source', ['environment', 'old_file'])
def test_unsafe_existing_configuration_cannot_mark_ready_or_call_network(source, monkeypatch):
    if source == 'environment':
        monkeypatch.setenv('XINJI_MODEL_BASE_URL', 'http://remote.invalid/v1')
        monkeypatch.setenv('XINJI_MODEL_API_KEY', 'synthetic')
        monkeypatch.setenv('XINJI_MODEL_NAME', 'm')
    else:
        Path(model_settings.PATH).write_text(json.dumps({'base_url':'http://remote.invalid/v1', 'api_key':'synthetic', 'model':'m'}))
    monkeypatch.setattr(model, '_open_model_request', lambda *a, **kw: pytest.fail('unsafe URL attempted a request'))
    assert model_settings.redacted()['configured'] is False
    assert model.from_env() is None
    assert model.test_connection()['ok'] is False


def test_mutating_url_after_client_creation_still_cannot_send_bearer(monkeypatch):
    client = model.ModelClient('https://safe.invalid/v1', 'synthetic', 'm')
    client.base_url = 'http://remote.invalid/v1'
    monkeypatch.setattr(model, '_open_model_request', lambda *a, **kw: pytest.fail('unsafe URL attempted a request'))
    with pytest.raises(model.ModelError):
        client.complete('private synthetic context', 'text')
    with pytest.raises(model.ModelError):
        client.complete_tools([], [])


@pytest.mark.parametrize('url', ['http://localhost/v1', 'http://127.0.0.1/v1', 'http://[::1]/v1'])
def test_loopback_http_disables_environment_proxies(monkeypatch, url):
    captured = []
    class FakeOpener:
        def open(self, request, timeout):
            return 'synthetic response'
    def opener(*handlers):
        captured.extend(handlers)
        return FakeOpener()
    monkeypatch.setattr(urllib.request, 'build_opener', opener)
    request = urllib.request.Request(url, headers={'Authorization':'Bearer synthetic'})
    assert model._open_model_request(request, timeout=1) == 'synthetic response'
    assert any(isinstance(h, urllib.request.ProxyHandler) and not h.proxies for h in captured)
    assert any(isinstance(h, model._NoModelRedirect) for h in captured)


def test_remote_https_keeps_environment_proxy_configuration(monkeypatch):
    captured = []
    class FakeOpener:
        def open(self, request, timeout):
            return 'synthetic response'
    def opener(*handlers):
        captured.extend(handlers)
        return FakeOpener()
    monkeypatch.setattr(urllib.request, 'build_opener', opener)
    request = urllib.request.Request('https://remote.invalid/v1', headers={'Authorization': 'Bearer synthetic'})
    assert model._open_model_request(request, timeout=1) == 'synthetic response'
    assert not any(isinstance(h, urllib.request.ProxyHandler) for h in captured)
    assert any(isinstance(h, model._NoModelRedirect) for h in captured)


@pytest.mark.parametrize('status', [301, 302, 303, 307, 308])
def test_model_redirects_are_rejected_without_forwarding_request(status):
    handler = model._NoModelRedirect()
    original = urllib.request.Request('https://safe.invalid/v1', headers={'Authorization': 'Bearer synthetic'})
    assert handler.redirect_request(original, None, status, 'redirect', {}, 'https://other.invalid') is None
