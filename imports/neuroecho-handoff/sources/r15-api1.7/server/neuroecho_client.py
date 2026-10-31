"""Read-only NeuroEcho v1 remote share client.

The handoff package intentionally gives a teammate only a read credential.  This
module therefore never calls the owner/model endpoints and never writes to the
remote service.  Invalid, stale, synthetic, or incomplete envelopes are
treated as unavailable so the caller can keep the normal R15 chat path.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


ACTION_MAP = {
    "A": {"action": "NO_ACTION", "channel": "none", "mode": "quiet"},
    "B": {"action": "TEXT_BRIEF", "channel": "text", "mode": "short_text"},
    "C": {"action": "VOICE_BRIEF", "channel": "voice", "mode": "short_voice"},
    "D": {"action": "TEXT_STEPS", "channel": "text", "mode": "steps"},
    "E": {"action": "TEXT_CLARIFY", "channel": "text", "mode": "clarify"},
    # F is a text support offer, never the silent listen state.
    "F": {"action": "TEXT_SUPPORT_OFFER", "channel": "text", "mode": "short_text",
          "content_intent": "offer_to_listen"},
}

DEFAULT_TIMEOUT = 4.0
MAX_RESPONSE_BYTES = 262_144


class NeuroEchoUnavailable(Exception):
    """Raised for configuration, transport, schema, and freshness failures."""


def _finite(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _connection_from_file(path: Path) -> tuple[str, str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # never expose file contents or token
        raise NeuroEchoUnavailable("connection_file_invalid") from exc
    return data.get("base_url"), data.get("channel"), data.get("read_token")


def connection_config() -> dict:
    """Resolve environment configuration without returning the bearer token."""
    base = os.getenv("NEUROECHO_BASE_URL", "").strip()
    channel = os.getenv("NEUROECHO_CHANNEL", "").strip()
    token = os.getenv("NEUROECHO_READ_TOKEN", "").strip()
    file_name = os.getenv("NEUROECHO_CONNECTION_FILE", "").strip()
    if file_name and not (base and channel and token):
        base, channel, token = _connection_from_file(Path(file_name))
        base = base.strip() if isinstance(base, str) else base
        channel = channel.strip() if isinstance(channel, str) else channel
        token = token.strip() if isinstance(token, str) else token
    return {"base_url": base, "channel": channel, "token": token}


def _share_url(base: str, channel: str) -> str:
    if not isinstance(base, str):
        raise NeuroEchoUnavailable("invalid_base_url")
    parsed = urlsplit(base)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise NeuroEchoUnavailable("https_base_required")
    if (not isinstance(channel, str) or not channel.isascii()
            or not channel or not channel.replace("-", "").isalnum()):
        raise NeuroEchoUnavailable("invalid_channel")
    return base.rstrip("/") + "/api/v1/share/" + channel


def _advance_to_receipt(snapshot: dict, lag: float) -> None:
    """Apply the handoff reader's last-hop age checks in memory."""
    fields = {
        "eeg": ("attention_score", "valence_score"),
        "heart": ("bpm",),
        "scene": ("scene_summary", "activity"),
        "decision": ("action", "channel", "executed_code", "raw_code",
                     "probabilities", "preview_text"),
    }
    intervals = snapshot.get("intervals_s", {})
    eeg_interval = intervals.get("eeg", 5) if isinstance(intervals, dict) else 5
    decision_interval = intervals.get("decision", 10) if isinstance(intervals, dict) else 10
    ttl = {"eeg": eeg_interval + 5 if eeg_interval in (5, 10) else 10,
           "heart": 15, "scene": 25, "decision": decision_interval + 10}
    for kind, names in fields.items():
        item = snapshot[kind]
        age = item.get("age_s")
        good = _finite(age) and age >= 0
        item["age_s"] = round(age + lag, 3) if good else None
        if not good or item["age_s"] > ttl[kind] or item.get("valid") is not True:
            item.update(valid=False, reason=item.get("reason") or "expired_before_receipt")
            for name in names:
                item[name] = None
    raw = snapshot["eeg"].get("raw")
    raw_age = raw.get("age_s")
    raw["age_s"] = raw_age + lag if _finite(raw_age) and raw_age >= 0 else None
    if raw.get("live") is not True or raw["age_s"] is None or raw["age_s"] >= 1.5:
        raw["live"] = False
        snapshot["eeg"].update(valid=False, attention_score=None, valence_score=None,
                                reason="raw_stale_before_receipt")
    brain = snapshot.get("brain_state")
    if isinstance(brain, dict):
        brain["age_s"] = snapshot["eeg"]["age_s"]
        if snapshot["eeg"].get("valid") is not True:
            brain.update(valid=False, attention=None, valence=None,
                         raw_attention=None, raw_valence=None, history=[])
    spectrum = snapshot.get("spectrum")
    if isinstance(spectrum, dict):
        age = spectrum.get("age_s")
        spectrum["age_s"] = age + lag if _finite(age) and age >= 0 else None
        if (not raw["live"] or spectrum["age_s"] is None
                or spectrum["age_s"] > 2.5):
            spectrum.update(valid=False, relative_power_pct=None)
    if snapshot["decision"].get("valid") is not True:
        snapshot["backend_handoff"].update(dispatch_recommended=False, decision_id=None)
    snapshot["generated_at_unix_s"] += lag
    transport = snapshot.setdefault("remote_transport", {})
    transport["receiver_transit_s"] = round(lag, 3)
    transport["transport_age_s"] = transport.get("transport_age_s", 0) + lag


def _modality_valid(snapshot: dict, kind: str, now: float, stamp: float) -> bool:
    item = snapshot.get(kind)
    if not isinstance(item, dict) or item.get("valid") is not True:
        return False
    age = item.get("age_s")
    if not _finite(age) or age < 0:
        return False
    intervals = snapshot.get("intervals_s") or {}
    eeg_interval = intervals.get("eeg", 5)
    ttl = (eeg_interval + 5 if eeg_interval in (5, 10) else 10) if kind == "eeg" else 15 if kind == "heart" else 25
    if age + (now - stamp) > ttl or item.get("mode", "live") != "live":
        return False
    if item.get("source") in ("synthetic", "simulated", "replay", "public_replay"):
        return False
    if kind == "eeg":
        raw = item.get("raw")
        return (isinstance(raw, dict) and raw.get("live") is True and _finite(raw.get("age_s"))
                and raw["age_s"] >= 0 and raw["age_s"] + (now - stamp) < 1.5
                and item.get("source") == "external_live"
                and item.get("model_version") == "neuroecho-v3-reference-20261031"
                and _finite(item.get("attention_score")) and 0 <= item["attention_score"] <= 100
                and _finite(item.get("valence_score")) and -1 <= item["valence_score"] <= 1)
    if kind == "heart":
        return (item.get("source") in ("apple_watch_via_heartcast", "heartcast")
                and item.get("measurement_kind") == "heart_rate_bpm_not_raw_ecg"
                and item.get("sensor_contact") is not False
                and (item.get("sensor_contact") is None or type(item.get("sensor_contact")) is bool)
                and _finite(item.get("bpm")) and 20 <= item["bpm"] <= 250)
    summary = item.get("scene_summary")
    uncertainties = item.get("uncertainties", [])
    return (item.get("capture_source") in ("glasses_whep", "user_selected_glasses_window")
            and isinstance(summary, str) and bool(summary.strip()) and len(summary) <= 400
            and isinstance(uncertainties, list) and len(uncertainties) <= 6
            and all(isinstance(value, str) and len(value) <= 200 for value in uncertainties))


def _validated_decision(snapshot: dict, now: float, stamp: float) -> dict | None:
    decision = snapshot.get("decision")
    handoff = snapshot.get("backend_handoff")
    constraints = snapshot.get("policy_constraints")
    context = snapshot.get("context")
    if not all(isinstance(value, dict) for value in (decision, handoff, constraints, context)):
        return None
    code = decision.get("executed_code")
    spec = ACTION_MAP.get(code)
    if (spec is None or decision.get("valid") is not True
            or not _finite(decision.get("age_s")) or decision["age_s"] < 0
            or decision["age_s"] + (now - stamp) > 20
            or decision.get("model_version") != "route3-D_all32_41"
            or decision.get("action") != spec["action"]
            or decision.get("channel") != spec["channel"]
            or decision.get("input_snapshot_id") not in (None, snapshot.get("snapshot_id"))):
        return None
    if constraints.get("user_requested_silence") is not False:
        return None
    if spec["channel"] == "voice" and constraints.get("audio_allowed") is not True:
        return None
    interaction = context.get("interaction_id")
    if (not isinstance(interaction, str) or not interaction
            or interaction != handoff.get("interaction_id")
            or not isinstance(handoff.get("decision_id"), str)
            or handoff["decision_id"] != decision.get("decision_id")
            or handoff.get("chat_generation_owner") != "teammate_backend"):
        return None
    utterance = context.get("utterance")
    if not isinstance(utterance, str) or len(utterance) > 600:
        return None
    if code != "A" and (handoff.get("dispatch_recommended") is not True or not utterance.strip()):
        return None
    return {
        "code": code, "action": spec["action"], "channel": spec["channel"],
        "mode": spec["mode"], "content_intent": spec.get("content_intent"),
        "decision_id": decision["decision_id"], "interaction_id": interaction,
        "utterance": utterance,
    }


def _observation(snapshot: dict, now: float, stamp: float) -> dict:
    """Return only the allowed, current observations; never expose raw data."""
    result = {}
    for kind in ("eeg", "heart", "scene"):
        if not _modality_valid(snapshot, kind, now, stamp):
            continue
        item = snapshot[kind]
        if kind == "eeg":
            result[kind] = {"attention_score": item["attention_score"],
                            "valence_score": item["valence_score"],
                            "age_s": item["age_s"],
                            "semantics": "uncalibrated_research_scores_not_state_truth"}
        elif kind == "heart":
            result[kind] = {"bpm": item["bpm"], "age_s": item["age_s"],
                            "measurement_kind": "heart_rate_bpm_not_raw_ecg"}
        else:
            result[kind] = {"scene_summary": item["scene_summary"],
                            "uncertainties": item.get("uncertainties", []),
                            "capture_source": item["capture_source"], "age_s": item["age_s"]}
    return result


def validate_reply(text: str, decision: dict) -> bool:
    """Apply the handoff content length/shape limits to R15 text output."""
    if not isinstance(text, str) or not text.strip() or not isinstance(decision, dict):
        return False
    mode = decision.get("mode")
    if mode in ("short_text", "short_voice"):
        return len(text) <= 50
    if mode == "clarify":
        return len(text) <= 120
    if mode == "steps":
        lines = text.splitlines()
        return (1 <= len(lines) <= 3
                and len(text) <= 240
                and all(re.match(r"^" + str(index) + r"[.、] \S", line)
                        for index, line in enumerate(lines, 1)))
    return False


def validate_envelope(envelope: object, received_at: float | None = None) -> dict:
    """Validate a remote envelope and return a bounded R15 enrichment."""
    received_at = time.time() if received_at is None else received_at
    if not isinstance(envelope, dict) or envelope.get("schema_version") != "neuroecho.remote.v1":
        raise NeuroEchoUnavailable("wrong_remote_schema")
    if type(envelope.get("available")) is not bool:
        raise NeuroEchoUnavailable("explicit_remote_availability_required")
    if envelope.get("available") is not True:
        return {"available": False, "reason": envelope.get("reason") or "remote_unavailable"}
    snapshot = envelope.get("snapshot")
    relay = envelope.get("relay")
    if (not isinstance(snapshot, dict) or snapshot.get("schema_version") != "neuroecho.multimodal.v1"
            or snapshot.get("mode") != "live" or not isinstance(relay, dict)):
        raise NeuroEchoUnavailable("invalid_live_snapshot")
    if not isinstance(snapshot.get("session_id"), str) or not snapshot["session_id"]:
        raise NeuroEchoUnavailable("missing_session_id")
    stamp = snapshot.get("generated_at_unix_s")
    transport = relay.get("transport_age_s")
    if not _finite(stamp) or not _finite(transport) or transport < 0:
        raise NeuroEchoUnavailable("missing_timing")
    lag = received_at - stamp
    if lag < 0 or lag > 8 or transport > 8 or transport + lag > 8:
        return {"available": False, "reason": "expired_in_transit_or_receiver_clock_out_of_sync"}
    for key in ("eeg", "heart", "scene", "decision", "backend_handoff", "intervals_s"):
        if not isinstance(snapshot.get(key), dict):
            raise NeuroEchoUnavailable("invalid_modality_or_relay_objects")
    if not isinstance(snapshot["eeg"].get("raw"), dict):
        raise NeuroEchoUnavailable("invalid_raw_or_intervals")
    intervals = snapshot["intervals_s"]
    if intervals.get("eeg") not in (5, 10) or intervals.get("decision") not in (10, 15):
        raise NeuroEchoUnavailable("invalid_raw_or_intervals")
    snapshot = json.loads(json.dumps(snapshot, allow_nan=False))
    _advance_to_receipt(snapshot, lag)
    # The reader's generated_at is rebased to receipt; freshness is now checked
    # against the same immutable eight-second transport deadline.
    rebased_stamp = snapshot["generated_at_unix_s"]
    expiry = stamp + 8 - transport
    if received_at > expiry:
        return {"available": False, "reason": "expired_in_transit_or_receiver_clock_out_of_sync"}
    decision = _validated_decision(snapshot, received_at, rebased_stamp)
    return {
        "available": True,
        "reason": None,
        "snapshot_id": snapshot.get("snapshot_id"),
        "session_id": snapshot.get("session_id"),
        "source_utterance": snapshot.get("context", {}).get("utterance"),
        "decision": decision,
        "observations": _observation(snapshot, received_at, rebased_stamp),
        "expires_at_unix_s": expiry,
    }


def fetch_latest(opener=None, received_at: float | None = None) -> dict:
    cfg = connection_config()
    url = _share_url(cfg["base_url"], cfg["channel"])
    token = cfg["token"]
    if not isinstance(token, str) or not 24 <= len(token) <= 256:
        raise NeuroEchoUnavailable("invalid_read_credential")
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + token,
                                                    "Accept": "application/json"})
    try:
        with opener.open(request, timeout=DEFAULT_TIMEOUT) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except Exception as exc:
        raise NeuroEchoUnavailable("read_failed_" + type(exc).__name__) from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise NeuroEchoUnavailable("response_too_large")
    try:
        envelope = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_json")))
    except Exception as exc:
        raise NeuroEchoUnavailable("invalid_json") from exc
    return validate_envelope(envelope, received_at=received_at)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def status() -> dict:
    try:
        cfg = connection_config()
    except NeuroEchoUnavailable:
        return {"configured": False, "base_url": None, "channel": None,
                "read_only": True, "error": "connection_file_invalid"}
    configured = bool(cfg["base_url"] and cfg["channel"] and cfg["token"])
    return {"configured": configured, "base_url": cfg["base_url"] or None,
            "channel": cfg["channel"] or None, "read_only": True}
