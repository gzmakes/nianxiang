"""Cross-platform local calendar and task sources.

The browser talks to the same source ids on every platform.  macOS keeps the
existing AppleScript adapter; Windows uses Outlook's local COM folders through
PowerShell when Outlook is installed.  A missing application or permission
failure is reported as a recoverable status and never replaced with demo data.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime

from . import apple_source

TIMEOUT = 8
WINDOWS_TASKS_ID = "windows_reminders"
WINDOWS_CALENDAR_ID = "windows_calendar"


def platform_ids() -> tuple[str, str] | None:
    if sys.platform == "darwin":
        return ("apple_reminders", "apple_calendar")
    if sys.platform == "win32":
        return (WINDOWS_TASKS_ID, WINDOWS_CALENDAR_ID)
    return None


def _powershell() -> str | None:
    # Windows PowerShell is present on supported Windows versions.  pwsh is
    # accepted as well so a portable PowerShell 7 installation works.
    return shutil.which("pwsh") or shutil.which("powershell")


def _windows_status(kind: str) -> dict:
    if sys.platform != "win32":
        return {"status": "platform_unsupported", "hint": "Windows Outlook 来源只在 Windows 服务上运行"}
    if not _powershell():
        return {"status": "needs_install", "hint": "请安装 Windows PowerShell 或 PowerShell 7"}
    label = "Outlook 任务" if kind == "tasks" else "Outlook 日历"
    return {"status": "conditions_required", "hint": f"连接时检查本机 {label} 与 Outlook 权限"}


def status(kind: str) -> dict:
    """Return a cheap platform/runtime status without opening a data source."""
    if kind not in ("tasks", "calendar"):
        raise ValueError("unknown system source kind")
    if sys.platform == "darwin":
        return {"status": "conditions_required", "hint": "连接时请求 macOS 自动化权限"}
    return _windows_status(kind)


def _unsupported(kind: str) -> dict:
    label = "提醒事项" if kind == "tasks" else "日历"
    return {
        "ok": False,
        "error_code": "platform_unsupported",
        "status": "platform_unsupported",
        "error": f"当前服务平台不支持本机{label}来源",
        "hint": "请在 macOS 使用 Apple 日历/提醒事项，或在 Windows 使用 Outlook 版本的回响服务。",
    }


def _windows_script(kind: str) -> str:
    # The script emits a bounded, deliberately small text format.  It never
    # serializes Outlook objects or account identifiers back to the browser.
    if kind == "tasks":
        return r'''
$ErrorActionPreference = "Stop"
$outlook = New-Object -ComObject Outlook.Application
$ns = $outlook.GetNamespace("MAPI")
$folder = $ns.GetDefaultFolder(13)
$items = $folder.Items
$items.Sort("[DueDate]", $false)
$count = 0
foreach ($item in $items) {
  if ($item.Complete -eq $false) {
    $title = ([string]$item.Subject).Replace("||", " ").Replace("`r", " ").Replace("`n", " ")
    $meta = ([string]$item.DueDate).Replace("||", " ").Replace("`r", " ").Replace("`n", " ")
    if ($title) { Write-Output ($title.Substring(0, [Math]::Min(80, $title.Length)) + "||" + $meta.Substring(0, [Math]::Min(80, $meta.Length))); $count++ }
    if ($count -ge 8) { break }
  }
}
'''
    return r'''
$ErrorActionPreference = "Stop"
$outlook = New-Object -ComObject Outlook.Application
$ns = $outlook.GetNamespace("MAPI")
$folder = $ns.GetDefaultFolder(9)
$start = Get-Date
$end = $start.AddDays(7)
$items = $folder.Items
$items.IncludeRecurrences = $true
$items.Sort("[Start]", $true)
$count = 0
foreach ($item in $items) {
  $when = $item.Start
  if ($when -ge $start -and $when -le $end) {
    $title = ([string]$item.Subject).Replace("||", " ").Replace("`r", " ").Replace("`n", " ")
    $meta = ([string]$when).Replace("||", " ").Replace("`r", " ").Replace("`n", " ")
    if ($title) { Write-Output ($title.Substring(0, [Math]::Min(80, $title.Length)) + "||" + $meta.Substring(0, [Math]::Min(80, $meta.Length))); $count++ }
    if ($count -ge 8) { break }
  }
}
'''


def _run_windows(kind: str) -> str:
    command = _powershell()
    if not command:
        raise FileNotFoundError("PowerShell is not installed")
    proc = subprocess.run(
        [command, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _windows_script(kind)],
        capture_output=True, text=True, timeout=TIMEOUT,
    )
    if proc.returncode:
        detail = (proc.stderr or "Outlook access failed").strip()
        raise RuntimeError(detail[:240])
    return proc.stdout


def _items(raw: str, kind: str) -> list[dict]:
    out = []
    label = "任务" if kind == "tasks" else "日程"
    for line in raw.splitlines():
        parts = [x.strip() for x in line.split("||", 1)]
        if not parts[0]:
            continue
        title = parts[0][:80]
        meta = parts[1][:80] if len(parts) > 1 else ""
        out.append({"type": label, "title": title, "meta": meta, "summary": f"{label}：{title}"})
    return out[:8]


def _package(kind: str, items: list[dict]) -> dict:
    tasks = kind == "tasks"
    source_id = WINDOWS_TASKS_ID if tasks else WINDOWS_CALENDAR_ID
    name = "Outlook 任务" if tasks else "Outlook 日历"
    label = "任务" if tasks else "日程"
    titles = [item["title"] for item in items]
    return {
        "ok": True,
        "connector": {"id": source_id, "name": name, "category": "日常", "icon": "✓" if tasks else "日",
                       "blurb": "未完成任务（只读）" if tasks else "未来 7 天日程（只读）",
                       "reads": ["未完成任务"] if tasks else ["未来 7 天日程"],
                       "scopes": ["tasks:read"] if tasks else ["calendar:readonly"], "mode": "local-real"},
        "items": items,
        "understanding": {
            "facts": [f"{i['title']}：{i['meta']}" for i in items[:3]],
            "inferences": [f"本次读到 {len(items)} 条{label}，其中一条是「{titles[0]}」。", "这些是 Outlook 里的真实条目，不是演示数据。"],
            "questions": [f"「{titles[0]}」需要我先帮你做什么？"],
        },
        "insights": [{"type": "pattern", "title": f"{len(items)} 条{label}在等着", "text": "其中包括：" + "、".join(titles[:3]) + "。"}],
        "starters": [f"「{titles[0]}」先做什么？", "为什么这么判断？", "变成下一步"],
        "synthetic": False,
        "source": "windows-outlook",
        "read_at": datetime.now().isoformat(timespec="seconds"),
    }


def read(kind: str) -> dict:
    if kind not in ("tasks", "calendar"):
        raise ValueError("unknown system source kind")
    if sys.platform == "darwin":
        return apple_source.read_reminders() if kind == "tasks" else apple_source.read_calendar()
    if sys.platform != "win32":
        return _unsupported(kind)
    try:
        raw = _run_windows(kind)
    except FileNotFoundError:
        return {"ok": False, "error_code": "needs_install", "status": "needs_install",
                "error": "未找到 PowerShell", "hint": "请安装 Windows PowerShell 或 PowerShell 7"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error_code": "source_timeout", "error": "读取 Outlook 超时",
                "hint": "请确认 Outlook 已安装并能正常打开"}
    except Exception as exc:
        detail = str(exc)
        if "class not registered" in detail.lower() or "无法创建" in detail:
            return {"ok": False, "error_code": "needs_install", "status": "needs_install",
                    "error": "未检测到 Outlook 桌面应用", "hint": "请安装并登录 Microsoft Outlook"}
        return {"ok": False, "error_code": "source_unavailable", "error": "无法读取 Outlook 来源",
                "hint": "请确认 Outlook 已安装、已登录，并允许本机脚本访问"}
    items = _items(raw, kind)
    if not items:
        return {"ok": False, "error_code": "source_empty", "error": "没有未完成的任务" if kind == "tasks" else "未来 7 天没有日程",
                "hint": "在 Outlook 中添加一条后再试"}
    return _package(kind, items)


def read_reminders() -> dict:
    return read("tasks")


def read_calendar() -> dict:
    return read("calendar")
