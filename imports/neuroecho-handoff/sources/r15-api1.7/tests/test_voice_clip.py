"""Voice synthesis is isolated: never launch say/afconvert or access devices."""
import io
from pathlib import Path
from types import SimpleNamespace
import threading
import wave

from fastapi.testclient import TestClient
import pytest

from server import api_contract, chat_delivery, core, main, voice_clip


def wav_bytes(frames=800):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\0\0' * frames)
    return stream.getvalue()


@pytest.fixture(autouse=True)
def never_run_real_speech(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('A voice test attempted to launch a real subprocess')
    monkeypatch.setattr(voice_clip.subprocess, 'run', forbidden)
    monkeypatch.setattr(voice_clip, '_slot', threading.BoundedSemaphore(1))


@pytest.fixture()
def local_speech(monkeypatch):
    monkeypatch.setattr(voice_clip, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(voice_clip, 'os', SimpleNamespace(path=SimpleNamespace(exists=lambda path:True)))
    folders = []
    original = voice_clip.tempfile.TemporaryDirectory
    def directory(*args, **kwargs):
        folder = original(*args, **kwargs)
        folders.append(Path(folder.name))
        return folder
    monkeypatch.setattr(voice_clip.tempfile, 'TemporaryDirectory', directory)
    return folders


@pytest.mark.parametrize('value', ['', '  ', '[表情: happy]', '字'*801])
def test_empty_or_oversize_input_never_starts_subprocess(value):
    with pytest.raises(ValueError):
        voice_clip.synthesize(value)


@pytest.mark.parametrize('platform', ['linux'])
def test_unsupported_platform_fails_without_tool_probe(monkeypatch, platform):
    monkeypatch.setattr(voice_clip,'sys',SimpleNamespace(platform=platform))
    monkeypatch.setattr(voice_clip,'os',SimpleNamespace(path=SimpleNamespace(exists=lambda value:pytest.fail('No probe on unsupported platform'))))
    with pytest.raises(voice_clip.VoiceUnavailable):
        voice_clip.synthesize('合成语音')


def test_missing_system_tools_and_busy_slot_never_launch_process(local_speech, monkeypatch):
    monkeypatch.setattr(voice_clip,'os',SimpleNamespace(path=SimpleNamespace(exists=lambda value:False)))
    with pytest.raises(voice_clip.VoiceUnavailable):
        voice_clip.synthesize('合成语音')
    monkeypatch.setattr(voice_clip,'os',SimpleNamespace(path=SimpleNamespace(exists=lambda value:True)))
    assert voice_clip._slot.acquire(blocking=False)
    try:
        with pytest.raises(voice_clip.VoiceUnavailable):
            voice_clip.synthesize('合成语音')
    finally:
        voice_clip._slot.release()
    assert local_speech == []


def test_wav_output_uses_fixed_commands_stdin_and_cleans_temp(local_speech, monkeypatch):
    expected = wav_bytes()
    calls = []
    def process(argv, **kwargs):
        calls.append((argv,kwargs))
        assert 'shell' not in kwargs and kwargs['check'] is True
        if argv[0] == '/usr/bin/say':
            assert kwargs['input'] == '你好 链接'.encode()
            assert kwargs['timeout'] == 45
            assert argv[1:4] == ['-v','Tingting','-o']
        else:
            assert argv[0] == '/usr/bin/afconvert' and kwargs['timeout'] == 15
            Path(argv[-1]).write_bytes(expected)
    monkeypatch.setattr(voice_clip.subprocess,'run',process)
    assert voice_clip.synthesize('**你好** [链接](https://example.invalid/path)[表情: happy]') == expected
    assert len(calls) == 2
    assert all(not folder.exists() for folder in local_speech)
    assert voice_clip._slot.acquire(blocking=False)
    voice_clip._slot.release()


@pytest.mark.parametrize('failure', ['timeout','oserror','conversion','missing','invalid','short','oversize'])
def test_all_failed_synthesis_cleans_temp_and_releases_slot(local_speech, monkeypatch, failure):
    def process(argv, **kwargs):
        if failure == 'timeout':
            raise voice_clip.subprocess.TimeoutExpired(argv, kwargs['timeout'])
        if failure == 'oserror':
            raise OSError('synthetic unavailable')
        if argv[0] == '/usr/bin/afconvert':
            if failure == 'conversion':
                raise voice_clip.subprocess.CalledProcessError(1,argv)
            if failure == 'missing':
                return
            payload = b'invalid' if failure == 'invalid' else wav_bytes(1 if failure == 'short' else 800)
            Path(argv[-1]).write_bytes(payload)
    monkeypatch.setattr(voice_clip.subprocess,'run',process)
    if failure == 'oversize':
        monkeypatch.setattr(voice_clip,'MAX_BYTES',100)
    with pytest.raises(voice_clip.VoiceUnavailable):
        voice_clip.synthesize('合成测试')
    assert len(local_speech) == 1 and not local_speech[0].exists()
    assert voice_clip._slot.acquire(blocking=False)
    voice_clip._slot.release()


@pytest.fixture()
def conversation():
    core.init_db()
    sid = core.create_session('empty', persona_id='whale')['session']['id']
    message = core.add_message(sid,'assistant','合成语音内容')
    return TestClient(main.app), sid, message


def request_voice(client, sid, mid, **extra):
    return client.post('/api/voice/clip',json={'session_id':sid,'message_id':mid,**extra})


def test_api_returns_only_requested_assistant_audio_and_no_store(conversation, monkeypatch):
    client,sid,message = conversation
    calls = []
    def synthesize(text):
        calls.append(text)
        return wav_bytes()
    monkeypatch.setattr(voice_clip,'synthesize',synthesize)
    response = request_voice(client,sid,message['id'])
    assert response.status_code == 200 and response.content == wav_bytes()
    assert response.headers['content-type'] == 'audio/wav'
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert calls == [message['text']]


def test_api_rejects_unknown_user_foreign_and_pending_messages_before_synthesis(conversation, monkeypatch):
    client,sid,message = conversation
    monkeypatch.setattr(voice_clip,'synthesize',lambda value:pytest.fail('Invalid target must not synthesize'))
    assert request_voice(client,'not-found',message['id']).status_code == 404
    assert request_voice(client,sid,'not-found').status_code == 404
    user = core.add_message(sid,'user','合成用户文字')
    assert request_voice(client,sid,user['id']).status_code == 404
    other = core.create_session('empty')['session']['id']
    assert request_voice(client,other,message['id']).status_code == 404
    pending = core.add_message(sid,'assistant','首段\n\n后段')
    with core.get_db() as conn:
        chat_delivery.register(conn,sid,pending['id'],pending['text'],at=10**12)
    assert request_voice(client,sid,pending['id']).status_code == 409


@pytest.mark.parametrize('body', [
    {'session_id':'s','message_id':''}, {'session_id':'s','message_id':'x'*129},
    {'session_id':'s','message_id':'m','text':'arbitrary input'},
    {'session_id':'s','message_id':'m','path':'/tmp/unused'},
])
def test_api_input_is_ids_only(conversation, body):
    client,_,_ = conversation
    assert client.post('/api/voice/clip',json=body).status_code == 422


@pytest.mark.parametrize('text', ['', '[表情: happy]', '字'*801])
def test_api_speech_input_limits_are_422_without_process(conversation, text):
    client,sid,_ = conversation
    message = core.add_message(sid,'assistant',text)
    response = request_voice(client,sid,message['id'])
    assert response.status_code == 422 and response.json()['error_code'] == 'validation_error'


def test_api_unsupported_service_platform_is_503_and_metadata_is_honest(conversation, monkeypatch):
    client,sid,message = conversation
    monkeypatch.setattr(voice_clip,'sys',SimpleNamespace(platform='win32'))
    monkeypatch.setattr(api_contract,'sys',SimpleNamespace(platform='win32'))
    monkeypatch.setattr(voice_clip.voice_settings, 'load_settings', lambda: {'tts': {'enabled': False}})
    monkeypatch.setattr(voice_clip.voice_settings, 'load_settings', lambda: {'tts': {'enabled': False}})
    response = request_voice(client,sid,message['id'])
    assert response.status_code == 503 and response.json()['error_code'] == 'service_unavailable'
    capabilities = client.get('/api/capabilities').json()
    assert capabilities['features']['voice_clip_from_assistant_message'] is False
    assert capabilities['platform_status']['voice_clip'] == 'platform_unsupported'


@pytest.mark.parametrize('change', ['delete_session','suppress','text','revoke_source','correct_memory'])
def test_api_discards_audio_if_target_or_context_changes_during_synthesis(conversation, monkeypatch, change):
    client,sid,message = conversation
    source_id = None
    memory = None
    if change == 'revoke_source':
        core.attach_source_to_empty_session(sid,'合成资料','合成资料内容',core.build_understanding('合成资料内容','paste'),[],[],[])
        source_id = core.list_sources(sid)[0]['id']
    if change == 'correct_memory':
        memory = core.add_memory(sid,'fact','合成旧偏好',source='用户手动添加')
    def synthesize(text):
        if change == 'delete_session':
            core.delete_session(sid)
        elif change in ('suppress','text'):
            with core.get_db() as conn:
                sql = 'UPDATE messages SET suppressed=1 WHERE id=?' if change == 'suppress' else "UPDATE messages SET text='合成新内容' WHERE id=?"
                conn.execute(sql,(message['id'],))
        elif change == 'revoke_source':
            core.revoke_source(sid,source_id)
        else:
            core.update_memory(memory['id'],text='合成新偏好')
        return wav_bytes()
    monkeypatch.setattr(voice_clip,'synthesize',synthesize)
    response = request_voice(client,sid,message['id'])
    assert response.status_code == 409
    assert response.headers.get('content-type','').startswith('application/json')
    assert not response.content.startswith(b'RIFF')
