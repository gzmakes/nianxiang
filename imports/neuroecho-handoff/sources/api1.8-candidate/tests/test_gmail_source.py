"""Gmail 真实只读（IMAP 应用专用密码，只读邮件头）。"""
import imaplib
import pytest
from fastapi.testclient import TestClient

from server import core, gmail_source, main
from server.main import app


HEADER = b"Subject: =?utf-8?b?5ryU56S65o+Q6YaS?=\r\nFrom: demo@example.com\r\nDate: Wed, 28 Oct 2026 10:00:00 +0800\r\n\r\n"


class FakeIMAP:
    def __init__(self, host, timeout):
        pass
    def login(self, a, p):
        if p == "bad":
            raise imaplib.IMAP4.error("bad")
    def select(self, box, readonly=False):
        assert readonly is True
        return "OK", [b"1"]
    def search(self, charset, q):
        return "OK", [b"1 2"]
    def fetch(self, mid, spec):
        return "OK", [(b"1", HEADER)]
    def logout(self):
        pass


def test_imap_connect_uses_default_tls_port_and_explicit_timeout(monkeypatch):
    from unittest.mock import MagicMock

    connection = MagicMock()
    factory = MagicMock(return_value=connection)
    monkeypatch.setattr(gmail_source.imaplib, "IMAP4_SSL", factory)

    assert gmail_source._connect("demo@example.com", "example-password") is connection
    factory.assert_called_once_with("imap.gmail.com", timeout=gmail_source.TIMEOUT)
    connection.login.assert_called_once_with("demo@example.com", "example-password")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(gmail_source.imaplib, "IMAP4_SSL", FakeIMAP)
    core.init_db()
    return TestClient(app)


def test_gmail_preview_real(client):
    r = client.post("/api/gmail/preview", json={"address": "demo@gmail.com", "password": "app-pass"}).json()
    assert r["ok"] is True and r["synthetic"] is False
    assert len(r["items"]) == 2
    assert "演示" in r["items"][0]["title"]


def test_gmail_start_and_bad_password(client, monkeypatch):
    preview = client.post("/api/gmail/preview", json={"address": "demo@gmail.com", "password": "app-pass"}).json()
    with monkeypatch.context() as m:
        m.setattr(gmail_source, "read", lambda *args: pytest.fail("start must use the preview snapshot"))
        s = client.post("/api/gmail/start", json={"preview_id": preview["preview_id"]}).json()
    assert s["session"]["source_label"] == "Gmail · 已连接"
    assert s["context"]["connector_id"] == "gmail"
    assert s["context"]["items"] == preview["items"]
    assert client.post("/api/gmail/start", json={"preview_id": preview["preview_id"]}).status_code == 400

    b = client.post("/api/gmail/preview", json={"address": "demo@gmail.com", "password": "bad"}).json()
    assert b["ok"] is False and "登录失败" in b["error"]


def test_preview_expiry_and_wrong_source_are_rejected(client):
    body = {"address": "demo@gmail.com", "password": "app-pass"}
    preview_id = client.post("/api/gmail/preview", json=body).json()["preview_id"]
    created, source, snapshot = main._source_previews[preview_id]
    assert "app-pass" not in repr(snapshot)
    main._source_previews[preview_id] = (created - main._PREVIEW_TTL - 1, source, snapshot)
    assert client.post("/api/gmail/start", json={"preview_id": preview_id}).status_code == 400

    preview_id = client.post("/api/gmail/preview", json=body).json()["preview_id"]
    assert client.post("/api/notion/start", json={"preview_id": preview_id}).status_code == 400
    assert client.post("/api/gmail/start", json={"preview_id": preview_id, "password": "app-pass"}).status_code == 422


@pytest.mark.parametrize("failing_stage", ["select", "search", "fetch"])
def test_failed_read_is_explicit_and_always_logs_out(monkeypatch, failing_stage):
    calls = []
    class Connection(FakeIMAP):
        def select(self, box, readonly=False):
            assert readonly is True
            return ("NO", []) if failing_stage == "select" else ("OK", [b"1"])
        def search(self, charset, q):
            return ("BAD", []) if failing_stage == "search" else ("OK", [b"1"])
        def fetch(self, mid, spec):
            assert "BODY.PEEK" in spec
            return ("NO", []) if failing_stage == "fetch" else ("OK", [(b"1", HEADER)])
        def logout(self):
            calls.append("logout")
    monkeypatch.setattr(gmail_source, "_connect", lambda *args: Connection("host", 1))
    result = gmail_source.read("demo@gmail.com", "synthetic-password")
    assert result["ok"] is False
    assert "没有未读" not in result["error"]
    assert calls == ["logout"]


def test_failed_login_closes_connection_without_echoing_server_text(monkeypatch):
    from unittest.mock import MagicMock
    connection = MagicMock()
    connection.login.side_effect = imaplib.IMAP4.error("synthetic-private-server-reply")
    monkeypatch.setattr(gmail_source.imaplib, "IMAP4_SSL", lambda *args, **kwargs: connection)
    result = gmail_source.read("demo@gmail.com", "synthetic-password")
    assert result["ok"] is False and "登录失败" in result["error"]
    assert "synthetic-private" not in repr(result)
    connection.logout.assert_called_once()


def test_interrupted_read_does_not_tell_user_password_is_wrong(monkeypatch):
    from unittest.mock import MagicMock
    connection = MagicMock()
    connection.select.side_effect = imaplib.IMAP4.abort("synthetic-private-server-reply")
    monkeypatch.setattr(gmail_source, "_connect", lambda *args: connection)
    result = gmail_source.read("demo@gmail.com", "synthetic-password")
    assert "读取连接已中断" in result["error"]
    assert "无需更换密码" in result["hint"]
    assert "synthetic-private" not in repr(result)
    connection.logout.assert_called_once()
