import json
import subprocess
from server import lark, lark_auth, lark_setup, lark_auth_coordinator as coordinator


def test_setup_url_only_exposes_registration_link():
    assert lark_setup.verification_url('secret https://evil.invalid/page/cli?user_code=x') == ''
    assert lark_setup.verification_url('https://open.feishu.cn/page/cli') == ''
    url = 'https://open.feishu.cn/page/cli?user_code=abc&source=cli'
    assert lark_setup.verification_url('Open: ' + url + '\nsecret') == url


def test_unconfigured_starts_worker_once(monkeypatch):
    monkeypatch.setattr(coordinator, '_active', None)
    monkeypatch.setattr(lark_auth, 'STATE', {})
    monkeypatch.setattr(lark, 'auth_status', lambda: {'ok': False})
    monkeypatch.setattr(lark_auth, '_run', lambda *a, **kw: subprocess.CompletedProcess([], 1, 'not_configured', ''))
    workers = []
    class Worker:
        def __init__(self, **kwargs): workers.append(kwargs)
        def start(self): pass
    monkeypatch.setattr(lark_auth.threading, 'Thread', Worker)
    assert lark_auth.start()['phase'] == 'setup'
    assert lark_auth.start()['status'] == 'starting'
    assert len(workers) == 1
    coordinator.finish('document', workers[0]['args'][1])


def test_setup_then_document_grant_keeps_reservation(monkeypatch):
    monkeypatch.setattr(coordinator, '_active', None)
    monkeypatch.setattr(lark_auth, 'STATE', {'attempt': 1, 'status': 'starting'})
    _, token = coordinator.begin('document')
    seen = []
    def initialize(show):
        show('https://open.feishu.cn/page/cli?user_code=fake')
        seen.append(lark_auth._public())
        assert coordinator.begin('search')[0] == 'conflict'
        return True
    monkeypatch.setattr(lark_setup, 'initialize', initialize)
    monkeypatch.setattr(lark_auth, '_qr_data_url', lambda _: '')
    monkeypatch.setattr(lark_auth, '_run', lambda *a, **kw: subprocess.CompletedProcess([], 0, json.dumps({'verification_url':'https://example.invalid/auth', 'device_code':'private'}), ''))
    def complete(code, attempt, reservation):
        seen.append(lark_auth._public())
        assert code == 'private' and reservation is token
        coordinator.finish('document', reservation)
    monkeypatch.setattr(lark_auth, '_complete', complete)
    lark_auth._initialize(1, token)
    assert [s['phase'] for s in seen] == ['setup', 'authorize']
    assert 'private' not in repr(seen)


def test_setup_failure_clears_links_and_releases(monkeypatch):
    monkeypatch.setattr(coordinator, '_active', None)
    monkeypatch.setattr(lark_auth, 'STATE', {'attempt':1})
    _, token = coordinator.begin('document')
    monkeypatch.setattr(lark_setup, 'initialize', lambda show: False)
    lark_auth._initialize(1, token)
    assert lark_auth.STATE['status'] == 'error'
    assert lark_auth.STATE['url'] == ''
    assert coordinator._active is None
