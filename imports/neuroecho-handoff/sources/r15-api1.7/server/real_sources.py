"""真实来源目录：只列出本机真的可用的 CLI/系统来源，不伪造演示数据。"""
from __future__ import annotations

import time

from . import apple_source, git_source, github_source, lark, local_source, notion_cli_source, system_source

_CACHE: tuple[float, list[dict]] | None = None


def _lark_ready() -> tuple[bool, str]:
    st = lark.auth_status()
    if not st.get("ok"):
        return False, "lark-cli 不可用"
    if lark.user_ready(st):
        return True, "已授权"
    if st.get("user_status") in ("ready", "needs_refresh") and st.get("token_status") == "needs_refresh":
        # The official CLI renews a still-valid refresh grant on the next API
        # request. Do not force a new device flow merely because access expired.
        return True, "已有授权，读取时检查并续期；失败后可重新授权"
    return False, "授权未就绪或已过期，请重新授权"


def sources(force: bool = False) -> list[dict]:
    global _CACHE
    if not force and _CACHE and time.time() - _CACHE[0] < 12:
        return _CACHE[1]
    lark_ok, lark_msg = _lark_ready()
    repos = git_source.repos()
    gh = github_source.status()
    gh_ok = gh.get("ok", False)
    reminders_id, calendar_id = system_source.platform_ids() or ("apple_reminders", "apple_calendar")
    reminders_status = system_source.status("tasks")
    calendar_status = system_source.status("calendar")
    out = [
        {"id": "feishu", "name": "飞书", "icon": "飞", "blurb": "读取你指定的一篇文档",
         "kind": "可连接", "status": "ready" if lark_ok else "needs_auth",
         "hint": lark_msg, "reads": ["单篇文档"], "mode": "real"},
        {"id": "local_files", "name": "本地文件", "icon": "⌂", "blurb": "由你逐个选择文本文件",
         "kind": "可连接", "status": "ready",
         "hint": "最多 3 份；先预览再确认", "reads": ["仅你选择的文本片段"], "mode": "real"},
        {"id": "git", "name": "本地代码库", "icon": "git", "blurb": "最近提交",
         "kind": "可连接", "status": "ready" if repos else "needs_config",
         "hint": "由你填写代码库目录；只读该库最近最多 8 条提交",
         "reads": ["所选代码库最近最多 8 条提交"], "mode": "real"},
        {"id": "github", "name": "GitHub", "icon": "gh", "blurb": "我的 PR",
         "kind": "可连接", "status": "ready" if gh_ok else gh.get("status", "needs_auth"),
         "hint": gh.get("hint") or ("GitHub CLI 已登录" if gh_ok else "终端执行 gh auth login -h github.com"),
         "reads": ["最近 PR"], "mode": "real"},
        {"id": reminders_id, "name": "提醒事项" if reminders_id == "apple_reminders" else "Outlook 任务", "icon": "✓", "blurb": "未完成提醒",
         "kind": "可连接" if reminders_status["status"] == "conditions_required" else "当前平台不可用",
         "status": "needs_click" if reminders_status["status"] == "conditions_required" else reminders_status["status"],
         "hint": reminders_status["hint"],
         "reads": ["未完成提醒"], "mode": "real"},
        {"id": calendar_id, "name": "Apple 日历" if calendar_id == "apple_calendar" else "Outlook 日历", "icon": "日", "blurb": "未来 7 天日程",
         "kind": "可连接" if calendar_status["status"] == "conditions_required" else "当前平台不可用",
         "status": "needs_click" if calendar_status["status"] == "conditions_required" else calendar_status["status"],
         "hint": calendar_status["hint"],
         "reads": ["未来 7 天日程"], "mode": "real"},
        {"id": "notion", "name": "Notion", "icon": "N", "blurb": "页面或数据库",
         "kind": "可连接", "status": "needs_config", "hint": notion_cli_source.status()["hint"],
         "reads": ["页面/数据库"], "mode": "real"},
        {"id": "gmail", "name": "Gmail", "icon": "M", "blurb": "最近未读邮件头",
         "kind": "可连接", "status": "needs_config", "hint": "可在运行念响的电脑上连接 Google 账号；也可使用应用专用密码",
         "reads": ["未读邮件头"], "mode": "real"},
    ]
    order = {"ready": 0, "needs_click": 1, "needs_config": 2, "needs_auth": 3, "unavailable": 4, "needs_install": 5, "empty": 6}
    result = sorted(out, key=lambda x: order.get(x["status"], 9))
    _CACHE = (time.time(), result)
    return result


def read(source_id: str) -> dict:
    if source_id == "local_files":
        return local_source.read()
    if source_id == "apple_reminders":
        return apple_source.read_reminders()
    if source_id == "apple_calendar":
        return apple_source.read_calendar()
    if source_id == "windows_reminders":
        return system_source.read_reminders()
    if source_id == "windows_calendar":
        return system_source.read_calendar()
    if source_id == "git":
        return git_source.read()
    if source_id == "github":
        return github_source.read()
    if source_id == "feishu":
        return {"ok": False, "error": "需要指定飞书文档", "hint": "在下一步粘贴文档链接", "needs": "url"}
    if source_id == "notion":
        return {"ok": False, "error": "需要 Notion token", "hint": "在下一步填写 token + 链接", "needs": "config"}
    if source_id == "gmail":
        return {"ok": False, "error": "可在运行念响的电脑上连接 Google 账号；也可使用应用专用密码", "hint": "在下一步填写地址 + 密码", "needs": "config"}
    return {"ok": False, "error": "未知来源", "hint": ""}
