"""Synthetic boundary regressions; real connection proof is recorded separately."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import subprocess

import pytest

from server import feishu_account as account, lark, recent_sources

NOW = datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc)
SINCE = NOW - timedelta(days=7)
KEY = "a" * 64
URL = "https://team.feishu.cn/docx/Recent1"
READY = {"ok": True, "user_status": "ready", "token_status": "valid", "account_key": KEY,
         "scopes": list(lark.ACCOUNT_READ_SCOPES)}


def state():
    return {"enabled": True, "version": 1, "account_key": KEY}


def row(url=URL, matched=None):
    stamp = (matched or NOW - timedelta(days=1)).isoformat()
    return {"title": "合成边界资料", "url": url, "type": "DOCX", "matched_at": stamp,
            "updated_at": stamp, "opened_at": stamp, "matched_by": ["edited"]}


@pytest.fixture(autouse=True)
def fake_cli(monkeypatch):
    monkeypatch.setattr(lark, "auth_status", lambda: deepcopy(READY))
    monkeypatch.setattr(lark, "search_recent_docs", lambda *args, **kwargs: {"ok": True, "items": [row()]})
    monkeypatch.setattr(lark, "read_doc", lambda url, **kwargs: {"ok": True, "title": "合成边界资料", "text": "合成测试正文"})


def test_recent_unconnected_never_reads_account(monkeypatch):
    monkeypatch.setattr(lark, "auth_status", lambda: pytest.fail("no grant check while disconnected"))
    result = recent_sources.read_feishu(get_current=lambda: {"enabled": False}, now=NOW)
    assert not result["ok"] and result["error_code"] == "connection_changed"
    assert "text" not in result


def test_recent_unions_real_search_whitelist_and_guards_arbitrary_url():
    access = account.RecentAccess(state)
    result = access.recent(SINCE, NOW)
    assert len(result["items"]) == 1
    assert result["items"][0]["matched_by"] == ["edited", "opened"]
    assert access.read("https://team.feishu.cn/docx/NotReturned")["error_code"] == "document_not_in_search"
    assert access.read(URL)["ok"]
    assert access.recent(SINCE, NOW)["error_code"] == "search_budget_exhausted"


def test_recent_excludes_stale_undated_or_external_metadata(monkeypatch):
    monkeypatch.setattr(lark, "search_recent_docs", lambda *args, **kwargs: {"ok": True, "items": [
        row(matched=SINCE-timedelta(seconds=1)), {**row(), "matched_at": ""}, row("https://example.org/docx/X") ]})
    result = recent_sources.read_feishu(get_current=state, now=NOW)
    assert result["ok"] and result["empty"] and result["text"] == "" and result["citations"] == []


def test_recent_account_switch_after_query_cannot_return_metadata(monkeypatch):
    current = state()
    def query(*args, **kwargs):
        current["version"] += 1
        return {"ok": True, "items": [row()]}
    monkeypatch.setattr(lark, "search_recent_docs", query)
    result = recent_sources.read_feishu(get_current=lambda: dict(current), now=NOW)
    assert not result["ok"] and "合成边界资料" not in repr(result)


def test_recent_revoke_after_fetch_discards_bodies(monkeypatch):
    current = state()
    def fetch(*args, **kwargs):
        current["enabled"] = False
        return {"ok": True, "text": "PRIVATE_TEST_BODY"}
    monkeypatch.setattr(lark, "read_doc", fetch)
    result = recent_sources.read_feishu(get_current=lambda: dict(current), now=NOW)
    assert not result["ok"] and "PRIVATE_TEST_BODY" not in repr(result)
    assert not result["_access"].is_current()


def test_recent_reads_at_most_three_document_bodies_and_bounded_context(monkeypatch):
    monkeypatch.setattr(lark, "search_recent_docs", lambda *args, **kwargs: {"ok": True, "has_more": True,
        "items": [row(f"https://team.feishu.cn/docx/Recent{i}") for i in range(8)]})
    calls = []
    monkeypatch.setattr(lark, "read_doc", lambda url, **kwargs: calls.append(kwargs) or {"ok": True, "text": "文" * 9000})
    result = recent_sources.read_feishu(get_current=state, now=NOW)
    assert result["ok"] and len(calls) == 3 and all(c == {"identity": "user"} for c in calls)
    assert sum(len(item["text"]) for item in result["items"]) == 12000
    assert result["has_more"] and result["limited"] and result["read_count"] == 3
    assert result["scope"]["kind"] == "last_7_days"
    assert result["_access"].is_current()


def test_body_read_failure_is_not_an_empty_activity_result(monkeypatch):
    monkeypatch.setattr(lark, "read_doc", lambda *args, **kwargs: {"ok": False, "error": "PRIVATE"})
    result = recent_sources.read_feishu(get_current=state, now=NOW)
    assert not result["ok"] and result["error_code"] == "recent_read_failed"
    assert not result["empty"] and result["read_failures"] == 1 and result["read_count"] == 0
    assert result["text"] == "" and "PRIVATE" not in repr(result)


REAL_RECENT_SEARCH = lark.search_recent_docs


def test_official_recent_filter_uses_user_and_discards_missing_or_snapped_dates(monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        meta = {"url": URL, "doc_types": "DOCX", "update_time_iso": (NOW-timedelta(days=1)).isoformat(),
                "last_open_time_iso": NOW.isoformat()}
        rows = [{"title_highlighted": "<b>资料</b>", "result_meta": meta},
                {"title_highlighted": "旧资料", "result_meta": {**meta, "update_time_iso": (SINCE-timedelta(seconds=1)).isoformat()}},
                {"title_highlighted": "无时间", "result_meta": {**meta, "update_time_iso": ""}}]
        return subprocess.CompletedProcess(command, 0, json.dumps({"ok": True, "data": {"results": rows, "has_more": True}}), "")
    monkeypatch.setattr(lark.subprocess, "run", run)
    result = REAL_RECENT_SEARCH(SINCE, NOW, activity="edited", limit=100)
    assert result["ok"] and len(result["items"]) == 1 and result["items"][0]["title"] == "资料"
    assert result["excluded_count"] == 2 and result["has_more"]
    command = calls[0]
    assert command[1:6] == ["drive", "+search", "--as", "user", "--query"]
    assert command[6] == "" and command[command.index("--page-size")+1] == "8"
    assert "--edited-since" in command and "--edited-until" in command


@pytest.mark.parametrize("payload,code", [({"ok": True, "data": {}}, "recent_search_invalid"),
    ({"ok": False, "error": {"message": "PRIVATE_ERROR"}}, "recent_search_failed")])
def test_recent_cli_errors_cannot_be_reported_as_zero_or_echo_private_output(monkeypatch, payload, code):
    monkeypatch.setattr(lark.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, json.dumps(payload), "PRIVATE"))
    result = REAL_RECENT_SEARCH(SINCE, NOW)
    assert not result["ok"] and result["error_code"] == code and "PRIVATE" not in repr(result)


def test_recent_window_rejects_naive_and_over_seven_days_without_cli(monkeypatch):
    monkeypatch.setattr(lark.subprocess, "run", lambda *args, **kwargs: pytest.fail("invalid window must not read"))
    assert not REAL_RECENT_SEARCH(SINCE.replace(tzinfo=None), NOW)["ok"]
    assert not REAL_RECENT_SEARCH(SINCE-timedelta(seconds=1), NOW)["ok"]


def test_edited_filter_uses_complete_hours_inside_exact_seven_day_window(monkeypatch):
    calls = []
    monkeypatch.setattr(lark.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd) or
                        subprocess.CompletedProcess(cmd, 0, json.dumps({"ok": True, "data": {"results": []}}), ""))
    start, end = SINCE+timedelta(minutes=30), NOW+timedelta(minutes=30)
    assert REAL_RECENT_SEARCH(start, end)["ok"]
    cmd = calls[0]
    sent_start = datetime.fromisoformat(cmd[cmd.index("--edited-since")+1])
    sent_end = datetime.fromisoformat(cmd[cmd.index("--edited-until")+1])
    assert start <= sent_start < sent_end <= end
    assert sent_start.minute == sent_end.minute == 0
