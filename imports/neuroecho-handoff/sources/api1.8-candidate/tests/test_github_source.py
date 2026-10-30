"""GitHub queries use only mocked CLI results."""
import json
import subprocess

from server import github_source


def test_requests_authored_prs_ordered_by_last_update(monkeypatch):
    calls = []
    def fake_run(args):
        calls.append(args)
        data = [{"title": "Sample PR", "repository": {"nameWithOwner": "example/repo"},
                 "state": "open", "updatedAt": "2026-10-29T00:00:00Z", "url": "https://example.invalid/pr/1"}]
        return subprocess.CompletedProcess(args, 0, json.dumps(data), "")
    monkeypatch.setattr(github_source, "_run", fake_run)
    result = github_source.read()
    assert result["ok"]
    assert calls[0][calls[0].index("--author") + 1] == "@me"
    assert calls[0][calls[0].index("--sort") + 1] == "updated"
    assert calls[0][calls[0].index("--order") + 1] == "desc"


def test_empty_and_failure_are_not_misrepresented(monkeypatch):
    monkeypatch.setattr(github_source, "_run", lambda args: subprocess.CompletedProcess(args, 0, "[]", ""))
    assert "创建的 PR" in github_source.read()["error"]
    monkeypatch.setattr(github_source, "_run", lambda args: subprocess.CompletedProcess(args, 1, "", "network failure"))
    assert github_source.read()["error"] == "GitHub PR 查询失败"


def test_timeout_is_reported_separately(monkeypatch):
    def timeout(args):
        raise subprocess.TimeoutExpired(args, 12)
    monkeypatch.setattr(github_source, "_run", timeout)
    assert "超时" in github_source.read()["error"]


def test_status_targets_github_and_does_not_expose_account_output(monkeypatch):
    calls = []
    def fake(args):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "synthetic-account-and-token", "")
    monkeypatch.setattr(github_source, "_run", fake)
    result = github_source.status()
    assert result["ok"] is True and result["status"] == "ready"
    assert calls == [["auth", "status", "--hostname", "github.com"]]
    assert "synthetic-account" not in repr(result)


def test_missing_cli_differs_from_login_and_network_failure(monkeypatch):
    def missing(args):
        raise FileNotFoundError("synthetic-private-path")
    monkeypatch.setattr(github_source, "_run", missing)
    assert github_source.status()["status"] == "needs_install"
    assert "尚未安装" in github_source.read()["error"]
    assert "synthetic-private-path" not in repr(github_source.status())
    monkeypatch.setattr(github_source, "_run", lambda args: subprocess.CompletedProcess(args, 1, "", "error connecting to api.github.com: synthetic-account"))
    assert github_source.status()["status"] == "unavailable"
    assert "无需重新授权" in github_source.read()["hint"]
    assert "synthetic-account" not in repr(github_source.read())


def test_malformed_cli_json_is_not_a_success(monkeypatch):
    monkeypatch.setattr(github_source, "_run", lambda args: subprocess.CompletedProcess(args, 0, '{"error":"unexpected"}', ""))
    assert github_source.read()["ok"] is False
