from __future__ import annotations

from server import system_source


def test_windows_status_without_powershell(monkeypatch):
    monkeypatch.setattr(system_source.sys, "platform", "win32")
    monkeypatch.setattr(system_source, "_powershell", lambda: None)
    result = system_source.status("tasks")
    assert result["status"] == "needs_install"
    assert "PowerShell" in result["hint"]


def test_windows_tasks_uses_same_preview_shape(monkeypatch):
    monkeypatch.setattr(system_source.sys, "platform", "win32")
    monkeypatch.setattr(system_source, "_powershell", lambda: "powershell.exe")
    monkeypatch.setattr(system_source, "_run_windows", lambda kind: "整理演示脚本||2026-11-01\n")
    result = system_source.read_reminders()
    assert result["ok"] is True
    assert result["connector"]["id"] == "windows_reminders"
    assert result["source"] == "windows-outlook"
    assert result["synthetic"] is False
    assert result["items"][0]["title"] == "整理演示脚本"


def test_windows_outlook_failure_is_recoverable(monkeypatch):
    monkeypatch.setattr(system_source.sys, "platform", "win32")
    monkeypatch.setattr(system_source, "_powershell", lambda: "powershell.exe")
    monkeypatch.setattr(system_source, "_run_windows", lambda kind: (_ for _ in ()).throw(RuntimeError("class not registered")))
    result = system_source.read_calendar()
    assert result["ok"] is False
    assert result["error_code"] == "needs_install"
    assert "Outlook" in result["hint"]


def test_non_supported_platform_does_not_fabricate(monkeypatch):
    monkeypatch.setattr(system_source.sys, "platform", "linux")
    result = system_source.read_calendar()
    assert result["ok"] is False
    assert result["error_code"] == "platform_unsupported"
    assert "items" not in result
