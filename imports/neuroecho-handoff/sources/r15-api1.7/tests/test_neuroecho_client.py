import json
import time

import pytest
from fastapi.testclient import TestClient

from server import core, neuroecho_client
from server.main import app


def _envelope(utterance="你好", *, available=True, stamp=1000.0, transport=0.2):
    snapshot = {
        "schema_version": "neuroecho.multimodal.v1",
        "session_id": "remote-session",
        "snapshot_id": "snapshot-1",
        "generated_at_unix_s": stamp,
        "mode": "live",
        "context": {"utterance": utterance, "interaction_id": "interaction-1", "source": "windows"},
        "policy_constraints": {"audio_allowed": True, "user_requested_silence": False},
        "intervals_s": {"eeg": 5, "decision": 10},
        "eeg": {"valid": False, "attention_score": None, "valence_score": None,
                "age_s": 0, "source": "external_live", "raw": {"live": False, "age_s": 0}},
        "heart": {"valid": False, "bpm": None, "age_s": 0},
        "scene": {"valid": False, "scene_summary": None, "age_s": 0},
        "decision": {"valid": True, "age_s": 0, "executed_code": "B",
                     "action": "TEXT_BRIEF", "channel": "text",
                     "model_version": "route3-D_all32_41", "decision_id": "decision-1"},
        "backend_handoff": {"interaction_id": "interaction-1", "decision_id": "decision-1",
                             "dispatch_recommended": True, "chat_generation_owner": "teammate_backend"},
    }
    return {"schema_version": "neuroecho.remote.v1", "available": available,
            "reason": None if available else "windows_publisher_stale", "relay": {"transport_age_s": transport},
            "snapshot": snapshot if available else None}


def test_validate_remote_envelope_maps_decision_and_filters_modalities():
    out = neuroecho_client.validate_envelope(_envelope(), received_at=1000.8)
    assert out["available"] is True
    assert out["source_utterance"] == "你好"
    assert out["decision"] == {
        "code": "B", "action": "TEXT_BRIEF", "channel": "text", "mode": "short_text",
        "content_intent": None, "decision_id": "decision-1", "interaction_id": "interaction-1",
        "utterance": "你好",
    }
    assert out["observations"] == {}
    assert out["expires_at_unix_s"] == pytest.approx(1007.8)


def test_validate_remote_envelope_fails_closed_on_stale_or_unavailable():
    stale = neuroecho_client.validate_envelope(_envelope(stamp=1000, transport=7.5), received_at=1001)
    assert stale == {"available": False, "reason": "expired_in_transit_or_receiver_clock_out_of_sync"}
    unavailable = neuroecho_client.validate_envelope(_envelope(available=False), received_at=1000)
    assert unavailable == {"available": False, "reason": "windows_publisher_stale"}


def test_fetch_latest_uses_bearer_and_no_redirect(monkeypatch):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return json.dumps(_envelope(stamp=time.time() - 0.1)).encode()

    class Opener:
        def open(self, request, timeout):
            seen["url"] = request.full_url
            seen["auth"] = request.headers.get("Authorization")
            seen["timeout"] = timeout
            return Response()

    monkeypatch.setattr(neuroecho_client, "connection_config", lambda: {
        "base_url": "https://example.test", "channel": "nianxiang-c23cb89fe6a9", "token": "x" * 32,
    })
    out = neuroecho_client.fetch_latest(opener=Opener())
    assert out["available"] is True
    assert seen == {
        "url": "https://example.test/api/v1/share/nianxiang-c23cb89fe6a9",
        "auth": "Bearer " + "x" * 32,
        "timeout": 4.0,
    }


def test_chat_falls_back_when_neuroecho_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "chat.db"))
    core.init_db()

    class FakeModel:
        model = "test-model"

        def complete(self, system, user):
            assert "当前人格" in system
            return "普通聊天仍然可用。"

    monkeypatch.setattr(core.model, "from_env", lambda: FakeModel())
    monkeypatch.setattr(neuroecho_client, "status", lambda: {"configured": True, "read_only": True})

    def unavailable():
        raise neuroecho_client.NeuroEchoUnavailable("read_failed_timeout")

    monkeypatch.setattr(neuroecho_client, "fetch_latest", unavailable)
    sid = TestClient(app).post("/api/session", json={"mode": "empty"}).json()["session"]["id"]
    response = TestClient(app).post("/api/chat", json={"session_id": sid, "text": "你好"})
    assert response.status_code == 200
    assert response.json()["reply"].startswith("普通聊天仍然可用。")
    events = TestClient(app).get(f"/api/audit?session_id={sid}").json()["events"]
    assert any(event["action"] == "neuroecho.unavailable" for event in events)


def test_chat_uses_validated_neuroecho_mode_without_replacing_persona_or_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "chat.db"))
    core.init_db()

    class FakeModel:
        model = "test-model"

        def complete(self, system, user):
            assert "【NeuroEcho 已校验的辅助信息】" in user
            assert "short_text" in user
            assert "【产品人格：念响】" in system
            return "我在，先接住你这句话。"

    remote = neuroecho_client.validate_envelope(_envelope("你好", stamp=time.time() - 0.1), received_at=time.time())
    monkeypatch.setattr(neuroecho_client, "status", lambda: {"configured": True, "read_only": True})
    monkeypatch.setattr(neuroecho_client, "fetch_latest", lambda: remote)
    monkeypatch.setattr(core.model, "from_env", lambda: FakeModel())
    sid = TestClient(app).post("/api/session", json={"mode": "empty", "persona_id": "nianxiang"}).json()["session"]["id"]
    response = TestClient(app).post("/api/chat", json={"session_id": sid, "text": "你好"})
    assert response.status_code == 200
    assert response.json()["reply"].startswith("我在，先接住你这句话。")


def test_remote_no_action_is_silent_and_does_not_call_content_model(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "chat.db"))
    core.init_db()
    remote = neuroecho_client.validate_envelope(_envelope("我想先安静", stamp=time.time() - 0.1), received_at=time.time())
    remote["decision"].update(code="A", action="NO_ACTION", channel="none", mode="quiet")
    monkeypatch.setattr(neuroecho_client, "status", lambda: {"configured": True, "read_only": True})
    monkeypatch.setattr(neuroecho_client, "fetch_latest", lambda: remote)

    def unexpected_model():
        raise AssertionError("quiet decision must not resolve the content model")

    monkeypatch.setattr(core.model, "from_env", unexpected_model)
    sid = TestClient(app).post("/api/session", json={"mode": "empty"}).json()["session"]["id"]
    response = TestClient(app).post("/api/chat", json={"session_id": sid, "text": "我想先安静"})
    assert response.status_code == 200
    assert response.json()["reply"] == ""
    assert response.json()["action"] == "neuroecho.quiet"
