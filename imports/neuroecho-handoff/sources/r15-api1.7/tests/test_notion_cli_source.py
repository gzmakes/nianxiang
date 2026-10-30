"""Official Notion CLI adapter: synthetic subprocess responses only."""
import json
import subprocess

from server import notion_cli_source

PAGE = "https://www.notion.so/1234567890abcdef1234567890abcdef"


def test_cli_reads_only_get_for_explicit_page_and_no_credentials_in_args(monkeypatch):
    calls = []
    monkeypatch.setattr(notion_cli_source, "executable", lambda: "/synthetic/ntn")
    def fake(args, **kwargs):
        calls.append((args, kwargs))
        value = {"properties": {"title": {"type": "title", "title": [{"plain_text": "Synthetic page"}]}}} if "/pages/" in args[2] else {
            "results": [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Synthetic content"}]}}]}
        return subprocess.CompletedProcess(args, 0, json.dumps(value), "")
    monkeypatch.setattr(notion_cli_source.subprocess, "run", fake)
    result = notion_cli_source.read(PAGE)
    assert result["ok"] is True and result["synthetic"] is False
    assert result["source"] == "notion-cli"
    assert len(calls) == 2
    for args, kwargs in calls:
        assert args[args.index("-X") + 1] == "GET"
        assert "--data" not in args and "login" not in args
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert "shell" not in kwargs
    assert "page_size==50" in calls[1][0]


def test_status_checks_installation_only_and_does_not_call_cli(monkeypatch):
    monkeypatch.setattr(notion_cli_source, "executable", lambda: "/synthetic/ntn")
    monkeypatch.setattr(notion_cli_source.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not inspect auth")))
    assert notion_cli_source.status() == {"installed": True, "auth_checked": False, "hint": "可使用本机 Notion CLI 的既有登录，读取你指定的单页"}


def test_auth_failure_hides_raw_cli_output_and_has_recovery(monkeypatch):
    monkeypatch.setattr(notion_cli_source, "executable", lambda: "/synthetic/ntn")
    monkeypatch.setattr(notion_cli_source.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 1, "", "not authenticated synthetic-private-token"))
    result = notion_cli_source.read(PAGE)
    assert result["ok"] is False and "ntn login" in result["hint"]
    assert "synthetic-private" not in repr(result)


def test_timeout_and_invalid_page_do_not_become_success(monkeypatch):
    monkeypatch.setattr(notion_cli_source, "executable", lambda: "/synthetic/ntn")
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired([], 15)
    monkeypatch.setattr(notion_cli_source.subprocess, "run", timeout)
    assert "超时" in notion_cli_source.read(PAGE)["error"]
    assert "无法识别" in notion_cli_source.read("not a page")["error"]
