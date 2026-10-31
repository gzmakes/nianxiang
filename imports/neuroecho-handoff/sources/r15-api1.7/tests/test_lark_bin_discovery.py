"""Portable CLI discovery and Finder environment tests; no real CLI/login."""
import os
from pathlib import Path
import subprocess

from server import lark, lark_auth


def executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o700)
    return path


def test_explicit_executable_wins_over_path(monkeypatch, tmp_path):
    explicit = executable(tmp_path / "custom/lark-cli")
    on_path = executable(tmp_path / "path/lark-cli")
    monkeypatch.setenv("XINJI_LARK_BIN", str(explicit))
    monkeypatch.setattr(lark.shutil, "which", lambda name: str(on_path))
    assert lark.discover_lark_bin() == str(explicit)


def test_path_discovery_ignores_invalid_explicit_override(monkeypatch, tmp_path):
    invalid = tmp_path / "not-executable"
    invalid.write_text("not executable")
    valid = executable(tmp_path / "path/lark-cli")
    monkeypatch.setenv("XINJI_LARK_BIN", str(invalid))
    monkeypatch.setattr(lark.shutil, "which", lambda name: str(valid))
    assert lark.discover_lark_bin() == str(valid)


def test_current_home_fallback_uses_the_current_user(monkeypatch, tmp_path):
    valid = executable(tmp_path / ".npm-global/bin/lark-cli")
    monkeypatch.delenv("XINJI_LARK_BIN", raising=False)
    monkeypatch.setattr(lark.shutil, "which", lambda name: None)
    monkeypatch.setattr(lark.Path, "home", classmethod(lambda cls: tmp_path))
    assert lark.discover_lark_bin() == str(valid)


def test_missing_cli_returns_command_for_existing_installation_error(monkeypatch, tmp_path):
    monkeypatch.setenv("XINJI_LARK_BIN", str(tmp_path / "missing"))
    monkeypatch.setattr(lark.shutil, "which", lambda name: None)
    monkeypatch.setattr(lark, "_standard_bin_dirs", lambda: [tmp_path / "missing-bin"])
    assert lark.discover_lark_bin() == "lark-cli"


def test_finder_env_retains_path_home_and_does_not_modify_process(monkeypatch, tmp_path):
    local_bin = tmp_path / ".local/bin"
    local_bin.mkdir(parents=True)
    missing = tmp_path / "missing-bin"
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XINJI_LARK_HOME", raising=False)
    monkeypatch.setattr(lark, "_standard_bin_dirs", lambda: [local_bin, missing, local_bin])
    result = lark.cli_env()
    assert result["PATH"] == f"/usr/bin:/bin:{local_bin}" and result["HOME"] == str(tmp_path)
    assert os.environ["PATH"] == "/usr/bin:/bin" and os.environ["HOME"] == str(tmp_path)


def test_missing_node_is_dependency_error_not_authorization(monkeypatch):
    failed = subprocess.CompletedProcess([], 127, "", "env: node: No such file or directory\nPRIVATE")
    result = lark.cli_dependency_failure(failed)
    assert result["error_code"] == "cli_dependency_missing" and "PRIVATE" not in repr(result)
    monkeypatch.setattr(lark.subprocess, "run", lambda *args, **kwargs: failed)
    monkeypatch.setattr(lark.faults, "active", lambda *args: False)
    assert lark.auth_status()["error_code"] == "cli_dependency_missing"
    assert lark.read_doc("https://team.feishu.cn/docx/Synthetic")["error_code"] == "cli_dependency_missing"
    assert lark.search_docs("Synthetic")["error_code"] == "cli_dependency_missing"
    assert "Node.js" in lark_auth._cli_error(failed, "启动授权")
    assert lark.cli_dependency_failure(subprocess.CompletedProcess([], 1, "", "permission denied")) is None
