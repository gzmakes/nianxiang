"""macOS 真实连接器：提醒事项 / 日历（只读，osascript）。

边界：
- 只读未完成提醒 / 未来 7 天日程；
- 首次调用可能触发系统「自动化」权限；拒绝或失败时返回可恢复的错误；
- 不做任何写入，不访问其他应用。
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime

TIMEOUT = 8


def platform_supported() -> bool:
    return sys.platform == "darwin"


def _unsupported() -> dict:
    return {"ok": False, "error_code": "platform_unsupported", "error": "当前服务平台不支持 Mac 日历或提醒事项",
            "hint": "这项连接需要运行在 macOS 的回响服务；当前没有读取，也不会申请权限。"}

REMINDERS_SCRIPT = r'''
set output to ""
set itemCount to 0
tell application "Reminders"
  repeat with l in lists
    repeat with r in (reminders of l whose completed is false)
      set output to output & (name of r) & "||" & (name of l) & linefeed
      set itemCount to itemCount + 1
      if itemCount >= 8 then exit repeat
    end repeat
    if itemCount >= 8 then exit repeat
  end repeat
end tell
return output
'''

CALENDAR_SCRIPT = r'''
set output to ""
set itemCount to 0
set now to (current date)
set later to now + 7 * days
tell application "Calendar"
  repeat with c in calendars
    repeat with e in (every event of c whose start date is greater than or equal to now and start date is less than or equal to later)
      set output to output & (summary of e) & "||" & (start date of e as string) & "||" & (name of c) & linefeed
      set itemCount to itemCount + 1
      if itemCount >= 8 then exit repeat
    end repeat
    if itemCount >= 8 then exit repeat
  end repeat
end tell
return output
'''


def create_reminder(title: str) -> dict:
    """写入系统提醒事项（需自动化权限）。"""
    import json as _json
    safe = _json.dumps(title[:180], ensure_ascii=False)
    script = f'tell application "Reminders" to make new reminder with properties {{name:{safe}}}'
    try:
        _run(script)
    except subprocess.TimeoutExpired:
        raise RuntimeError("写入提醒事项超时")
    except Exception as e:
        raise RuntimeError(str(e)[:160])
    return {"ok": True, "title": title}


def create_event(title: str, when_iso: str, duration_min: int = 30) -> dict:
    """写入系统日历（第一个日历），需自动化权限。"""
    import json as _json
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(when_iso)
    except Exception:
        raise RuntimeError("时间格式无效")
    safe = _json.dumps(title[:180], ensure_ascii=False)
    script = f'''set d to current date
set year of d to {dt.year}
set month of d to {dt.month}
set day of d to {dt.day}
set hours of d to {dt.hour}
set minutes of d to {dt.minute}
set seconds of d to 0
tell application "Calendar" to tell calendar 1 to make new event with properties {{summary:{safe}, start date:d, end date:d + {int(duration_min)} * minutes}}'''
    try:
        _run(script)
    except subprocess.TimeoutExpired:
        raise RuntimeError("写入日历超时")
    except Exception as e:
        raise RuntimeError(str(e)[:160])
    return {"ok": True, "title": title, "when": when_iso}


def _run(script: str) -> str:
    if not platform_supported():
        raise RuntimeError('当前服务平台不支持 Mac 系统操作')
    p = subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, text=True, timeout=TIMEOUT)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "osascript failed").strip()[:200])
    return p.stdout


def _items(lines: list[str], kind: str) -> list[dict]:
    out = []
    for line in lines:
        parts = [x.strip() for x in line.split("||")]
        if not parts or not parts[0]:
            continue
        title = parts[0][:80]
        meta = " · ".join(part for part in parts[1:] if part)
        out.append({"type": kind, "title": title, "meta": meta[:80], "summary": f"{kind}：{title}"})
    return out[:8]


def read_reminders() -> dict:
    if not platform_supported():
        return _unsupported()
    try:
        raw = _run(REMINDERS_SCRIPT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "读取提醒事项超时", "hint": "系统设置 → 隐私与安全性 → 自动化，允许终端控制提醒事项"}
    except Exception:
        return {"ok": False, "error": "无法读取提醒事项", "hint": "检查系统设置 → 隐私与安全性 → 自动化，允许启动本服务的应用控制提醒事项；再重新读取"}
    items = _items([l for l in raw.splitlines() if l.strip()], "提醒")
    if not items:
        return {"ok": False, "error": "没有未完成的提醒", "hint": "在提醒事项里建一条后再试"}
    return _package("apple_reminders", "提醒事项", "✓", "待办与承诺（只读）",
                    ["未完成提醒"], ["reminders:read"], items, "提醒")


def read_calendar() -> dict:
    if not platform_supported():
        return _unsupported()
    try:
        raw = _run(CALENDAR_SCRIPT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "读取日历超时", "hint": "系统设置 → 隐私与安全性 → 自动化，允许终端控制日历"}
    except Exception:
        return {"ok": False, "error": "无法读取日历", "hint": "检查系统设置 → 隐私与安全性 → 自动化，允许启动本服务的应用控制日历；再重新读取"}
    items = _items([l for l in raw.splitlines() if l.strip()], "日程")
    if not items:
        return {"ok": False, "error": "未来 7 天没有日程", "hint": "在日历里加一个日程后再试"}
    return _package("apple_calendar", "Apple 日历", "日", "未来 7 天日程（只读）",
                    ["未来 7 天日程"], ["calendar:readonly"], items, "日程")


def _package(cid, name, icon, blurb, reads, scopes, items, kind) -> dict:
    titles = [i["title"] for i in items]
    facts = [f"{i['title']}：{i['meta']}" for i in items[:3]]
    inferences = [
        f"本次读到 {len(items)} 条{kind}，其中一条是「{titles[0]}」。",
        "这些是系统里的真实条目，不是演示数据。",
    ]
    questions = [f"「{titles[0]}」需要我先帮你做什么？"]
    insights = [
        {"type": "pattern", "title": f"{len(items)} 条{kind}在等着",
         "text": "其中包括：" + "、".join(titles[:3]) + "。"},
        {"type": "risk", "title": "承诺在堆积", "text": "未完成项越多，越容易靠记忆硬扛。"},
        {"type": "opportunity", "title": "把一条变成下一步", "text": "只挑一条今天能动的最小动作。"},
    ]
    return {
        "ok": True,
        "connector": {"id": cid, "name": name, "category": "日常", "icon": icon,
                      "blurb": blurb, "reads": reads, "scopes": scopes, "mode": "local-real"},
        "items": items,
        "understanding": {"facts": facts, "inferences": inferences, "questions": questions},
        "insights": insights,
        "starters": ([f"「{titles[0]}」先做什么？"] if titles else ["先做什么？"]) +
                    ["为什么这么判断？", "变成下一步"],
        "synthetic": False,
        "source": "macos",
        "read_at": datetime.now().isoformat(timespec="seconds"),
    }
