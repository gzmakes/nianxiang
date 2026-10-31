from __future__ import annotations

from server import api_contract, github_source, git_source, lark, notion_cli_source, real_sources, system_source


def test_windows_real_source_catalog_uses_windows_system_ids(monkeypatch):
    monkeypatch.setattr(system_source.sys, "platform", "win32")
    monkeypatch.setattr(system_source, "_powershell", lambda: "powershell.exe")
    monkeypatch.setattr(lark, "auth_status", lambda: {"ok": False})
    monkeypatch.setattr(git_source, "repos", lambda: [])
    monkeypatch.setattr(github_source, "status", lambda: {"ok": False, "status": "needs_install", "hint": "安装 gh"})
    monkeypatch.setattr(notion_cli_source, "status", lambda: {"installed": False, "hint": "安装 ntn"})
    real_sources._CACHE = None

    rows = real_sources.sources(force=True)
    by_id = {row["id"]: row for row in rows}
    assert by_id["windows_reminders"]["name"] == "Outlook 任务"
    assert by_id["windows_calendar"]["name"] == "Outlook 日历"
    assert by_id["windows_calendar"]["status"] == "needs_click"
    assert "Outlook" in by_id["windows_calendar"]["hint"]


def test_windows_capabilities_describe_outlook_sources(monkeypatch):
    monkeypatch.setattr(api_contract.sys, "platform", "win32")
    data = api_contract.capabilities(chat_budget=40, budget_window_minutes=60)
    assert data["platform_status"]["windows_calendar"] == "conditions_required"
    assert data["platform_status"]["windows_reminders"] == "conditions_required"
    assert data["features"]["service_windows_calendar_reminders"] is True
