"""Adapter contract tests using fake CLI outputs; no login, credentials or network."""
import json
import subprocess

import pytest

from server import lark, lark_auth, lark_auth_coordinator, real_sources


@pytest.fixture(autouse=True)
def reset_auth_state(monkeypatch):
    monkeypatch.setattr(lark_auth_coordinator, "_active", None)
    monkeypatch.setattr(lark_auth, "STATE", {"status": "idle", "url": "", "qr": "", "error": "", "started_at": 0})
    monkeypatch.setattr(lark.faults, "active", lambda *args: False)


def proc(returncode=0, out="", err=""):
    return subprocess.CompletedProcess(args=["fake-cli"], returncode=returncode, stdout=out, stderr=err)


def test_real_doc_adapter_calls_cli_and_caps_clean_text(monkeypatch):
    calls = []
    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return proc(out=json.dumps({"ok": True, "data": {"document": {"content": "# My test\\n" + "a" * 20000}}}))
    monkeypatch.setattr(lark.subprocess, "run", fake_run)
    result = lark.read_doc("https://example.invalid/docx/test")
    assert result["ok"] is True and result["length"] == lark.MAX_CHARS
    assert result["truncated"] is True and result["extracted_length"] > result["length"]
    assert calls[0][1]["timeout"] == 25
    assert calls[0][0][1:3] == ["docs", "+fetch"]
    assert "--as" in calls[0][0] and "user" in calls[0][0]


@pytest.mark.parametrize("size", [1, lark.MAX_CHARS, lark.MAX_CHARS + 1])
def test_document_truncation_is_reported_accurately(monkeypatch, size):
    monkeypatch.setattr(lark.subprocess, "run", lambda *a, **kw: proc(out=json.dumps({
        "ok": True, "data": {"document": {"content": "文" * size}}
    })))
    result = lark.read_doc("https://example.invalid/docx/synthetic")
    assert result["text"] == "文" * min(size, lark.MAX_CHARS)
    assert result["extracted_length"] == size
    assert result["truncated"] is (size > lark.MAX_CHARS)


def test_cli_nonzero_and_malformed_cannot_report_success(monkeypatch):
    monkeypatch.setattr(lark.subprocess, "run", lambda *a, **kw: proc(1, out=json.dumps({"ok": True})))
    assert lark.read_doc("https://example.invalid/docx/test")["ok"] is False
    monkeypatch.setattr(lark.subprocess, "run", lambda *a, **kw: proc(1, err="private fake text"))
    result = lark.read_doc("https://example.invalid/docx/test")
    assert result["ok"] is False and "private fake text" not in repr(result)
    assert lark.auth_status()["ok"] is False


def test_auth_status_checks_structure_and_exit_code(monkeypatch):
    response = {"identities": {"user": {"status": "ready", "tokenStatus": "valid"}}}
    monkeypatch.setattr(lark.subprocess, "run", lambda *a, **kw: proc(out=json.dumps(response)))
    assert lark.auth_status()["user_status"] == "ready"
    monkeypatch.setattr(lark.subprocess, "run", lambda *a, **kw: proc(out=json.dumps({"ok": False})))
    assert lark.auth_status()["ok"] is False
    monkeypatch.setattr(lark.subprocess, "run", lambda *a, **kw: proc(1, out=json.dumps(response)))
    assert lark.auth_status()["ok"] is False


def test_qr_unavailable_still_returns_opaque_clickable_url(monkeypatch):
    url = "https://example.invalid/auth?code=a%2Bb&x=1"
    monkeypatch.setattr(lark, "auth_status", lambda: {"ok": True, "user_status": "not_authorized"})
    calls = []
    monkeypatch.setattr(lark_auth, "_run", lambda args, timeout: calls.append((args, timeout)) or proc(out=json.dumps({"verification_url": url, "device_code": "fake-device-code"})))
    def fail_qr(_):
        raise ImportError("missing qrcode")
    monkeypatch.setattr(lark_auth, "_qr_data_url", fail_qr)
    started = []
    class FakeThread:
        def __init__(self, **kwargs):
            self.args = kwargs["args"]
        def start(self):
            started.append(self.args)
    monkeypatch.setattr(lark_auth.threading, "Thread", FakeThread)
    result = lark_auth.start()
    assert result["status"] == "pending" and result["url"] == url and result["qr"] == ""
    assert "device_code" not in result
    assert len(started) == 1 and started[0][0] == "fake-device-code" and started[0][1] == 1
    assert calls[0][0] == ["auth", "login", "--no-wait", "--json", "--scope", lark_auth.SCOPE]


def test_start_cli_failure_reports_exit_without_exposing_output(monkeypatch):
    monkeypatch.setattr(lark, "auth_status", lambda: {"ok": True, "user_status": "not_authorized"})
    monkeypatch.setattr(lark_auth, "_run", lambda *a, **kw: proc(7, err="private fake text"))
    result = lark_auth.start()
    assert result["status"] == "error" and "退出码 7" in result["error"]
    assert "private fake text" not in repr(result)


def test_complete_failed_cli_cannot_become_success(monkeypatch):
    monkeypatch.setattr(lark_auth, "_run", lambda *a, **kw: proc(9, err="private fake text"))
    monkeypatch.setattr(lark, "auth_status", lambda: pytest.fail("must not check success on failed CLI"))
    lark_auth.STATE.update(status="pending", url="sensitive-url", qr="fake-qr", attempt=1)
    _, token = lark_auth_coordinator.begin("document")
    lark_auth._complete("fake-device-code", 1, token)
    assert lark_auth.STATE["status"] == "error" and "退出码 9" in lark_auth.STATE["error"]
    assert lark_auth.STATE["url"] == "" and lark_auth.STATE["qr"] == ""
    assert "private fake text" not in repr(lark_auth.STATE)


def test_search_explicitly_uses_user_identity(monkeypatch):
    calls = []
    def fake_run(argv, **kwargs):
        calls.append(argv)
        return proc(out=json.dumps({"ok": True, "data": {"items": []}}))
    monkeypatch.setattr(lark.subprocess, "run", fake_run)
    assert lark.search_docs("example")["ok"]
    assert calls[0][calls[0].index("--as") + 1] == "user"


def test_search_adapts_search_v2_result_meta(monkeypatch):
    result = {"ok": True, "data": {"results": [{
        "entity_type": "DOC", "title_highlighted": "<h>念响</h> PRD V0.4",
        "result_meta": {"doc_types": "MIAODA_APP_DEVELOPMENT", "url": "https://miaoda.feishu.cn/app/app_fake"},
    }, {
        "entity_type": "DOC", "title_highlighted": "<hb>计划</hb> &amp; 项目",
        "result_meta": {"doc_types": "DOCX", "url": "https://example.feishu.cn/docx/fake"},
    }]}}
    monkeypatch.setattr(lark.subprocess, "run", lambda *a, **kw: proc(out=json.dumps(result)))
    items = lark.search_docs("example")["items"]
    assert items == [
        {"title": "念响 PRD V0.4", "url": "https://miaoda.feishu.cn/app/app_fake", "type": "MIAODA_APP_DEVELOPMENT"},
        {"title": "计划 & 项目", "url": "https://example.feishu.cn/docx/fake", "type": "DOCX"},
    ]


def test_search_does_not_fabricate_docx_url_for_unknown_type(monkeypatch):
    data = {"ok": True, "data": {"results": [
        {"title": "app", "token": "app_fake", "result_meta": {"doc_types": "MIAODA_APP_DEVELOPMENT"}},
        {"title": "doc", "token": "doc_fake", "result_meta": {"doc_types": "DOCX"}},
    ]}}
    monkeypatch.setattr(lark.subprocess, "run", lambda *a, **kw: proc(out=json.dumps(data)))
    items = lark.search_docs("example")["items"]
    assert items[0]["url"] == ""
    assert items[1]["url"] == "https://feishu.cn/docx/doc_fake"


def test_expired_token_is_not_reported_as_connected(monkeypatch):
    monkeypatch.setattr(lark, "auth_status", lambda: {"ok": True, "user_status": "ready", "token_status": "expired"})
    assert real_sources._lark_ready()[0] is False
    lark_auth.STATE.update(status="success")
    assert lark_auth.status()["status"] != "success"
    monkeypatch.setattr(lark_auth, "_run", lambda *a, **kw: proc(7))
    assert lark_auth.start()["status"] == "error"


def test_refreshable_access_token_keeps_read_path_without_claiming_valid(monkeypatch):
    refreshable = {'ok': True, 'user_status':'needs_refresh', 'token_status':'needs_refresh'}
    monkeypatch.setattr(lark,'auth_status',lambda:refreshable)
    ready,hint=real_sources._lark_ready()
    assert ready and '续期' in hint
    assert not lark.user_ready(refreshable)
    for token in ('expired','invalid','revoked','missing'):
        monkeypatch.setattr(lark,'auth_status',lambda token=token:{'ok':True,'user_status':'needs_refresh','token_status':token})
        assert not real_sources._lark_ready()[0]
