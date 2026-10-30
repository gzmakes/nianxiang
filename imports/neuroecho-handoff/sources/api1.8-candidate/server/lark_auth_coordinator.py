"""Serialize Feishu flows with an opaque owner token per reservation."""
import threading

_lock = threading.Lock()
_active = None


def begin(purpose):
    global _active
    with _lock:
        if _active is not None:
            return ("same", _active[1]) if _active[0] == purpose else ("conflict", None)
        token = object()
        _active = (purpose, token)
        return "new", token


def finish(purpose, token):
    global _active
    with _lock:
        if _active is not None and _active[0] == purpose and _active[1] is token:
            _active = None
