"""Isolated source/job boundary tests; no account, model, or network credentials."""
import json
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace

import pytest
import server

from server import connection_intro as intro, core, feishu_account, model


@pytest.fixture()
def environment(tmp_path, monkeypatch):
    database = str(tmp_path / "intro.db")
    monkeypatch.setattr(core, "DB_PATH", database)
    monkeypatch.setattr(model, "from_env", lambda: None)
    core.init_db()
    intro.recover(database)
    sid = core.conversation_id()
    yield database, sid
    intro.shutdown(database)
    with intro._lock:
        threads = [thread for (path, _), thread in intro._threads.items() if path == database]
    for thread in threads:
        thread.join(3)


def attach(sid, text="本次真实来源边界测试正文", *, provider="local_files", title="当前资料.txt"):
    before = {row["id"] for row in core.list_sources(sid)}
    core.attach_sources_to_session(sid, [{"connector_id": provider, "label": title, "text": text,
        "understanding": {"facts": [], "inferences": [], "questions": []},
        "items": [{"title": title, "summary": text}], "insights": [], "starters": []}])
    return next(row["id"] for row in core.list_sources(sid) if row["id"] not in before)


def wait(job, sid):
    until = time.monotonic() + 4
    while time.monotonic() < until:
        result = intro.get(job["id"], sid)
        if result is None or result["status"] != "running":
            return result
        time.sleep(.01)
    pytest.fail("bounded worker did not finish")


def client(monkeypatch, callback=None):
    calls = []
    def complete(system, user, max_tokens=600):
        calls.append((system, json.loads(user), max_tokens))
        return callback() if callback else "我看到你在打磨最近的产品计划。这里最想先推进的是哪一件？"
    monkeypatch.setattr(model, "from_env", lambda: SimpleNamespace(model="synthetic-test-model", complete=complete))
    return calls


def account(sid):
    conn = core.get_db()
    feishu_account.set_enabled(conn, sid, True, account_key="a" * 64)
    conn.commit()
    conn.close()


def recent(monkeypatch, *, empty=False, ok=True, access=None):
    reads = []
    def read_feishu(*, get_current):
        reads.append(get_current())
        return {"ok": ok, "empty": empty, "scope": {"kind": "last_7_days", "label": "最近7天编辑或打开的飞书文档"},
                "text": "SYNTHETIC_RECENT_BODY" if not empty else "", "items": [] if empty else [{"title": "本周计划"}],
                "citations": [] if empty else [{"kind": "feishu_document", "title": "本周计划", "url": "https://team.feishu.cn/docx/Doc1"}],
                "_access": access or SimpleNamespace(is_current=lambda: True)}
    fake = SimpleNamespace(read_feishu=read_feishu)
    monkeypatch.setitem(sys.modules, "server.recent_sources", fake)
    monkeypatch.setattr(server, "recent_sources", fake, raising=False)
    return reads


def test_selected_batch_is_assistant_only_and_idempotent(environment, monkeypatch):
    _, sid = environment
    old = attach(sid, "OLDER_BODY_MUST_NOT_LEAK", title="旧资料")
    selected = attach(sid, "SELECTED_BODY", title="选中的新资料")
    calls = client(monkeypatch)
    job = intro.start(sid, "local_files", [selected])
    final = wait(job, sid)
    duplicate = intro.start(sid, "local_files", [selected])
    assert final["status"] == "completed" and final["message_id"]
    assert duplicate["id"] == job["id"] and len(calls) == 1
    assert "SELECTED_BODY" in calls[0][1]["source_text"]
    assert "OLDER_BODY_MUST_NOT_LEAK" not in json.dumps(calls)
    messages = core.get_messages(sid)
    assert all(row["role"] == "assistant" for row in messages)
    assert len(messages) == 2
    assert messages[-1]["citations"][0]["source_id"] == selected
    conn = core.get_db()
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    stored = dict(conn.execute("SELECT * FROM connection_intro_jobs").fetchone())
    assert "SELECTED_BODY" not in json.dumps(stored)
    assert old not in stored["selection"]
    conn.close()


def test_concurrent_duplicate_requests_run_only_one_model(environment, monkeypatch):
    _, sid = environment
    attachment = attach(sid)
    release, entered = threading.Event(), threading.Event()
    def block():
        entered.set()
        assert release.wait(3)
        return "基于所选资料的洞察，你最想先聊什么？"
    calls = client(monkeypatch, block)
    results = []
    threads = [threading.Thread(target=lambda: results.append(intro.start(sid, "local_files", attachment))) for _ in range(5)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)
        assert entered.wait(2)
        assert len({row["id"] for row in results}) == 1
    finally:
        release.set()
    assert wait(results[0], sid)["status"] == "completed"
    assert len(calls) == 1


def test_unconfirmed_foreign_or_arbitrary_receipts_never_start(environment):
    _, sid = environment
    with pytest.raises(ValueError):
        intro.start(sid, "local_files")
    attach(sid)
    for receipt in ("invented-id", ["foreign-id"], [], {"key": "force-another"}):
        with pytest.raises(ValueError):
            intro.start(sid, "local_files", receipt)
    with pytest.raises(LookupError):
        intro.start("no-such-conversation", "local_files")
    conn = core.get_db()
    assert conn.execute("SELECT COUNT(*) FROM connection_intro_jobs").fetchone()[0] == 0
    conn.close()


@pytest.mark.parametrize("change", ["new_user", "revoke", "source_stale", "delete"])
def test_pending_generation_does_not_reply_after_context_change(environment, monkeypatch, change):
    _, sid = environment
    attachment = attach(sid)
    release, entered = threading.Event(), threading.Event()
    def block():
        entered.set()
        assert release.wait(3)
        return "STALE_BODY_MUST_NOT_BE_COMMITTED"
    client(monkeypatch, block)
    job = intro.start(sid, "local_files", attachment)
    try:
        assert entered.wait(2)
        if change == "new_user":
            core.add_message(sid, "user", "先听我说")
            assert intro.get(job["id"], sid)["status"] == "superseded"
        elif change == "revoke":
            core.revoke_source(sid, attachment)
            assert intro.get(job["id"], sid)["status"] == "superseded"
        elif change == "source_stale":
            conn = core.get_db()
            conn.execute("UPDATE source_attachments SET stale=1 WHERE id=?", (attachment,))
            conn.commit()
            conn.close()
        else:
            core.delete_session(sid)
    finally:
        release.set()
    result = wait(job, sid)
    assert result is None if change == "delete" else result["status"] == "superseded"
    assert "STALE_BODY_MUST_NOT_BE_COMMITTED" not in json.dumps(core.get_messages(sid))


def test_shutdown_and_recovery_never_commit_old_worker(environment, monkeypatch):
    database, sid = environment
    attachment = attach(sid)
    release, entered = threading.Event(), threading.Event()
    def block():
        entered.set()
        assert release.wait(3)
        return "OLD_PROCESS_OUTPUT"
    client(monkeypatch, block)
    job = intro.start(sid, "local_files", attachment)
    try:
        assert entered.wait(2)
        intro.shutdown(database)
        assert intro.get(job["id"], sid)["status"] == "interrupted"
        with pytest.raises(RuntimeError):
            intro.start(sid, "local_files", attachment)
        intro.recover(database)
    finally:
        release.set()
    with intro._lock:
        thread = intro._threads.get((database, job["id"]))
    if thread:
        thread.join(2)
    assert intro.get(job["id"], sid)["status"] == "interrupted"
    assert intro.start(sid, "local_files", attachment)["id"] == job["id"]
    assert "OLD_PROCESS_OUTPUT" not in json.dumps(core.get_messages(sid))


def test_restart_marks_persisted_running_as_interrupted(environment):
    database, sid = environment
    conn = core.get_db()
    stamp = core.now()
    conn.execute("INSERT INTO connection_intro_jobs(id,session_id,source_id,dedupe_key,selection,last_user_rowid,status,created_at,updated_at) "
                 "VALUES('abandoned',?,'feishu','key','{}',0,'running',?,?)", (sid, stamp, stamp))
    conn.commit()
    conn.close()
    intro.recover(database)
    assert intro.get("abandoned", sid)["status"] == "interrupted"
    assert intro.get("abandoned", "foreign-session") is None


def test_account_recent_read_uses_time_scope_and_actual_citations(environment, monkeypatch):
    _, sid = environment
    account(sid)
    reads = recent(monkeypatch)
    calls = client(monkeypatch)
    final = wait(intro.start(sid, "feishu"), sid)
    assert final["status"] == "completed"
    assert len(reads) == len(calls) == 1
    assert final["scope"]["kind"] == "last_7_days"
    assert calls[0][1]["source_text"] == "SYNTHETIC_RECENT_BODY"
    assert core.get_messages(sid)[-1]["citations"][0]["kind"] == "feishu_document"
    conn = core.get_db()
    assert conn.execute("SELECT COUNT(*) FROM source_attachments").fetchone()[0] == 0
    assert "SYNTHETIC_RECENT_BODY" not in json.dumps([dict(row) for row in conn.execute("SELECT * FROM connection_intro_jobs")])
    conn.close()


def test_empty_recent_result_is_honest_and_never_calls_model(environment, monkeypatch):
    _, sid = environment
    account(sid)
    recent(monkeypatch, empty=True)
    monkeypatch.setattr(model, "from_env", lambda: pytest.fail("empty result needs no model"))
    final = wait(intro.start(sid, "feishu"), sid)
    conn = core.get_db()
    row = conn.execute("SELECT id,text FROM messages WHERE id=?", (final["message_id"],)).fetchone()
    visible = intro.chat_delivery.annotate(conn, sid, [dict(row)], at=time.time() + 60)[0]
    conn.close()
    assert final["status"] == "completed"
    first = core.get_messages(sid)[-1]["text"]
    assert "没有找到" in first and "最近7天" in first
    assert not visible["delivery_pending"]
    assert "没有找到" in visible["text"] and "最近7天" in visible["text"]
    assert "愿意" in visible["text"]
    assert "你的日程很满" not in visible["text"]


def test_account_disconnect_after_read_prevents_model_send(environment, monkeypatch):
    _, sid = environment
    account(sid)
    recent(monkeypatch, access=SimpleNamespace(is_current=lambda: False))
    calls = client(monkeypatch)
    final = wait(intro.start(sid, "feishu"), sid)
    assert final["status"] == "superseded" and not calls
    assert len(core.get_messages(sid)) == 1


def test_atomic_commit_rechecks_account_version_after_external_guard(environment, monkeypatch):
    _, sid = environment
    account(sid)
    counter = 0
    def guard():
        nonlocal counter
        counter += 1
        if counter == 2:
            conn = core.get_db()
            feishu_account.set_enabled(conn, sid, False)
            conn.commit()
            conn.close()
        return True
    recent(monkeypatch, access=SimpleNamespace(is_current=guard))
    calls = client(monkeypatch)
    final = wait(intro.start(sid, "feishu"), sid)
    assert len(calls) == 1 and final["status"] == "superseded"
    assert len(core.get_messages(sid)) == 1


@pytest.mark.parametrize("failure", ["unconfigured", "model_error", "read_error"])
def test_errors_are_real_service_notices_without_private_exception(environment, monkeypatch, failure):
    _, sid = environment
    if failure == "read_error":
        account(sid)
        recent(monkeypatch, ok=False)
        provider, receipt = "feishu", None
        calls = client(monkeypatch)
    else:
        provider, receipt = "local_files", attach(sid)
        calls = []
        if failure == "model_error":
            def fail():
                raise model.ModelError("PRIVATE_TOKEN_AND_BODY")
            calls = client(monkeypatch, fail)
    final = wait(intro.start(sid, provider, receipt), sid)
    assert final["status"] == "failed" and final["message_id"]
    assert "PRIVATE_TOKEN_AND_BODY" not in json.dumps(core.get_messages(sid)) + json.dumps(final)
    assert len(calls) == (1 if failure == "model_error" else 0)
    assert len(core.get_messages(sid)) == 2


def test_snapshot_feishu_does_not_expand_into_account_scope(environment, monkeypatch):
    _, sid = environment
    attachment = attach(sid, provider="feishu")
    recent(monkeypatch)
    calls = client(monkeypatch)
    final = wait(intro.start(sid, "feishu", attachment), sid)
    assert final["status"] == "completed"
    assert final["scope"]["kind"] == "selected_material"
    assert "SYNTHETIC_RECENT_BODY" not in json.dumps(calls)


def test_explicit_document_receipt_stays_selected_even_when_account_is_enabled(environment, monkeypatch):
    _, sid = environment
    account(sid)
    attachment = attach(sid, "ONLY_EXPLICIT_DOCUMENT_BODY", provider="feishu")
    reads = recent(monkeypatch)
    calls = client(monkeypatch)
    final = wait(intro.start(sid, "feishu", attachment), sid)
    assert final["status"] == "completed" and final["scope"]["kind"] == "selected_material"
    assert not reads
    assert "ONLY_EXPLICIT_DOCUMENT_BODY" in calls[0][1]["source_text"]
    assert "SYNTHETIC_RECENT_BODY" not in json.dumps(calls)


def test_calendar_without_time_evidence_never_claims_past_week(environment, monkeypatch):
    _, sid = environment
    attachment = attach(sid, "未来日历项", provider="apple_calendar")
    calls = client(monkeypatch)
    final = wait(intro.start(sid, "apple_calendar", attachment), sid)
    assert final["scope"]["kind"] == "selected_calendar_snapshot"
    assert calls[0][1]["scope"]["kind"] != "last_7_days"


def test_empty_calendar_preserves_verified_scope_and_never_calls_model(environment, monkeypatch):
    _, sid = environment
    scope = {"kind": "last_7_days", "label": "过去7天开始的日程", "since": "2026-10-24T00:00:00+08:00",
             "until": "2026-10-31T00:00:00+08:00"}
    core.attach_source_to_empty_session(sid, "Apple日历", "本次读取0条。", {"facts": [], "inferences": [], "questions": []},
                                       [], [], [], connector_id="apple_calendar", read_scope=scope)
    monkeypatch.setattr(model, "from_env", lambda: pytest.fail("no invented insight for zero data"))
    final = wait(intro.start(sid, "apple_calendar"), sid)
    assert final["status"] == "completed" and final["scope"] == scope
    conn = core.get_db()
    row = conn.execute("SELECT id,text FROM messages WHERE id=?", (final["message_id"],)).fetchone()
    visible = intro.chat_delivery.annotate(conn, sid, [dict(row)], at=time.time() + 60)[0]
    conn.close()
    first = core.get_messages(sid)[-1]["text"]
    assert "过去7天" in first and "没有找到" in first
    assert not visible["delivery_pending"]
    assert "过去7天" in visible["text"] and "愿意" in visible["text"]


def test_presentation_state_change_does_not_cancel_source_intro(environment, monkeypatch):
    _, sid = environment
    attachment = attach(sid)
    def complete():
        core.set_session_state(sid, "responding")
        return "所选资料讲到你在推进的计划。你最想先谈哪一部分？"
    calls = client(monkeypatch, complete)
    final = wait(intro.start(sid, "local_files", attachment), sid)
    assert final["status"] == "completed" and len(calls) == 1


def test_read_failures_are_not_treated_as_zero_recent_documents(environment, monkeypatch):
    _, sid = environment
    account(sid)
    def read_feishu(*, get_current):
        return {"ok": True, "empty": False, "read_count": 0, "read_failures": 2, "matched_count": 2,
                "scope": {"kind": "last_7_days"}, "items": [{"title": "只找到元数据"}], "text": "",
                "_access": SimpleNamespace(is_current=lambda: True)}
    monkeypatch.setattr(server, "recent_sources", SimpleNamespace(read_feishu=read_feishu), raising=False)
    monkeypatch.setattr(model, "from_env", lambda: pytest.fail("unread body cannot support insight"))
    final = wait(intro.start(sid, "feishu"), sid)
    assert final["status"] == "failed"
    text = core.get_messages(sid)[-1]["text"]
    assert "没能读到正文" in text and "没有找到" not in text


def test_same_account_connect_retry_reuses_intro_and_disconnect_cancels_in_transaction(environment, monkeypatch):
    _, sid = environment
    account(sid)
    release, entered = threading.Event(), threading.Event()
    def block():
        entered.set()
        assert release.wait(3)
        return "不能在撤回后提交的正文洞察"
    recent(monkeypatch)
    calls = client(monkeypatch, block)
    job = intro.start(sid, "feishu")
    try:
        assert entered.wait(2)
        conn = core.get_db()
        before = feishu_account.snapshot(conn, sid)
        same = feishu_account.set_enabled(conn, sid, True, account_key="a" * 64)
        conn.commit()
        assert same == before
        assert intro.start(sid, "feishu")["id"] == job["id"]
        conn.execute("BEGIN IMMEDIATE")
        feishu_account.set_enabled(conn, sid, False)
        assert conn.execute("SELECT status FROM connection_intro_jobs WHERE id=?", (job["id"],)).fetchone()[0] == "superseded"
        conn.rollback()
        assert intro.get(job["id"], sid)["status"] == "running"  # cancellation shares the transaction.
        feishu_account.set_enabled(conn, sid, False)
        conn.commit()
        conn.close()
        assert intro.get(job["id"], sid)["status"] == "superseded"
    finally:
        release.set()
    wait(job, sid)
    assert len(calls) == 1 and len(core.get_messages(sid)) == 1


def test_partial_reads_never_send_failed_titles_as_content():
    _, prompt = intro._prompt("飞书", {"text": "SUCCESS_BODY", "read_count": 1, "read_failures": 1,
        "matched_count": 2, "items": [{"title": "success", "read_ok": True}, {"title": "FAILED_PRIVATE_TITLE", "read_ok": False}]})
    data = json.loads(prompt)
    assert "FAILED_PRIVATE_TITLE" not in prompt
    assert data["read_count"] == data["read_failures"] == 1 and data["matched_count"] == 2


def test_attachment_receipts_are_returned_from_the_same_commit(environment):
    _, sid = environment
    first = core.attach_source_to_empty_session(sid, "本批甲", "甲正文", {"facts": [], "inferences": [], "questions": []},
                                               [{"title": "甲"}], [], [], connector_id="local_files")
    second = core.attach_source_to_empty_session(sid, "本批乙", "乙正文", {"facts": [], "inferences": [], "questions": []},
                                                [{"title": "乙"}], [], [], connector_id="local_files")
    assert len(first) == len(second) == 1 and not set(first).intersection(second)
    conn = core.get_db()
    assert conn.execute("SELECT source_text FROM source_attachments WHERE id=?", (first[0],)).fetchone()[0] == "甲正文"
    assert conn.execute("SELECT source_text FROM source_attachments WHERE id=?", (second[0],)).fetchone()[0] == "乙正文"
    conn.close()


def test_connection_intro_uses_session_persona_and_work_mode(environment, monkeypatch):
    _, sid = environment
    core.set_session_persona(sid, 'whale')
    core.set_session_mode(sid, 'work')
    attachment = attach(sid)
    calls = client(monkeypatch)
    final = wait(intro.start(sid, 'local_files', attachment), sid)
    assert final['status'] == 'completed'
    assert '【产品人格：whale】' in calls[0][0]
    assert '【工作模式】' in calls[0][0]
    conn = core.get_db()
    row = conn.execute('SELECT persona_id,interaction_mode FROM messages WHERE id=?', (final['message_id'],)).fetchone()
    assert tuple(row) == ('whale', 'work')
    assert conn.execute('SELECT 1 FROM chat_delivery WHERE message_id=?', (final['message_id'],)).fetchone()
    conn.close()


@pytest.mark.parametrize("setter,other,original", [
    (core.set_session_persona, 'whale', 'nianxiang'),
    (core.set_session_mode, 'work', 'companion'),
])
def test_space_switch_during_generation_supersedes_even_if_switched_back(environment, monkeypatch, setter, other, original):
    _, sid = environment
    attachment = attach(sid)
    entered, release = threading.Event(), threading.Event()
    def block():
        entered.set()
        assert release.wait(3)
        return '不应提交的旧人格洞察'
    client(monkeypatch, block)
    job = intro.start(sid, 'local_files', attachment)
    try:
        assert entered.wait(2)
        setter(sid, other)
        setter(sid, original)
    finally:
        release.set()
    assert wait(job, sid)['status'] == 'superseded'
    assert '不应提交的旧人格洞察' not in json.dumps(core.get_messages(sid), ensure_ascii=False)
    # A retry after changing persona is a new job, not the superseded one.
    next_job = intro.start(sid, 'local_files', attachment)
    assert next_job['id'] != job['id']
    assert wait(next_job, sid)['status'] == 'completed'


def test_legacy_local_conversation_migrates_to_existing_default_persona(tmp_path, monkeypatch):
    database = str(tmp_path / "legacy-local.db")
    conn = sqlite3.connect(database)
    conn.executescript("""
        CREATE TABLE sessions(id TEXT PRIMARY KEY, created_at TEXT, mode TEXT, source_text TEXT,
            source_label TEXT, state TEXT);
        CREATE TABLE messages(id TEXT PRIMARY KEY, session_id TEXT, role TEXT, text TEXT,
            citations TEXT DEFAULT '[]', suggestions TEXT DEFAULT '[]', created_at TEXT);
        INSERT INTO sessions VALUES('old', 'now', 'empty', '', '旧对话', 'listening');
        INSERT INTO messages VALUES('reply', 'old', 'assistant', '旧回复', '[]', '[]', 'now');
    """)
    conn.close()
    monkeypatch.setattr(core, "DB_PATH", database)
    core.init_db()
    session = core.get_session('old')
    message = core.get_messages('old')[0]
    assert (session['persona_id'], session['interaction_mode']) == ('nianxiang', 'companion')
    assert (message['persona_id'], message['interaction_mode']) == ('nianxiang', 'companion')
    assert message['text'] == '旧回复'


def test_user_message_records_current_persona_and_mode(environment):
    _, sid = environment
    core.set_session_persona(sid, 'whale')
    core.set_session_mode(sid, 'work')
    result = core.add_message(sid, 'user', '接着聊')
    message = next(row for row in core.get_messages(sid) if row['id'] == result['id'])
    assert (message['persona_id'], message['interaction_mode']) == ('whale', 'work')
