"""CLI path discovery with a synthetic home and without invoking the CLI."""
import subprocess
import sys
from pathlib import Path


def test_lark_fallback_uses_running_users_home(tmp_path):
    env = {"HOME": str(tmp_path), "PATH": "", "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    result = subprocess.run(
        [sys.executable, "-c", "from server.lark import LARK_BIN; print(LARK_BIN)"],
        env=env, text=True, capture_output=True, check=True,
    )
    assert result.stdout.strip() == str(Path(tmp_path) / ".npm-global" / "bin" / "lark-cli")


def test_explicit_lark_override_takes_precedence(tmp_path):
    env = {"HOME": str(tmp_path), "PATH": "", "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "XINJI_LARK_BIN": "/synthetic/lark-cli"}
    result = subprocess.run(
        [sys.executable, "-c", "from server.lark import LARK_BIN; print(LARK_BIN)"],
        env=env, text=True, capture_output=True, check=True,
    )
    assert result.stdout.strip() == "/synthetic/lark-cli"
