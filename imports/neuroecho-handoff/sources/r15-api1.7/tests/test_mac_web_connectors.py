import io
import json
import subprocess
import threading

from fastapi.testclient import TestClient

from server import apple_source, cli_runtime, connector_auth, gmail_cli_source, main


def test_login_url_allowlist_and_token_rejection():
    assert connector_auth.extract_link('github', 'https://github.com/login/device')
    for url in ('https://github.com.evil.invalid/login/device', 'https://evil.invalid/token',
                'https://github.com/login/device?access_token=private', 'https://github.com/user/repo',
                'https://private@github.com/login/device'):
        assert connector_auth.extract_link('github', url) == ''
    assert connector_auth.extract_link('gmail', 'https://accounts.google.com/o/oauth2/auth?state=opaque')


def test_duplicate_login_reuses_worker_and_never_runs_a_shell(monkeypatch):
    monkeypatch.setattr(connector_auth, 'JOBS', {})
    monkeypatch.setattr(cli_runtime, 'resolve', lambda *a: '/installed/gh')
    workers = []
    class Thread:
        def __init__(self, **kw): workers.append(kw)
        def start(self): pass
    monkeypatch.setattr(connector_auth.threading, 'Thread', Thread)
    assert connector_auth.start('github')['status'] == 'starting'
    assert connector_auth.start('github')['status'] == 'starting'
    assert len(workers) == 1


def test_cli_output_is_not_forwarded_to_login_state(monkeypatch):
    job = {'status': 'starting'}
    monkeypatch.setattr(connector_auth, 'JOBS', {'github': job})
    calls = []
    class Process:
        stdout = io.StringIO('private-access-token\nFirst copy your one-time code: ABCD-1234\nhttps://github.com/login/device\n')
        def __init__(self, args, **kw): calls.append((args, kw))
        def wait(self): return 0
        def poll(self): return 0
        def kill(self): raise AssertionError('finished process')
    monkeypatch.setattr(connector_auth.subprocess, 'Popen', Process)
    connector_auth._run('github', '/installed/gh', job)
    assert job['status'] == 'success'
    assert job['url'] == job['code'] == ''
    assert 'private-access-token' not in repr(job)
    assert not calls[0][1].get('shell')
    assert calls[0][1]['stdin'] == subprocess.DEVNULL
    assert '--web' in calls[0][0]


def test_failed_login_cannot_report_success_or_leak_output(monkeypatch):
    job = {'status': 'starting'}
    monkeypatch.setattr(connector_auth, 'JOBS', {'gmail': job})
    class Process:
        stdout = io.StringIO('client_secret=private\n')
        def __init__(self, args, **kw):
            assert args[-2:] == ['--scopes', gmail_cli_source.SCOPE]
        def wait(self): return 1
        def poll(self): return 1
    monkeypatch.setattr(connector_auth.subprocess, 'Popen', Process)
    connector_auth._run('gmail', '/installed/gws', job)
    assert job['status'] == 'error'
    assert 'private' not in repr(job)
    assert 'OAuth' in job['message']


def test_login_routes_are_local_guarded_and_provider_restricted(monkeypatch):
    client = TestClient(main.app)
    monkeypatch.setattr(cli_runtime, 'resolve', lambda *a: None)
    monkeypatch.setattr(connector_auth, 'JOBS', {})
    assert client.post('/api/connector-auth/unknown/start').status_code == 404
    response = client.post('/api/connector-auth/notion/start')
    assert response.status_code == 200 and response.json()['status'] == 'needs_install'
    assert client.post('/api/connector-auth/gmail/start', headers={'Origin': 'https://evil.invalid'}).status_code == 403
    assert client.get('/api/connector-auth/gmail/status').json()['status'] == 'idle'


def test_gmail_cli_reads_only_headers_without_query_or_marking_read(monkeypatch):
    calls = []
    monkeypatch.setattr(gmail_cli_source, 'executable', lambda: '/installed/gws')
    def run(args, **kw):
        params = json.loads(args[-1]); calls.append((args, params, kw))
        data = {'messages': [{'id': 'synthetic'}]} if 'list' in args else {
            'payload': {'headers': [{'name': 'Subject', 'value': 'Synthetic mail'}, {'name': 'From', 'value': 'example@example.invalid'}],
                        'body': {'data': 'DO-NOT-USE'}}, 'snippet': 'DO-NOT-USE'}
        return subprocess.CompletedProcess(args, 0, json.dumps(data), '')
    monkeypatch.setattr(gmail_cli_source.subprocess, 'run', run)
    result = gmail_cli_source.read()
    assert result['ok'] and result['items'][0]['title'] == 'Synthetic mail'
    assert 'DO-NOT-USE' not in repr(result)
    assert calls[0][1] == {'userId': 'me', 'labelIds': ['INBOX', 'UNREAD'], 'maxResults': 5}
    assert calls[1][1]['format'] == 'metadata'
    assert all('q' not in params and not kw.get('shell') for _, params, kw in calls)


def test_gmail_cli_failure_and_empty_are_not_synthetic_data(monkeypatch):
    monkeypatch.setattr(gmail_cli_source, '_get', lambda *a: {'messages': []})
    assert not gmail_cli_source.read()['ok']
    def failed(*a): raise RuntimeError('private account')
    monkeypatch.setattr(gmail_cli_source, '_get', failed)
    assert 'private account' not in repr(gmail_cli_source.read())


def test_gmail_cli_and_legacy_request_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(main.gmail_cli_source, 'read', lambda: calls.append('cli') or {'ok': False, 'error': 'test'})
    monkeypatch.setattr(main.gmail_source, 'read', lambda a, p: calls.append((a, p)) or {'ok': False, 'error': 'test'})
    client = TestClient(main.app)
    assert client.post('/api/gmail/preview', json={'method': 'cli'}).status_code == 200
    assert client.post('/api/gmail/preview', json={'address': 'synthetic', 'password': 'test'}).status_code == 200
    assert calls == ['cli', ('synthetic', 'test')]
    assert client.post('/api/gmail/preview', json={'method': 'shell'}).status_code == 422


def test_mac_runtime_finds_finder_private_install(tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(cli_runtime.shutil, 'which', lambda _: None)
    binary = tmp_path / '.nianxiang/tools/node_modules/.bin/ntn'
    binary.parent.mkdir(parents=True); binary.touch()
    monkeypatch.setattr(cli_runtime.os, 'access', lambda *a: True)
    assert cli_runtime.resolve('ntn') == str(binary)
    assert '/opt/homebrew/bin' in cli_runtime.environment()['PATH']


def test_apple_read_scripts_bound_items_and_non_mac_is_honest(monkeypatch):
    for script in (apple_source.CALENDAR_SCRIPT, apple_source.REMINDERS_SCRIPT):
        assert script.count('if itemCount >= 8 then exit repeat') == 2
        assert 'make new' not in script
    monkeypatch.setattr(apple_source, 'platform_supported', lambda: False)
    monkeypatch.setattr(apple_source, '_run', lambda _: (_ for _ in ()).throw(AssertionError('must not run')))
    assert apple_source.read_calendar()['error_code'] == 'platform_unsupported'
    assert apple_source.read_reminders()['error_code'] == 'platform_unsupported'
