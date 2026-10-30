"""Explicit local repository selection, using temporary synthetic repositories."""
import os
import subprocess
from pathlib import Path

import pytest

from server import git_source


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def repository(tmp_path, name="selected-repo", commits=1):
    repo = tmp_path / name
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Synthetic User")
    git(repo, "config", "user.email", "synthetic@example.invalid")
    for number in range(commits):
        (repo / "example.txt").write_text(f"synthetic {number}")
        git(repo, "add", "example.txt")
        git(repo, "commit", "-qm", f"Synthetic commit {number}")
    return repo


def test_selected_repo_reads_only_metadata_and_never_discovers_others(tmp_path, monkeypatch):
    repo = repository(tmp_path, "repo with spaces $(do-not-run)", commits=10)
    monkeypatch.setattr(git_source, "repos", lambda: pytest.fail("explicit selection must not discover other repositories"))
    calls = []
    original = git_source._run
    def capture(args):
        calls.append(args)
        return original(args)
    monkeypatch.setattr(git_source, "_run", capture)
    result = git_source.read(path=str(repo), limit=100)
    assert result["ok"] is True and result["synthetic"] is False
    assert result["selected_path"] == str(repo.resolve())
    assert len(result["items"]) == 8
    assert result["items"][0]["title"] == "Synthetic commit 9"
    assert all(str(repo) in args for args in calls)
    assert len(calls) == 3
    assert calls[-1][-2] == "-8"
    assert not any(arg in ("show", "diff", "fetch", "pull", "status") for args in calls for arg in args)


def test_subdirectory_resolves_to_actual_repository_root(tmp_path):
    repo = repository(tmp_path)
    subdir = repo / "src"
    subdir.mkdir()
    result = git_source.read(path=str(subdir))
    assert result["ok"] is True
    assert result["selected_path"] == str(repo.resolve())


@pytest.mark.parametrize("kind", ["missing", "file", "plain", "bare", "empty", "relative"])
def test_invalid_or_unreadable_selection_has_actionable_error(tmp_path, kind):
    path = tmp_path / "selected"
    if kind == "file":
        path.write_text("synthetic")
    elif kind == "plain":
        path.mkdir()
    elif kind == "bare":
        subprocess.run(["git", "init", "--bare", "-q", str(path)], check=True)
    elif kind == "empty":
        path = repository(tmp_path, "empty", commits=0)
    elif kind == "relative":
        path = Path("relative-project")
    result = git_source.read(path=str(path))
    assert result["ok"] is False
    assert result.get("error") and result.get("hint")
    assert "items" not in result


def test_linked_git_worktree_is_supported(tmp_path):
    repo = repository(tmp_path)
    linked = tmp_path / "linked-worktree"
    git(repo, "worktree", "add", "--detach", str(linked), "HEAD")
    assert (linked / ".git").is_file()
    result = git_source.read(path=str(linked))
    assert result["ok"] is True and len(result["items"]) == 1
    assert result["selected_path"] == str(linked.resolve())


def test_git_invocation_uses_argv_and_ignores_inherited_repository_override(monkeypatch):
    calls = []
    monkeypatch.setenv("GIT_DIR", "/synthetic/other-repository/.git")
    monkeypatch.setenv("GIT_WORK_TREE", "/synthetic/other-repository")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "synthetic")
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, "synthetic", "")
    monkeypatch.setattr(git_source.subprocess, "run", run)
    args = ["git", "-C", "/synthetic/repo $(literal)", "log", "-8"]
    assert git_source._run(args) == "synthetic"
    actual, options = calls[0]
    assert actual == args and not options.get("shell", False)
    assert options["stdin"] == subprocess.DEVNULL
    assert not any(key in options["env"] for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_CONFIG_COUNT", "GIT_CONFIG_VALUE_0"))
    assert options["env"]["GIT_OPTIONAL_LOCKS"] == "0"
