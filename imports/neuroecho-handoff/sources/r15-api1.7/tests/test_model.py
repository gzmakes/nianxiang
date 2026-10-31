"""模型适配器与降级路径（PRD F13）。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from server import core, model
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    core.init_db()
    return TestClient(app)


def test_config_rule_mode(client, monkeypatch):
    for k in ("XINJI_MODEL_BASE_URL", "XINJI_MODEL_API_KEY", "XINJI_MODEL_NAME"):
        monkeypatch.delenv(k, raising=False)
    cfg = client.get("/api/config").json()
    assert cfg["model"]["mode"] == "rule"
    assert cfg["model"]["configured"] is False


def test_model_client_http():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n))
            assert body["model"] == "fake-model"
            assert self.headers.get("Authorization") == "Bearer test-key"
            out = {"choices": [{"message": {"content": "模型说：我在。"}}]}
            data = json.dumps(out, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        cli = model.ModelClient(f"http://127.0.0.1:{srv.server_port}/v1", "test-key", "fake-model")
        assert cli.complete("sys", "user") == "模型说：我在。"
    finally:
        srv.shutdown()


def test_chat_uses_model_when_configured(client, monkeypatch):
    class Fake:
        model = "fake-model"

        def complete(self, system, user):
            assert "念响" in system
            return "模型回复：先确认你说的这一步。"

    monkeypatch.setattr(core.model, "from_env", lambda: Fake())
    sid = client.post("/api/session", json={"mode": "paste", "text": "测试项目正在整理交互原型。测试团队准备下一轮演示。测试资料记录当前计划。测试选择先确认范围。测试安排稍后核对记录。"}).json()["session"]["id"]
    r = client.post("/api/chat", json={"session_id": sid, "text": "你在吗"})
    assert r.status_code == 200
    assert r.json()["reply"].startswith("模型回复")
    audit = client.get(f"/api/audit?session_id={sid}").json()["events"]
    assert any(e["action"] == "model.call" for e in audit)


def test_chat_falls_back_on_model_error(client, monkeypatch):
    class Broken:
        model = "broken"

        def complete(self, system, user):
            raise model.ModelError("timeout")

    monkeypatch.setattr(core.model, "from_env", lambda: Broken())
    sid = client.post("/api/session", json={"mode": "paste", "text": "测试项目正在整理交互原型。测试团队准备下一轮演示。测试资料记录当前计划。测试选择先确认范围。测试安排稍后核对记录。"}).json()["session"]["id"]
    r = client.post("/api/chat", json={"session_id": sid, "text": "你在吗"})
    assert r.status_code == 200
    assert "我在听" in r.json()["reply"]
    audit = client.get(f"/api/audit?session_id={sid}").json()["events"]
    assert any(e["action"] == "model.fallback" for e in audit)
