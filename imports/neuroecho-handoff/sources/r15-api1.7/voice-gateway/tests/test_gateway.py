import hashlib
import io
import wave

from fastapi.testclient import TestClient

from app import main


def wav_bytes():
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 3200)
    return out.getvalue()


def test_health_is_public_and_status_requires_token(monkeypatch):
    token = "test-token"
    monkeypatch.setattr(main, "settings", main.Settings(token_hashes=frozenset({hashlib.sha256(token.encode()).hexdigest()}), tts_url="", ref_audio_path="x", prompt_text="", prompt_lang="zh", text_lang="zh", max_chars=800, max_audio_bytes=2_000_000, timeout_seconds=2, max_queue=10, bind_host="127.0.0.1", bind_port=9881))
    client = TestClient(main.app)
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/v1/status").status_code == 401
    assert client.get("/v1/status", headers={"Authorization": "Bearer revoked-token"}).status_code == 401
    assert client.get("/v1/status", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_tts_validates_persona_and_returns_wav(monkeypatch):
    token = "test-token"
    monkeypatch.setattr(main, "settings", main.Settings(token_hashes=frozenset({hashlib.sha256(token.encode()).hexdigest()}), tts_url="", ref_audio_path="x", prompt_text="", prompt_lang="zh", text_lang="zh", max_chars=800, max_audio_bytes=2_000_000, timeout_seconds=2, max_queue=10, bind_host="127.0.0.1", bind_port=9881))
    monkeypatch.setattr(main, "synthesize", lambda text, persona: wav_bytes())
    client = TestClient(main.app)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/v1/tts", json={"persona_id": "nianxiang", "text": "hi"}, headers=headers).status_code == 422
    response = client.post("/v1/tts", json={"persona_id": "whale", "text": "你好"}, headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content[:4] == b"RIFF"


def test_tts_rejects_extra_fields_and_empty_text(monkeypatch):
    token = "test-token"
    monkeypatch.setattr(main, "settings", main.Settings(token_hashes=frozenset({hashlib.sha256(token.encode()).hexdigest()}), tts_url="", ref_audio_path="x", prompt_text="", prompt_lang="zh", text_lang="zh", max_chars=3, max_audio_bytes=2_000_000, timeout_seconds=2, max_queue=10, bind_host="127.0.0.1", bind_port=9881))
    client = TestClient(main.app)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/v1/tts", json={"persona_id": "whale", "text": ""}, headers=headers).status_code == 422
    assert client.post("/v1/tts", json={"persona_id": "whale", "text": "abc", "ref_audio_path": "x"}, headers=headers).status_code == 422
