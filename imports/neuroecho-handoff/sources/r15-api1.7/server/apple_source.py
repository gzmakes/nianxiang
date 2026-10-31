"""macOS 真实连接器：提醒事项 / 日历（只读，osascript）。

边界：
- 只读未完成提醒 / 未来 7 天日程；
- 首次调用可能触发系统「自动化」权限；拒绝或失败时返回可恢复的错误；
- 不做任何写入，不访问其他应用。
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone

TIMEOUT = 45
START_TIMEOUT = 8
MAX_ITEMS = 8

# AppleScript's text protocol uses a line per item and || between fields.
# Remove those separators from the fields, so a user-created title cannot be
# mistaken for an extra item or move a calendar name into the wrong field.
_CLEAN_FIELD = r'''
on cleanField(valueText)
  set valueText to valueText as text
  repeat with separator in {return, linefeed, "||"}
    set AppleScript's text item delimiters to separator as text
    set pieces to text items of valueText
    set AppleScript's text item delimiters to " "
    set valueText to pieces as text
  end repeat
  set AppleScript's text item delimiters to ""
  return valueText
end cleanField
'''


def platform_supported() -> bool:
    return sys.platform == "darwin"


def _unsupported() -> dict:
    return {"ok": False, "error_code": "platform_unsupported", "error": "当前服务平台不支持 Mac 日历或提醒事项",
            "hint": "这项连接需要运行在 macOS 的回响服务；当前没有读取，也不会申请权限。"}

REMINDERS_SCRIPT = _CLEAN_FIELD + r'''
set output to ""
set itemCount to 0
tell application "Reminders"
  repeat with l in lists
    repeat with r in (reminders of l whose completed is false)
      set output to output & my cleanField(name of r) & "||" & my cleanField(name of l) & linefeed
      set itemCount to itemCount + 1
      if itemCount >= 8 then exit repeat
    end repeat
    if itemCount >= 8 then exit repeat
  end repeat
end tell
return output
'''

CALENDAR_SCRIPT = _CLEAN_FIELD + r'''
set output to ""
set itemCount to 0
set now to (current date)
set later to now + 7 * days
tell application "Calendar"
  repeat with c in calendars
    repeat with e in (every event of c whose start date is greater than or equal to now and start date is less than or equal to later)
      set output to output & my cleanField(summary of e) & "||" & my cleanField(start date of e as string) & "||" & my cleanField(name of c) & linefeed
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
        if not parts or (not parts[0] and "||" not in line):
            continue
        title = (parts[0] or f"未命名{kind}")[:80]
        meta = " · ".join(part for part in parts[1:] if part)
        out.append({"type": kind, "title": title, "meta": meta[:80], "summary": f"{kind}：{title}"})
    return out[:MAX_ITEMS]


def _read_with_start(script: str, bundle_id: str) -> str:
    """Retry app-not-running once, using only known Apple bundle identifiers."""
    try:
        return _run(script)
    except RuntimeError as error:
        if "(-600)" not in str(error) or bundle_id not in {
                "com.apple.iCal", "com.apple.reminders"}:
            raise
        opened = subprocess.run(["/usr/bin/open", "-g", "-b", bundle_id],
                                capture_output=True, text=True, timeout=START_TIMEOUT)
        if opened.returncode:
            raise RuntimeError("(-600) application could not be started")
        return _run(script)


def _read_error(exc: Exception, app: str) -> dict:
    """Return actionable status without exposing untrusted AppleScript stderr."""
    message = str(exc).lower()
    if isinstance(exc, subprocess.TimeoutExpired):
        return {"ok": False, "error_code": "read_timeout", "error": f"读取{app}超时",
                "hint": f"请检查是否有等待确认的系统权限提示，然后重试。首次启动{app}也可能需要一点时间。"}
    if "(-600)" in message:
        return {"ok": False, "error_code": "app_not_running", "error": f"无法启动{app}",
                "hint": f"请先手动打开{app}，等待它启动后重新读取。"}
    if "(-1743)" in message or "not authorized to send apple events" in message or "not permitted to send apple events" in message:
        return {"ok": False, "error_code": "automation_denied", "error": f"无法读取{app}",
                "hint": f"请到系统设置 → 隐私与安全性 → 自动化，允许启动念响服务的应用控制{app}，再重试。"}
    return {"ok": False, "error_code": "read_failed", "error": f"无法读取{app}",
            "hint": f"请确认{app}可以正常打开，并检查启动念响服务的应用是否有自动化权限；再重试。"}


def read_reminders() -> dict:
    if not platform_supported():
        return _unsupported()
    try:
        raw = _read_with_start(REMINDERS_SCRIPT, "com.apple.reminders")
    except Exception as exc:
        return _read_error(exc, "提醒事项")
    items = _items([l for l in raw.splitlines() if l.strip()], "提醒")
    if raw.strip() and not items:
        return {"ok": False, "error_code": "unreadable_results", "error": "读取到的提醒事项无法识别",
                "hint": "请检查提醒事项中的条目是否有标题，再重新读取。"}
    return _package("apple_reminders", "提醒事项", "✓", "待办与承诺（只读）",
                    ["未完成提醒"], ["reminders:read"], items, "提醒")


def read_calendar() -> dict:
    if not platform_supported():
        return _unsupported()
    try:
        raw = _read_with_start(CALENDAR_SCRIPT, "com.apple.iCal")
    except Exception as exc:
        return _read_error(exc, "日历")
    items = _items([l for l in raw.splitlines() if l.strip()], "日程")
    if raw.strip() and not items:
        return {"ok": False, "error_code": "unreadable_results", "error": "读取到的日历条目无法识别",
                "hint": "请检查日历中的条目是否有标题，再重新读取。"}
    return _package("apple_calendar", "Apple 日历", "日", "未来 7 天日程（只读）",
                    ["未来 7 天日程"], ["calendar:readonly"], items, "日程")


_EPOCH_DATE = r'''
on epochText(d, anchorDate, unixReference)
  return ((round ((d - anchorDate) + unixReference)) as text)
end epochText
'''


def _script_window(since: datetime, until: datetime) -> str:
    # AppleScript's date constructor loses UTC offsets and repeated-hour folds.
    # Anchor an absolute date to the same system second, then use epoch deltas.
    # The before/after bracket avoids a one-second boundary race; no locale or
    # current-offset assumptions are used for either boundary or returned date.
    return r'''
repeat with clockAttempt from 1 to 3
  set unixBefore to (do shell script "/bin/date +%s") as real
  set epochAnchor to current date
  set unixAfter to (do shell script "/bin/date +%s") as real
  if unixBefore = unixAfter then exit repeat
  if clockAttempt = 3 then error "Unable to sample system clock"
end repeat
''' + (f"set windowStart to epochAnchor + ({int(since.timestamp())} - unixAfter)\n"
       f"set windowEnd to epochAnchor + ({int(until.timestamp())} - unixAfter)\n")


def _read_recent(kind: str, *, now: datetime | None = None) -> dict:
    if not platform_supported():
        return _unsupported()
    until = (now or datetime.now().astimezone()).astimezone().replace(microsecond=0)
    since = (until.astimezone(timezone.utc) - timedelta(days=7)).astimezone()
    calendar = kind == "calendar"
    app, bundle = ("Calendar", "com.apple.iCal") if calendar else ("Reminders", "com.apple.reminders")
    app_name = "日历" if calendar else "提醒事项"
    script = _CLEAN_FIELD + _EPOCH_DATE + _script_window(since, until)
    script += ('set output to ""\nset itemCount to 0\n'
               f'tell application "{app}"\n')
    if calendar:
        script += r'''
  repeat with c in calendars
    repeat with e in (every event of c whose start date is greater than or equal to windowStart and start date is less than or equal to windowEnd)
      set output to output & my cleanField(summary of e) & "||" & my epochText(start date of e, epochAnchor, unixAfter) & "||" & my cleanField(name of c) & linefeed
      set itemCount to itemCount + 1
      if itemCount ≥ 8 then exit repeat
    end repeat
    if itemCount ≥ 8 then exit repeat
  end repeat
'''
    else:
        script += r'''
  repeat with l in lists
    repeat with r in (reminders of l whose modification date is greater than or equal to windowStart and modification date is less than or equal to windowEnd)
      set stateText to "未完成"
      if completed of r then set stateText to "已完成"
      set output to output & my cleanField(name of r) & "||" & my epochText(modification date of r, epochAnchor, unixAfter) & "||" & my cleanField(name of l) & "||" & stateText & linefeed
      set itemCount to itemCount + 1
      if itemCount ≥ 8 then exit repeat
    end repeat
    if itemCount ≥ 8 then exit repeat
  end repeat
'''
    script += "end tell\nreturn output\n"
    try:
        raw = _read_with_start(script, bundle)
    except Exception as exc:
        return _read_error(exc, app_name)
    items = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        fields = [value.strip() for value in line.split("||")]
        if len(fields) < 3:
            return {"ok": False, "error_code": "unreadable_results", "error": f"近期{app_name}的时间信息无法识别，请重新读取。"}
        try:
            event_time = datetime.fromtimestamp(float(fields[1]), timezone.utc).astimezone()
        except (ValueError, OverflowError, OSError):
            return {"ok": False, "error_code": "unreadable_results", "error": f"近期{app_name}的时间信息无法识别，请重新读取。"}
        if not since <= event_time <= until:
            continue  # Never label a system out-of-window row as seven-day data.
        title = (fields[0] or ("未命名日程" if calendar else "未命名提醒"))[:80]
        meta = " · ".join([event_time.isoformat(timespec="seconds"), *fields[2:]])[:180]
        items.append({"type": "日程" if calendar else "提醒", "title": title, "meta": meta,
                      "summary": f"{'日程' if calendar else '提醒'}：{title}",
                      "start_at" if calendar else "modified_at": event_time.isoformat(timespec="seconds"),
                      "completed": fields[3] == "已完成" if not calendar and len(fields) > 3 else False})
    items = items[:MAX_ITEMS]
    label = "过去 7 天开始的日程" if calendar else "过去 7 天修改过的提醒（含已完成）"
    cid = "apple_calendar" if calendar else "apple_reminders"
    result = _package(cid, "Apple 日历" if calendar else "提醒事项", "日" if calendar else "✓",
                      label + "（只读）", [label], ["calendar:readonly" if calendar else "reminders:read"],
                      items, "日程" if calendar else "提醒")
    result["read_window"] = "recent7"
    result["scope"] = {"kind": "last_7_days", "since": since.isoformat(timespec="seconds"),
                       "until": until.isoformat(timespec="seconds"), "label": label}
    # This server-read fact also survives an empty item list when the attachment
    # is saved as source_text. No client-supplied scope is trusted.
    result["text"] = (f"读取范围：{label}；{result['scope']['since']} 至 {result['scope']['until']}。"
                      f"本次读取 {len(items)} 条，最多展示 {MAX_ITEMS} 条。\n" +
                      "\n".join(f"{item['title']}：{item['meta']}" for item in items))
    for item in result["items"]:
        item["read_scope"] = dict(result["scope"])
    if not items:
        result["understanding"]["facts"] = [f"截至 {result['read_at']}，读取{label}，结果为 0 条。"]
    return result


def read_calendar_recent(*, now: datetime | None = None) -> dict:
    """Read actual event starts in the previous seven days; default API is unchanged."""
    return _read_recent("calendar", now=now)


def read_reminders_recent(*, now: datetime | None = None) -> dict:
    """Read reminders actually modified in the previous seven days, including completed."""
    return _read_recent("reminders", now=now)


def _package(cid, name, icon, blurb, reads, scopes, items, kind) -> dict:
    titles = [i["title"] for i in items]
    if not items:
        read_at = datetime.now().isoformat(timespec="seconds")
        empty_fact = (f"截至 {read_at} 读取系统提醒事项中的未完成提醒，结果为 0 条。"
                      if cid == "apple_reminders" else
                      f"截至 {read_at} 读取系统日历未来 7 天的日程，结果为 0 条。")
        return {
            "ok": True,
            "connector": {"id": cid, "name": name, "category": "日常", "icon": icon,
                          "blurb": blurb, "reads": reads, "scopes": scopes, "mode": "local-real"},
            "items": [], "understanding": {"facts": [empty_fact], "inferences": [], "questions": []},
            "insights": [], "starters": ["先听我说"], "synthetic": False, "source": "macos",
            "read_at": read_at,
        }
    facts = [f"{i['title']}：{i['meta']}" for i in items[:3]]
    inferences = [
        f"本次展示 {len(items)} 条{kind}（最多展示 8 条），其中一条是「{titles[0]}」。",
        "这些是系统里的真实条目，不是演示数据。",
    ]
    questions = [f"「{titles[0]}」需要我先帮你做什么？"]
    insights = [
        {"type": "pattern", "title": f"本次展示 {len(items)} 条{kind}",
         "text": "其中包括：" + "、".join(titles[:3]) + "。"},
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
