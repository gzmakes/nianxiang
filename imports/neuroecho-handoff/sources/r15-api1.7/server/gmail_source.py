"""Gmail 真实只读（IMAP + 应用专用密码）。

边界：
- 只读 INBOX 最近未读邮件的头信息（主题/发件人/日期），不下载正文；
- 账号与密码只在本次请求内存中使用，不写库、不写日志；
- 需要 Gmail 两步验证后生成「应用专用密码」。
"""
from __future__ import annotations

import email
import imaplib
import socket
from datetime import datetime
from email.header import decode_header

TIMEOUT = 10


def _dec(raw) -> str:
    if not raw:
        return ""
    parts = decode_header(raw)
    out = []
    for s, enc in parts:
        if isinstance(s, bytes):
            try:
                out.append(s.decode(enc or "utf-8", errors="ignore"))
            except Exception:
                out.append(s.decode("utf-8", errors="ignore"))
        else:
            out.append(s)
    return " ".join("".join(out).split())


def _connect(address: str, password: str):
    m = imaplib.IMAP4_SSL("imap.gmail.com", timeout=TIMEOUT)
    try:
        m.login(address, password)
    except Exception:
        _logout(m)
        raise
    return m


def _logout(connection) -> None:
    try:
        connection.logout()
    except Exception:
        # Cleanup must not replace the actual read/login error.
        pass


def read(address: str, password: str, limit: int = 5) -> dict:
    address = (address or "").strip()
    password = (password or "").strip().replace(" ", "")
    if not address or not password:
        return {"ok": False, "error": "缺少 Gmail 地址或应用专用密码",
                "hint": "Google 账号 → 安全性 → 两步验证 → 应用专用密码"}
    m = None
    stage = "connect"
    try:
        m = _connect(address, password)
        stage = "read"
        typ, _ = m.select("INBOX", readonly=True)
        if typ != "OK":
            return {"ok": False, "error": "无法以只读方式打开 Gmail 收件箱", "hint": "检查账号是否允许 IMAP 访问后重试"}
        typ, data = m.search(None, "UNSEEN")
        if typ != "OK" or not data:
            return {"ok": False, "error": "查询 Gmail 未读邮件失败", "hint": "检查网络和 IMAP 访问权限后重试"}
        limit = max(1, min(int(limit), 5))
        ids = (data[0] or b"").split()[-limit:]
        items = []
        for mid in reversed(ids):
            typ, msg_data = m.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
            if typ != "OK":
                return {"ok": False, "error": "读取 Gmail 邮件头失败", "hint": "连接可能已断开，请重新读取"}
            if not msg_data or not isinstance(msg_data[0], tuple) or len(msg_data[0]) < 2:
                continue
            raw = msg_data[0][1] or b""
            msg = email.message_from_bytes(raw)
            subject = _dec(msg.get("Subject")) or "（无主题）"
            sender = _dec(msg.get("From"))[:60]
            date = _dec(msg.get("Date"))[:40]
            items.append({"type": "email", "title": subject[:60],
                          "meta": f"Gmail · {sender}", "summary": f"{date} · 未读"})
    except imaplib.IMAP4.error:
        if stage == "connect":
            return {"ok": False, "error": "Gmail 登录失败",
                    "hint": "确认已开启两步验证并使用「应用专用密码」，不是账号登录密码"}
        return {"ok": False, "error": "Gmail 读取连接已中断", "hint": "请检查网络后重新读取，无需更换密码"}
    except (TimeoutError, socket.timeout):
        return {"ok": False, "error": "连接 Gmail 超时", "hint": "检查网络是否能访问 Gmail 后重试"}
    except Exception:
        return {"ok": False, "error": "读取 Gmail 失败", "hint": "检查网络及 IMAP 访问是否可用后重试"}
    finally:
        if m is not None:
            _logout(m)
    if not items:
        return {"ok": False, "error": "收件箱没有未读邮件", "hint": "先留一封未读再试"}

    titles = [i["title"] for i in items]
    facts = [f"{i['title']}：{i['meta']}" for i in items[:3]]
    inferences = [f"你有 {len(items)} 封未读，最近的是「{titles[0]}」。",
                  "未读不等于重要；先选一封真正需要回的。"]
    questions = [f"「{titles[0]}」需要现在回吗？"]
    insights = [
        {"type": "pattern", "title": f"{len(items)} 封未读在等你", "text": "最近：" + "、".join(titles[:3]) + "。"},
        {"type": "risk", "title": "未读≠待办", "text": "先把需要回的挑出来，别被红点牵着走。"},
        {"type": "opportunity", "title": "只回最关键的一封", "text": "选一封，写一句明确回复。"},
    ]
    return {
        "ok": True,
        "connector": {"id": "gmail", "name": "Gmail", "category": "日常", "icon": "M",
                      "blurb": "未读邮件头（只读）", "reads": ["最近未读邮件头"], "scopes": ["gmail:unread-headers"], "mode": "real-readonly"},
        "title": "Gmail 未读",
        "items": items,
        "understanding": {"facts": facts, "inferences": inferences, "questions": questions},
        "insights": insights,
        "starters": [f"「{titles[0][:18]}」先怎么回？", "为什么这么判断？", "变成下一步"],
        "synthetic": False,
        "source": "gmail",
        "read_at": datetime.now().isoformat(timespec="seconds"),
    }
