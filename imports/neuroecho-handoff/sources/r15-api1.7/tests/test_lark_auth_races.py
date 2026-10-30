"""Synthetic authorization state races: no CLI credentials or network."""
import json
import subprocess
import threading
from server import lark, lark_auth, lark_search_auth, lark_auth_coordinator as coordinator


def test_old_document_status_cannot_overwrite_new_pending(monkeypatch):
    monkeypatch.setattr(coordinator, '_active', None)
    monkeypatch.setattr(lark_auth, 'STATE', {'status':'success','url':'','qr':'','error':'','started_at':0,'attempt':1})
    entered, release = threading.Event(), threading.Event()
    real_thread = threading.Thread
    def auth_status():
        if threading.current_thread().name == 'old-status':
            entered.set()
            assert release.wait(3)
        return {'ok':False}
    monkeypatch.setattr(lark, 'auth_status', auth_status)
    monkeypatch.setattr(lark_auth, '_run', lambda *a, **kw: subprocess.CompletedProcess(['fake'], 0, json.dumps({'verification_url':'https://example.invalid/doc','device_code':'fake'}), ''))
    monkeypatch.setattr(lark_auth, '_qr_data_url', lambda _: '')
    class FakeThread:
        def __init__(self, **kwargs): pass
        def start(self): pass
    monkeypatch.setattr(lark_auth.threading, 'Thread', FakeThread)
    t = real_thread(target=lark_auth.status, name='old-status')
    t.start()
    try:
        assert entered.wait(3)
        assert lark_auth.start()['status'] == 'pending'
    finally:
        release.set(); t.join()
    assert lark_auth.STATE['status'] == 'pending'
    assert coordinator.begin('search')[0] == 'conflict'


def test_old_document_worker_cannot_update_or_release_new_reservation(monkeypatch):
    monkeypatch.setattr(coordinator, '_active', None)
    monkeypatch.setattr(lark_auth, 'STATE', {'status':'pending','url':'new','qr':'','error':'','started_at':0,'attempt':2})
    _, old = coordinator.begin('document')
    coordinator.finish('document', old)
    _, current = coordinator.begin('document')
    monkeypatch.setattr(lark_auth, '_run', lambda *a, **kw: subprocess.CompletedProcess(['fake'], 1, '', ''))
    lark_auth._complete('fake', 1, old)
    assert lark_auth.STATE['status'] == 'pending' and lark_auth.STATE['url'] == 'new'
    assert coordinator.begin('search')[0] == 'conflict'
    coordinator.finish('document', current)
    assert coordinator.begin('search')[0] == 'new'
