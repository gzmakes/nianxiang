"""真实来源目录：只列真实可用的 CLI/系统来源，不做演示回退。"""
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import core, git_source, github_source, lark, local_source, real_sources
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    real_sources._CACHE = None
    core.init_db()
    return TestClient(app)


def test_catalog_reflects_real_status(client, monkeypatch):
    monkeypatch.setattr(lark, "auth_status", lambda: {"ok": True, "user_status": "ready"})
    monkeypatch.setattr(local_source, "list_files", lambda: [{"name": "a.md"}])
    monkeypatch.setattr(git_source, "repos", lambda: [Path("/tmp/repo")])
    monkeypatch.setattr(github_source, "status", lambda: {"ok": True})
    d = client.get("/api/onboarding/sources").json()["sources"]
    by = {x["id"]: x for x in d}
    assert by["feishu"]["status"] == "ready"
    assert by["local_files"]["status"] == "ready"
    assert by["git"]["status"] == "ready"
    assert by["github"]["status"] == "ready"


def test_git_read_real_and_no_demo_fallback(client, tmp_path, monkeypatch):
    repo = tmp_path / "demo-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "A"], cwd=repo, check=True)
    (repo / "a.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "真实提交"], cwd=repo, check=True)
    monkeypatch.setattr(git_source, "repos", lambda: [repo])

    r = client.post("/api/onboarding/real/read", json={"source_id": "git"}).json()
    assert r["ok"] is True and r["synthetic"] is False
    assert "真实提交" in r["items"][0]["title"]

    # Start uses the reviewed snapshot, not a second read of changed content.
    monkeypatch.setattr(git_source, "repos", lambda: [])
    s = client.post("/api/onboarding/real/start", json={"source_id": "git", "preview_id": r["preview_id"]}).json()
    assert s["session"]["source_label"] == "本地代码库 · 已连接"
    assert client.post("/api/onboarding/real/start", json={"source_id": "git", "preview_id": r["preview_id"]}).status_code == 400


def test_external_origin_cannot_read_local_api(client):
    response = client.get("/api/config", headers={"Origin": "https://unrelated.example"})
    assert "access-control-allow-origin" not in response.headers


def test_failed_real_source_does_not_fake_demo(client, monkeypatch):
    monkeypatch.setattr(local_source, "read", lambda: {"ok": False, "error": "没有文件", "hint": "放一份"})
    r = client.post("/api/onboarding/real/read", json={"source_id": "local_files"}).json()
    assert r["ok"] is False and "没有文件" in r["error"]
    assert "items" not in r


@pytest.mark.parametrize("status,hint", [("needs_install", "请安装 gh"), ("unavailable", "请检查网络")])
def test_catalog_preserves_github_recovery_status(client, monkeypatch, status, hint):
    monkeypatch.setattr(lark, "auth_status", lambda: {"ok": False})
    monkeypatch.setattr(git_source, "repos", lambda: [])
    monkeypatch.setattr(github_source, "status", lambda: {"ok": False, "status": status, "hint": hint})
    sources = client.get("/api/onboarding/sources?force=1").json()["sources"]
    github = next(source for source in sources if source["id"] == "github")
    assert github["status"] == status and github["hint"] == hint
