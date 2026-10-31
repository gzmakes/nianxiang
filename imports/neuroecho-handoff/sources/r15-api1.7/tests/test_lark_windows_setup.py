import os
import subprocess
from pathlib import Path

from server import lark, lark_auth


def test_explicit_cli_override(monkeypatch):
    monkeypatch.setenv("XINJI_LARK_BIN", "custom-cli")
    assert lark.resolve_cli() == "custom-cli"


def test_windows_npm_shim_resolves_native_binary(tmp_path, monkeypatch):
    if os.name != "nt":
        return
    native = tmp_path / "node_modules/@larksuite/cli/bin/lark-cli.exe"
    native.parent.mkdir(parents=True)
    native.touch()
    monkeypatch.delenv("XINJI_LARK_BIN", raising=False)
    monkeypatch.setattr(lark.shutil, "which", lambda _: str(tmp_path / "lark-cli.cmd"))
    assert Path(lark.resolve_cli()) == native


def test_unconfigured_error_explains_setup_without_raw_output():
    response = subprocess.CompletedProcess([], 1, '{"error":{"subtype":"not_configured"},"secret":"private"}', '')
    error = lark_auth._cli_error(response, "启动授权")
    assert "重新点击" in error
    assert "private" not in error
