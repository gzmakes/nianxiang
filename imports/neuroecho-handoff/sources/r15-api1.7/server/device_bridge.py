"""设备桥模拟器：实体按钮事件 + 显示命令 ACK（PRD F03/F04/F06/F12/F18/F20）。

真实硬件替换点：
- SensorFrame 由 RSCAdapter 提供（当前为 SyntheticAdapter）；
- 实体按钮由硬件事件回调触发 button_press()；
- 显示通过 PresentationAdapter.display() 下发，返回 command_id 与 ACK。
本模块只提供进程内模拟，不涉及真实串口/BLE/网络。
"""
from __future__ import annotations

import random
import time
import uuid
from datetime import datetime, timezone

_state = {
    "last_button": None,
    "last_display": None,
    "acks": [],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def button_press(session_id: str, source: str = "synthetic-button") -> dict:
    """模拟实体按钮按下：产生事件并返回 ACK（PRD F06）。"""
    evt = {
        "id": f"evt_{uuid.uuid4().hex[:10]}",
        "type": "button.press",
        "source": source,
        "session_id": session_id,
        "ts": _now(),
    }
    ack = {
        "id": f"ack_{uuid.uuid4().hex[:10]}",
        "for": evt["id"],
        "status": "received",
        "latency_ms": random.randint(8, 40),
        "ts": _now(),
    }
    evt["ack"] = ack
    _state["last_button"] = evt
    return evt


def display(session_id: str, text: str, color: str = "amber") -> dict:
    """模拟显示命令：返回 command_id 与 ACK（PRD F12/F18）。"""
    cmd = {
        "id": f"disp_{uuid.uuid4().hex[:10]}",
        "type": "display.show",
        "session_id": session_id,
        "text": (text or "")[:80],
        "color": color,
        "ts": _now(),
    }
    ack = {
        "id": f"ack_{uuid.uuid4().hex[:10]}",
        "for": cmd["id"],
        "status": "displayed",
        "latency_ms": random.randint(12, 60),
        "ts": _now(),
    }
    cmd["ack"] = ack
    _state["last_display"] = cmd
    _state["acks"].append(ack)
    _state["acks"] = _state["acks"][-20:]
    return cmd


def state() -> dict:
    return {
        "last_button": _state["last_button"],
        "last_display": _state["last_display"],
        "acks": _state["acks"],
        "synthetic": True,
    }
