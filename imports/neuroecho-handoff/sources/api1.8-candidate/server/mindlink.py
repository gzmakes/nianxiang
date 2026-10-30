"""Opt-in, read-only snapshot of the local MindLink attention feed.

No background polling, recording, emotion interpretation, or cached readings.
The caller must obtain consent for each enabled session before calling read_attention.
"""
from __future__ import annotations

import json
import math
import time
from urllib.error import URLError
from http.client import HTTPException
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

_URL = "http://127.0.0.1:8876/api/v1/state?source=esense"
_URL_PERSONAL = "http://127.0.0.1:8876/api/v1/state?source=personal"
_SOURCES = {"esense": "neurosky_esense", "personal": "personal_model"}
_MAX_BYTES = 64 * 1024
_TIMEOUT_SECONDS = 1.0
_MAX_AGE_MS = 2500


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch(source: str = "esense") -> dict:
    # Do not use system proxy settings or follow redirects away from loopback.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    if not isinstance(source, str) or source not in _SOURCES:
        raise ValueError("unsupported source")
    request = Request(_URL if source == "esense" else _URL_PERSONAL, headers={"Accept": "application/json", "Cache-Control": "no-store"})
    with opener.open(request, timeout=_TIMEOUT_SECONDS) as response:
        body = response.read(_MAX_BYTES + 1)
    if len(body) > _MAX_BYTES:
        raise ValueError("response too large")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("invalid response")
    return data


def _unavailable(reason: str, source: str = "neurosky_esense") -> dict:
    return {"available": False, "reason": reason, "source": source, "score": None, "age_ms": None}


def _number(value) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def read_attention(*, enabled: bool = False, source: str = "esense") -> dict:
    """Fetch one snapshot only when explicitly enabled by the caller.

    Values are device feedback scores, not emotion or clinical measurements.
    The caller must stop showing the score whenever available is false.
    """
    if not isinstance(source, str) or source not in _SOURCES:
        return _unavailable("unsupported_source", "unknown")
    requested_source = _SOURCES[source]
    if enabled is not True:
        return _unavailable("not_enabled", requested_source)
    started = time.monotonic()
    try:
        state = _fetch() if source == "esense" else _fetch(source=source)
    except (OSError, URLError, ValueError, UnicodeError, TimeoutError, HTTPException):
        return _unavailable("service_unavailable", requested_source)

    attention = state.get("attention")
    if state.get("api_version") != "1.0" or not isinstance(attention, dict):
        return _unavailable("invalid_response", requested_source)
    if state.get("live") is not True or state.get("connected") is not True:
        return _unavailable("signal_not_live", requested_source)
    if type(state.get("signal_quality")) is not int or state["signal_quality"] != 0:
        return _unavailable("signal_quality_unavailable", requested_source)
    if attention.get("source") != requested_source or attention.get("valid") is not True:
        return _unavailable("attention_unavailable", requested_source)
    if source == "personal" and (not isinstance(state.get("capabilities"), dict) or state["capabilities"].get("personal_model_loaded") is not True):
        return _unavailable("attention_unavailable", requested_source)
    score, age = attention.get("value"), attention.get("age_ms")
    minimum = 1 if source == "esense" else 0
    if not _number(score) or not minimum <= score <= 100 or not _number(age) or age < 0:
        return _unavailable("attention_unavailable", requested_source)
    # Treat the whole request duration as additional age, conservatively.
    age += max(0.0, time.monotonic() - started) * 1000
    # The local server also emits its wall-clock update time. When provided,
    # check both clocks so that an old/replayed response cannot claim a fresh age.
    updated = attention.get("updated_at_unix")
    if updated is not None:
        if not _number(updated):
            return _unavailable("attention_unavailable", requested_source)
        wall_age = (time.time() - updated) * 1000
        if wall_age < -1000:  # clock skew too large for a trustworthy snapshot
            return _unavailable("attention_unavailable", requested_source)
        age = max(age, max(0.0, wall_age))
    if age > _MAX_AGE_MS:
        return _unavailable("attention_unavailable", requested_source)
    return {"available": True, "reason": None, "source": requested_source, "score": score, "age_ms": age}
