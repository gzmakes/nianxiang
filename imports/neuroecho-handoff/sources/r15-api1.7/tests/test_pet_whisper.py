from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi.testclient import TestClient

from server import main, pet_whisper


def local_client():
    return TestClient(main.app, base_url="http://127.0.0.1:8787", client=("127.0.0.1", 1234))


def test_whisper_uses_no_user_data_or_chat_context(monkeypatch):
    calls = []

    class Fake:
        def complete(self, system, user, max_tokens):
            calls.append((system, user, max_tokens))
            return '“小鱼转个圈，灵感就来啦～”'

    monkeypatch.setattr(pet_whisper.model, "from_env", lambda: Fake())
    response = local_client().post("/api/pet-whisper", json={"history": "private-secret"})
    assert response.status_code == 200
    assert response.json() == {"available": True, "text": "小鱼转个圈，灵感就来啦～"}
    assert response.headers["cache-control"] == "no-store"
    assert len(calls) == 1 and "private-secret" not in repr(calls)
    assert calls[0][2] == 100 and calls[0][1].startswith("现在是")


def test_whisper_unconfigured_or_failing_model_is_not_fabricated(monkeypatch):
    client = local_client()
    monkeypatch.setattr(pet_whisper.model, "from_env", lambda: None)
    assert client.post("/api/pet-whisper").json() == {"available": False, "text": None}

    class Broken:
        def complete(self, *_args, **_kwargs):
            raise RuntimeError("test failure")

    monkeypatch.setattr(pet_whisper.model, "from_env", lambda: Broken())
    assert client.post("/api/pet-whisper").json() == {"available": False, "text": None}


def test_whisper_does_not_expose_model_to_remote_or_hosted(monkeypatch):
    called = []
    monkeypatch.setattr(pet_whisper, "generate", lambda: called.append(True))
    client = local_client()
    assert client.post("/api/pet-whisper", headers={"Origin": "https://other.example"}).status_code == 403
    remote = TestClient(main.app, base_url="http://127.0.0.1:8787", client=("192.0.2.2", 1234))
    assert remote.post("/api/pet-whisper").status_code == 403
    monkeypatch.setattr(main, "PUBLIC_ORIGIN", "https://example.test")
    assert client.post("/api/pet-whisper").status_code == 403
    assert called == []


def test_overlapping_tabs_fall_back_without_calling_model_again(monkeypatch):
    entered, release = Event(), Event()
    calls = []

    class Slow:
        def complete(self, *_args, **_kwargs):
            calls.append(True)
            entered.set()
            assert release.wait(5), "test must release the pending request"
            return "小鱼在这里～"

    monkeypatch.setattr(pet_whisper.model, "from_env", lambda: Slow())
    first_client, second_client = local_client(), local_client()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_client.post, "/api/pet-whisper")
        try:
            assert entered.wait(5)
            second = pool.submit(second_client.post, "/api/pet-whisper")
            assert second.result(timeout=2).json() == {"available": False, "text": None}
            assert calls == [True]
        finally:
            release.set()
        assert first.result(timeout=5).json() == {"available": True, "text": "小鱼在这里～"}
    assert second_client.post("/api/pet-whisper").json() == {"available": True, "text": "小鱼在这里～"}
    assert calls == [True, True]


def test_generation_lock_is_released_when_model_resolution_or_call_fails(monkeypatch):
    def failed_resolution():
        raise RuntimeError("configuration unavailable")

    monkeypatch.setattr(pet_whisper.model, "from_env", failed_resolution)
    assert local_client().post("/api/pet-whisper").json() == {"available": False, "text": None}

    class Broken:
        def complete(self, *_args, **_kwargs):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr(pet_whisper.model, "from_env", lambda: Broken())
    assert local_client().post("/api/pet-whisper").json() == {"available": False, "text": None}

    class Ready:
        def complete(self, *_args, **_kwargs):
            return "抖抖鱼尾巴～"

    monkeypatch.setattr(pet_whisper.model, "from_env", lambda: Ready())
    assert local_client().post("/api/pet-whisper").json() == {"available": True, "text": "抖抖鱼尾巴～"}
