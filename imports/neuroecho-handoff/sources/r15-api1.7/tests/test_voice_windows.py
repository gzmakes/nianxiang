import io
import json
import wave

import pytest

from server import asr_service, voice_clip, voice_settings


def wav_bytes(frames=800, rate=32000):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(rate); audio.writeframes(b'\0\0' * frames)
    return stream.getvalue()


def test_windows_tts_posts_whale_reference(monkeypatch, tmp_path):
    reference = tmp_path / 'fish.wav'; reference.write_bytes(b'ref')
    config = {'tts': {'enabled': True, 'base_url': 'http://127.0.0.1:9880', 'ref_audio_path': str(reference), 'prompt_text': '参考句', 'timeout_seconds': 3}}
    calls = []
    class Reply:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, *args): return wav_bytes(frames=4000)
    def open_url(request, timeout): calls.append((request, timeout)); return Reply()
    monkeypatch.setattr(voice_settings, 'load_settings', lambda: config)
    monkeypatch.setattr(voice_clip.sys, 'platform', 'win32')
    monkeypatch.setattr(voice_clip.urllib.request, 'urlopen', open_url)
    assert voice_clip.synthesize('你好', persona_id='whale').startswith(b'RIFF')
    payload = json.loads(calls[0][0].data)
    assert payload['ref_audio_path'] == str(reference) and payload['prompt_text'] == '参考句' and calls[0][1] == 3


def test_windows_tts_rejects_non_whale(monkeypatch):
    monkeypatch.setattr(voice_clip.sys, 'platform', 'win32')
    with pytest.raises(voice_clip.VoiceUnavailable): voice_clip.synthesize('你好', persona_id='nianxiang')


def test_asr_converts_and_calls_sdk_then_cleans(monkeypatch, tmp_path):
    converted = tmp_path / 'converted.wav'; converted.write_bytes(wav_bytes(rate=16000)); calls = []
    monkeypatch.setattr(asr_service, 'run_ffmpeg', lambda *args: converted)
    monkeypatch.setattr(asr_service, 'recognize_wav', lambda payload, settings: calls.append(payload) or {'Result': '你好', 'RequestId': 'req-1'})
    result = asr_service.transcribe_bytes(b'webm', 'audio/webm', settings={'asr': {'enabled': True, 'max_upload_bytes': 4_000_000, 'max_converted_wav_bytes': 2_100_000}})
    assert result == {'text': '你好', 'request_id': 'req-1', 'audio_duration_ms': 50} and calls[0].startswith(b'RIFF')


def test_asr_empty_result_is_error(monkeypatch, tmp_path):
    converted = tmp_path / 'converted.wav'; converted.write_bytes(wav_bytes(rate=16000))
    monkeypatch.setattr(asr_service, 'run_ffmpeg', lambda *args: converted)
    monkeypatch.setattr(asr_service, 'recognize_wav', lambda *args: {'Result': '', 'RequestId': 'req-2'})
    with pytest.raises(asr_service.TranscriptionError): asr_service.transcribe_bytes(b'audio', 'audio/webm', settings={'asr': {'enabled': True}})


def test_credentials_without_profile_are_reported_missing(monkeypatch):
    class EmptyCredential:
        def get_credential(self):
            return None
    from tencentcloud.common import credential
    monkeypatch.setattr(credential, 'ProfileCredential', EmptyCredential)
    assert voice_settings._credentials_available() is False
    with pytest.raises(asr_service.TranscriptionError, match='凭证未配置'):
        asr_service.recognize_wav(b'RIFF', {'asr': {}})


def test_portable_voice_settings_accept_environment_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv('XINJI_ASR_ENABLED', 'false')
    monkeypatch.setenv('XINJI_FFMPEG_PATH', str(tmp_path / 'ffmpeg.exe'))
    monkeypatch.setenv('XINJI_TTS_REFERENCE_AUDIO', str(tmp_path / 'fish.wav'))
    settings = voice_settings.load_settings()
    assert settings['asr']['enabled'] is False
    assert settings['asr']['ffmpeg_path'] == str(tmp_path / 'ffmpeg.exe')
    assert settings['tts']['ref_audio_path'] == str(tmp_path / 'fish.wav')
