"""Account retrieval contracts: isolated SQLite/fake CLI, no credentials or network."""
from copy import deepcopy
import json
import sqlite3
import subprocess

import pytest

from server import feishu_account as account, lark, lark_account_auth as auth, lark_auth, lark_auth_coordinator as coordinator

KEY = "a" * 64
OTHER_KEY = "b" * 64
READY = {"ok": True, "user_status": "ready", "token_status": "valid", "account_key": KEY,
         "scopes": list(lark.ACCOUNT_READ_SCOPES)}
URLS = [f"https://team.feishu.cn/docx/Doc{i}" for i in range(5)]


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(lark, "auth_status", lambda: deepcopy(READY))
    monkeypatch.setattr(lark, "search_docs", lambda query, limit=8: {"ok": True, "items": [
        {"title": f"文档 {i}", "url": url, "type": "DOCX"} for i, url in enumerate(URLS[:limit])]})
    monkeypatch.setattr(lark, "read_doc", lambda url, **kwargs: {"ok": True, "title": "真实正文标题", "text": "正文", "truncated": False})
    monkeypatch.setattr(auth, "STATE", {"status": "idle", "url": "", "qr": "", "error": "", "error_code": "", "attempt": 0})
    monkeypatch.setattr(coordinator, "_active", None)


def enabled_state():
    return {"enabled": True, "version": 1, "account_key": KEY, "connected_at": "test", "mode": "account_readonly"}


def test_connection_only_stores_state_and_transition_versions():
    conn = sqlite3.connect(":memory:")
    account.init_schema(conn)
    assert account.snapshot(conn, "one") == {"enabled": False, "version": 0, "account_key": "", "connected_at": "", "mode": "account_readonly"}
    with pytest.raises(ValueError):
        account.set_enabled(conn, "one", True)
    first = account.set_enabled(conn, "one", True, account_key=KEY)
    assert first["enabled"] and first["version"] == 1
    second = account.set_enabled(conn, "one", False)
    assert not second["enabled"] and second["version"] == 2
    assert account.set_enabled(conn, "one", True, account_key=KEY)["version"] == 3
    assert account.snapshot(conn, "other")["enabled"] is False
    assert [row[1] for row in conn.execute("PRAGMA table_info(feishu_account_connections)")] == [
        "session_id", "enabled", "version", "account_key", "connected_at"]
    conn.close()


def test_state_mutation_uses_callers_transaction():
    conn = sqlite3.connect(":memory:")
    account.init_schema(conn)
    conn.commit()
    account.set_enabled(conn, "one", True, account_key=KEY)
    conn.rollback()
    assert not account.snapshot(conn, "one")["enabled"]


def test_verify_requires_actual_search_not_only_ready_status(monkeypatch):
    calls = []
    monkeypatch.setattr(lark, "search_docs", lambda q, limit: calls.append((q, limit)) or {"ok": True, "items": []})
    result = account.verify_access()
    assert result["ok"] and result["ready"] and result["search_checked"] and result["account_key"] == KEY
    assert calls == [("念响", 1)]  # Empty success proves API accessibility, not a made-up document.


@pytest.mark.parametrize("scopes", [[], ["docx:document:readonly"], ["search:docs:readonly", "docx:document:readonly"]])
def test_missing_exact_scopes_does_not_search_or_start_login(monkeypatch, scopes):
    monkeypatch.setattr(lark, "auth_status", lambda: {**READY, "scopes": scopes})
    monkeypatch.setattr(lark, "search_docs", lambda *args, **kwargs: pytest.fail("no search with incomplete scope"))
    monkeypatch.setattr(lark_auth, "_run", lambda *args, **kwargs: pytest.fail("verification never starts login"))
    result = account.verify_access()
    assert not result["ok"] and result["permission_issue"] == "user_grant"


@pytest.mark.parametrize("issue,code", [("user_grant", "search_user_permission"), ("app_config", "search_app_permission"), (None, "search_failed")])
def test_search_permission_categories_do_not_echo_private_cli_output(monkeypatch, issue, code):
    monkeypatch.setattr(lark, "search_docs", lambda *args, **kwargs: {"ok": False, "error": "PRIVATE", "permission_issue": issue})
    result = account.verify_access()
    assert result["error_code"] == code and "PRIVATE" not in repr(result)


def test_switch_during_verify_cannot_enable_wrong_account(monkeypatch):
    responses = iter([READY, {**READY, "account_key": OTHER_KEY}])
    monkeypatch.setattr(lark, "auth_status", lambda: next(responses))
    assert account.verify_access()["error_code"] == "account_changed"


@pytest.mark.parametrize("url", ["http://team.feishu.cn/docx/Abc", "https://evil.invalid/docx/Abc",
    "https://feishu.cn.evil.invalid/docx/Abc", "https://u:p@team.feishu.cn/docx/Abc", "https://team.feishu.cn:444/docx/Abc",
    "https://team.feishu.cn/app/App1", "https://team.feishu.cn/docx/Abc/extra", "https://team.feishu.cn/docx/%2e%2e"])
def test_only_official_https_text_document_urls_are_valid(url):
    assert not account.canonical_document_url(url)


def test_read_requires_this_turn_search_and_user_identity(monkeypatch):
    seen = []
    monkeypatch.setattr(lark, "read_doc", lambda url, **kwargs: seen.append((url, kwargs)) or {"ok": True, "text": "原站正文", "title": "原站标题"})
    access = account.TurnAccess(enabled_state)
    assert access.read(URLS[0])["error_code"] == "document_not_in_search"
    access.search("项目")
    read = access.read(URLS[0] + "?from=browser#heading")
    assert read["ok"] and read["url"] == URLS[0] and read["text"] == "原站正文"
    assert seen == [(URLS[0], {"identity": "user"})]
    assert access.read(URLS[0])["error_code"] == "document_already_read"
    fresh_turn = account.TurnAccess(enabled_state)
    assert fresh_turn.read(URLS[0])["error_code"] == "document_not_in_search"


def test_invalid_search_results_cannot_authorize_external_fetch(monkeypatch):
    monkeypatch.setattr(lark, "search_docs", lambda *args, **kwargs: {"ok": True, "items": [
        {"url": "https://evil.invalid/docx/X", "title": "external"}, {"url": "https://team.feishu.cn/app/X", "title": "not a text document"}]})
    access = account.TurnAccess(enabled_state)
    result = access.search("test")
    assert result["items"] == [] and result["unsupported_count"] == 2
    assert "表格" in result["notice"]
    assert access.read("https://evil.invalid/docx/X")["error_code"] == "document_not_in_search"


def test_limits_bound_cli_reads_and_full_context_size(monkeypatch):
    calls = []
    monkeypatch.setattr(lark, "read_doc", lambda url, **kwargs: calls.append(url) or {"ok": True, "text": "文" * 7000, "title": "长文档"})
    access = account.TurnAccess(enabled_state)
    assert access.search("项目")["ok"]
    assert access.search("PRD")["ok"]
    assert access.search("第三次")["error_code"] == "search_budget_exhausted"
    results = [access.read(url) for url in URLS[:3]]
    assert all(r["ok"] and r["length"] == 4000 and r["truncated"] for r in results)
    assert access.context_chars == 12000
    assert access.read(URLS[3])["error_code"] == "read_budget_exhausted" and len(calls) == 3
    assert not any("文" * 10 in repr(value) for value in access.__dict__.values())  # No permanent/turn body cache.


@pytest.mark.parametrize("changed", [{"enabled": False}, {"version": 2}, {"account_key": OTHER_KEY}])
def test_disconnect_or_reconnect_during_fetch_discards_new_body(monkeypatch, changed):
    current = enabled_state()
    access = account.TurnAccess(lambda: dict(current))
    access.search("PRD")
    def fetch(url, **kwargs):
        current.update(changed)
        return {"ok": True, "title": "PRIVATE", "text": "PRIVATE DOCUMENT BODY"}
    monkeypatch.setattr(lark, "read_doc", fetch)
    result = access.read(URLS[0])
    assert not result["ok"] and result["error_code"] == "connection_changed"
    assert "PRIVATE" not in repr(result) and not access.is_current()


def test_cli_account_switch_without_ui_disconnect_is_detected(monkeypatch):
    access = account.TurnAccess(enabled_state)
    access.search("PRD")
    monkeypatch.setattr(lark, "auth_status", lambda: {**READY, "account_key": OTHER_KEY})
    monkeypatch.setattr(lark, "read_doc", lambda *args, **kwargs: pytest.fail("do not read another account"))
    assert access.read(URLS[0])["error_code"] == "account_changed"
    assert not access.is_current()


def test_cli_search_network_failure_does_not_change_connection(monkeypatch):
    access = account.TurnAccess(enabled_state)
    monkeypatch.setattr(lark, "search_docs", lambda *args, **kwargs: {"ok": False, "error": "timeout"})
    assert access.search("PRD")["error_code"] == "search_failed"
    assert access.is_current()


def test_keyword_scope_can_locate_later_evidence_and_keeps_true_search_title(monkeypatch):
    calls = []
    def fetch(url, **kwargs):
        calls.append(kwargs)
        return {"ok": True, "title": "飞书文档", "text": "位于长文后段的目标证据", "partial": True}
    monkeypatch.setattr(lark, "read_doc", fetch)
    access = account.TurnAccess(enabled_state)
    access.search("PRD")
    result = access.read(URLS[0], query="商业化|定价")
    assert result["text"] == "位于长文后段的目标证据" and result["title"] == "文档 0"
    assert result["partial"] and result["excerpt"] and result["read_scope"] == "keyword"
    assert calls == [{"identity": "user", "keyword": "商业化|定价"}]
    assert access.read(URLS[0], query="另一主题")["ok"]  # Different ranges still share the three-read budget.


def test_keyword_no_match_falls_back_to_related_passages_beyond_opening(monkeypatch):
    calls = []
    original = "开头背景。" * 1000 + "后段证据：我们需要在用户表达低落时认真陪伴，保留用户主导。" + "文档结尾。" * 100
    def fetch(url, **kwargs):
        calls.append(kwargs)
        return {"ok": False, "error_code": "keyword_no_match"} if "keyword" in kwargs else {"ok": True, "text": original}
    monkeypatch.setattr(lark, "read_doc", fetch)
    access = account.TurnAccess(enabled_state)
    access.search("项目")
    result = access.read(URLS[0], query="陪伴感")
    assert result["ok"] and "后段证据" in result["text"] and "认真陪伴" in result["text"]
    assert result["fallback_used"] and result["partial"] and result["excerpt"]
    assert result["read_scope"] == "full_fallback_relevant_excerpts" and not result["keyword_missed"]
    assert len(result["text"]) <= 780 and calls == [{"identity": "user", "keyword": "陪伴感"}, {"identity": "user"}]
    assert access.read_count == 1  # One logical read, at most one bounded fallback CLI call.


def test_whitespace_keywords_are_safe_or_and_original_query_is_preserved(monkeypatch):
    calls = []
    monkeypatch.setattr(lark, "read_doc", lambda url, **kwargs: calls.append(kwargs) or {"ok": True, "text": "用户体验相关段落"})
    access = account.TurnAccess(enabled_state)
    access.search("项目")
    result = access.read(URLS[0], query="情感   陪伴|用户 陪伴 C++ .* (a)")
    assert result["query"] == "情感   陪伴|用户 陪伴 C++ .* (a)"
    expected = r"情感|陪伴|用户|C\+\+|\.\*|\(a\)"
    assert result["effective_keyword"] == expected and calls[0]["keyword"] == expected
    assert access.read(URLS[0], query="情感|陪伴|用户 C++ .* (a)")["error_code"] == "document_already_read"


def test_unmatched_fallback_returns_honest_bounded_opening(monkeypatch):
    def fetch(url, **kwargs):
        return {"ok": False, "error_code": "keyword_no_match"} if "keyword" in kwargs else {"ok": True, "text": "天气晴朗。" * 2000}
    monkeypatch.setattr(lark, "read_doc", fetch)
    access = account.TurnAccess(enabled_state)
    access.search("文档")
    result = access.read(URLS[0], query="支付协议")
    assert result["ok"] and result["fallback_used"] and result["keyword_missed"]
    assert result["read_scope"] == "full_fallback_opening" and "不代表与问题相关" in result["notice"]
    assert result["length"] == 4000 and result["truncated"] and result["partial"]


@pytest.mark.parametrize("failure", [{"ok": False, "subtype": "need_user_authorization"},
    {"ok": False, "error": "network timeout"}, {"ok": False, "error_code": "arbitrary_failure"}])
def test_permissions_and_transport_failures_never_trigger_fallback(monkeypatch, failure):
    calls = []
    monkeypatch.setattr(lark, "read_doc", lambda url, **kwargs: calls.append(kwargs) or failure)
    access = account.TurnAccess(enabled_state)
    access.search("项目")
    assert not access.read(URLS[0], query="用户")["ok"]
    assert len(calls) == 1 and calls[0]["keyword"] == "用户"


def test_disconnect_during_fallback_discards_full_document(monkeypatch):
    current = enabled_state()
    access = account.TurnAccess(lambda: dict(current))
    access.search("项目")
    calls = []
    def fetch(url, **kwargs):
        calls.append(kwargs)
        if "keyword" in kwargs:
            return {"ok": False, "error_code": "keyword_no_match"}
        current["version"] += 1
        return {"ok": True, "text": "PRIVATE DOCUMENT BODY"}
    monkeypatch.setattr(lark, "read_doc", fetch)
    result = access.read(URLS[0], query="用户")
    assert result["error_code"] == "connection_changed" and "PRIVATE" not in repr(result)
    assert len(calls) == 2


def test_automatic_fallback_still_bounds_logical_reads_cli_calls_and_output(monkeypatch):
    calls = []
    def fetch(url, **kwargs):
        calls.append(kwargs)
        return {"ok": False, "error_code": "keyword_no_match"} if "keyword" in kwargs else {"ok": True, "text": "天气晴朗。" * 2000}
    monkeypatch.setattr(lark, "read_doc", fetch)
    access = account.TurnAccess(enabled_state)
    access.search("项目")
    results = [access.read(url, query="无关主题") for url in URLS[:3]]
    assert all(result["ok"] and result["keyword_missed"] for result in results)
    assert access.read_count == 3 and len(calls) == 6 and access.context_chars == 12000
    assert not access.read(URLS[3], query="另一主题")["ok"] and len(calls) == 6


def test_expired_token_cannot_return_content(monkeypatch):
    access = account.TurnAccess(enabled_state)
    monkeypatch.setattr(lark, "auth_status", lambda: {**READY, "token_status": "revoked"})
    assert not access.is_current() and access.search("test")["error_code"] == "authorization_not_ready"


def test_refreshable_cli_grant_can_renew_on_read_without_new_login(monkeypatch):
    monkeypatch.setattr(lark, "auth_status", lambda: {**READY, "user_status": "needs_refresh", "token_status": "needs_refresh"})
    monkeypatch.setattr(lark_auth, "_run", lambda *args, **kwargs: pytest.fail("no new login for automatic CLI renewal"))
    assert account.verify_access()["ok"]
    access = account.TurnAccess(enabled_state)
    assert access.search("test")["ok"] and access.read(URLS[0])["ok"]
    for token in ("expired", "invalid", "missing", "revoked"):
        monkeypatch.setattr(lark, "auth_status", lambda token=token: {**READY, "user_status": "needs_refresh", "token_status": token})
        assert not account.verify_access()["ok"]


def test_public_grant_readiness_is_local_and_accepts_cli_renewal(monkeypatch):
    monkeypatch.setattr(lark, "search_docs", lambda *args, **kwargs: pytest.fail("local helper cannot search"))
    assert account.grant_readiness(READY) is None
    assert account.grant_readiness({**READY, "user_status": "needs_refresh", "token_status": "needs_refresh"}) is None
    problem = account.grant_readiness({**READY, "token_status": "revoked"})
    assert problem["error_code"] == "authorization_not_ready"


def test_has_context_marks_document_metadata_but_not_failures_or_empty_search(monkeypatch):
    access = account.TurnAccess(enabled_state)
    assert access.has_context is False
    assert access.read(URLS[0])["ok"] is False and not access.has_context
    monkeypatch.setattr(lark, "search_docs", lambda *args, **kwargs: {"ok": True, "items": []})
    assert access.search("空结果")["ok"] and not access.has_context
    monkeypatch.setattr(lark, "search_docs", lambda *args, **kwargs: {"ok": True, "items": [{"url": URLS[0], "title": "真实标题"}]})
    assert access.search("有结果")["items"] and access.has_context
    assert access.read(URLS[0])["ok"] and access.has_context
    with pytest.raises(AttributeError):
        access.has_context = False


def test_unavailable_account_exposes_no_context(monkeypatch):
    access = account.TurnAccess(enabled_state)
    monkeypatch.setattr(lark, "auth_status", lambda: {"ok": False})
    assert not access.search("项目")["ok"] and not access.has_context


REAL_STATUS = lark.auth_status
REAL_READ_DOC = lark.read_doc


def test_read_adapter_uses_official_keyword_flags_and_reports_excerpt(monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess([], 0, json.dumps({"ok": True, "data": {"document": {
            "content": '<fragment mode="keyword"><p>真实匹配段落</p></fragment>'}}}), "")
    monkeypatch.setattr(lark.subprocess, "run", run)
    monkeypatch.setattr(lark.faults, "active", lambda *args: False)
    result = REAL_READ_DOC(URLS[0], identity="user", keyword="主题|别名")
    assert result["ok"] and result["text"] == "真实匹配段落" and result["partial"]
    assert calls[0][-8:] == ["--scope", "keyword", "--keyword", "主题|别名", "--context-before", "1", "--context-after", "2"]
    assert result["read_scope"] == "keyword"


def test_auth_status_exports_hash_and_known_scopes_not_identifiers(monkeypatch):
    payload = {"ok": True, "appId": "SYNTHETIC_APP", "identities": {"user": {
        "status": "ready", "tokenStatus": "valid", "openId": "SYNTHETIC_OPENID",
        "scope": "docx:document:readonly search:docs:read unrelated:private:scope", "accessToken": "SECRET"}}}
    monkeypatch.setattr(lark.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 0, json.dumps(payload), ""))
    result = REAL_STATUS()
    assert len(result["account_key"]) == 64 and result["scopes"] == list(lark.ACCOUNT_READ_SCOPES)
    assert all(secret not in repr(result) for secret in ("SYNTHETIC_APP", "SYNTHETIC_OPENID", "SECRET", "unrelated:private:scope"))
    first = result["account_key"]
    payload["appId"] = "OTHER_APP"
    assert REAL_STATUS()["account_key"] != first


def test_combined_oauth_is_explicit_and_never_accepts_old_ready_status(monkeypatch):
    calls, workers = [], []
    monkeypatch.setattr(lark_auth, "_run", lambda args, timeout: calls.append(args) or subprocess.CompletedProcess([], 0, json.dumps({"verification_url": "https://accounts.feishu.cn/oauth/v1/device/verify/?user_code=SYNTHETIC", "device_code": "PRIVATE_CODE"}), ""))
    monkeypatch.setattr(lark_auth, "_qr_data_url", lambda url: "")
    class Thread:
        def __init__(self, **kwargs): workers.append(kwargs)
        def start(self): pass
    monkeypatch.setattr(auth.threading, "Thread", Thread)
    assert auth.status()["status"] == "idle" and not calls
    result = auth.start()
    assert result["status"] == "pending" and "PRIVATE_CODE" not in repr(result)
    assert calls == [["auth", "login", "--no-wait", "--json", "--scope", "docx:document:readonly search:docs:read"]]
    assert auth.start()["status"] == "pending" and len(calls) == 1
    assert coordinator.begin("document")[0] == "conflict"


def test_oauth_receipt_requires_live_search_check_and_ignores_stale_worker(monkeypatch):
    _, token = coordinator.begin("account")
    auth.STATE.update(status="pending", attempt=2, url="OLD_URL")
    monkeypatch.setattr(lark_auth, "_run", lambda *args, **kwargs: subprocess.CompletedProcess([], 0, '{"ok":true}', ""))
    monkeypatch.setattr(account, "verify_access", lambda: {"ok": False, "error": "应用未开通搜索", "error_code": "search_app_permission", "permission_issue": "app_config"})
    auth._complete("synthetic", 1, object())
    assert auth.status()["status"] == "pending" and coordinator.begin("search")[0] == "conflict"
    auth._complete("synthetic", 2, token)
    result = auth.status()
    assert result["status"] == "error" and result["permission_issue"] == "app_config" and not result["url"]
    _, token = coordinator.begin("account")
    auth.STATE.update(status="pending", attempt=3)
    monkeypatch.setattr(account, "verify_access", lambda: {"ok": True, "ready": True})
    auth._complete("synthetic", 3, token)
    assert auth.status()["status"] == "success"
