"""故障演练：进程内开关，用于演示 failed/unknown 与降级路径（PRD F12/F13）。"""
from __future__ import annotations

KEYS = ("model_timeout", "device_stall", "lark_auth")
_state = {k: False for k in KEYS}


def set_faults(kind: str, enabled: bool) -> dict:
    if kind not in _state:
        raise ValueError(f"unknown fault: {kind}")
    _state[kind] = bool(enabled)
    return get_faults()


def clear() -> dict:
    for k in _state:
        _state[k] = False
    return get_faults()


def get_faults() -> dict:
    return dict(_state)


def active(kind: str) -> bool:
    return bool(_state.get(kind))
