"""Only synthetic SQLite state; no model, credentials, or user database."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from server.chat_turns import ChatTurnStore, TurnConflict, TurnLeaseLost, TurnNotFound


class ChatTurnsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "synthetic.db"
        with sqlite3.connect(self.path) as conn:
            conn.executescript("""
                CREATE TABLE sessions(id TEXT PRIMARY KEY);
                INSERT INTO sessions VALUES ('session-a'),('session-b');
                CREATE TABLE synthetic_messages(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT);
            """)
        self.store = ChatTurnStore(self.path, owner_id="process-a")

    def test_concurrent_same_id_executes_generator_and_writes_messages_once(self):
        count = 0
        lock = threading.Lock()
        barrier = threading.Barrier(12)

        def handle(_):
            nonlocal count
            barrier.wait(timeout=5)
            claim = self.store.claim("session-a", "request-concurrent", "合成用户发言")
            if claim.claimed:
                with lock:
                    count += 1
                with sqlite3.connect(self.path) as conn:
                    conn.execute("INSERT INTO synthetic_messages(session_id,role) VALUES('session-a','user')")
                    conn.execute("INSERT INTO synthetic_messages(session_id,role) VALUES('session-a','assistant')")
                self.store.complete("session-a", "request-concurrent", claim.token,
                                    {"user_message_id": "synthetic-user", "assistant_message_id": "synthetic-assistant"})
            return claim.record.status

        with ThreadPoolExecutor(max_workers=12) as pool:
            states = list(pool.map(handle, range(12)))
        self.assertEqual(count, 1)
        self.assertTrue(set(states) <= {"running", "completed"})
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM synthetic_messages").fetchone()[0], 2)
        repeated = self.store.claim("session-a", "request-concurrent", "合成用户发言")
        self.assertFalse(repeated.claimed)
        self.assertEqual(repeated.record.outcome["assistant_message_id"], "synthetic-assistant")

    def test_http_response_loss_can_query_or_repeat_id_without_reexecution(self):
        claim = self.store.claim("session-a", "request-lost-response", "合成文本")
        self.assertEqual(self.store.get("session-a", "request-lost-response").status, "running")
        retry = self.store.claim("session-a", "request-lost-response", "合成文本")
        self.assertFalse(retry.claimed)
        self.store.complete("session-a", "request-lost-response", claim.token, {"user_message_id": "m-one"})
        retry = self.store.claim("session-a", "request-lost-response", "合成文本")
        self.assertFalse(retry.claimed)
        self.assertEqual(retry.record.outcome, {"user_message_id": "m-one"})

    def test_id_bound_to_session_exact_text_and_behavior_options(self):
        self.store.claim("session-a", "request-binding", "文字\n原样", options={"memory_proposals": True})
        for session, text, options in (
            ("session-b", "文字\n原样", {"memory_proposals": True}),
            ("session-a", "文字原样", {"memory_proposals": True}),
            ("session-a", "文字\n原样", {"memory_proposals": False}),
        ):
            with self.assertRaises(TurnConflict):
                self.store.claim(session, "request-binding", text, options=options)
        with self.assertRaises(TurnNotFound):
            self.store.get("session-b", "request-binding")

    def test_restart_quarantines_old_running_without_reexecuting_or_late_commit(self):
        running = self.store.claim("session-a", "request-interrupted", "生成到一半")
        done = self.store.claim("session-a", "request-finished", "已完成")
        self.store.complete("session-a", "request-finished", done.token, {"assistant_message_id": "done"})
        restarted = ChatTurnStore(self.path, owner_id="process-b")
        recovered = restarted.claim("session-a", "request-interrupted", "生成到一半")
        self.assertFalse(recovered.claimed)
        self.assertEqual(recovered.record.status, "unknown")
        self.assertEqual(recovered.record.error_code, "process_interrupted")
        self.assertEqual(restarted.get("session-a", "request-finished").status, "completed")
        with self.assertRaises(TurnLeaseLost):
            self.store.complete("session-a", "request-interrupted", running.token, {"assistant_message_id": "late"})
        self.assertTrue(self.store.is_cancel_requested("session-a", "request-interrupted", running.token))

    def test_second_store_same_process_does_not_recover_live_request(self):
        same_process = ChatTurnStore(self.path)
        claim = same_process.claim("session-a", "request-same-process", "合成文本")
        another_instance = ChatTurnStore(self.path)
        self.assertEqual(another_instance.get("session-a", "request-same-process").status, "running")
        another_instance.complete("session-a", "request-same-process", claim.token, {"assistant_message_id": "ok"})

    def test_cancel_is_request_until_worker_confirms_and_late_completed_is_truthful(self):
        claim = self.store.claim("session-a", "request-cancel", "尚在生成")
        cancelled = self.store.request_cancel("session-a", "request-cancel")
        self.assertEqual(cancelled.status, "running")
        self.assertTrue(cancelled.cancel_requested)
        self.assertTrue(self.store.is_cancel_requested("session-a", "request-cancel", claim.token))
        self.assertEqual(self.store.finish_cancelled("session-a", "request-cancel", claim.token).status, "cancelled")
        self.assertFalse(self.store.claim("session-a", "request-cancel", "尚在生成").claimed)
        late = self.store.claim("session-a", "request-too-late", "实际已经完成")
        self.store.request_cancel("session-a", "request-too-late")
        result = self.store.complete("session-a", "request-too-late", late.token, {"assistant_message_id": "committed"})
        self.assertEqual(result.status, "completed")
        self.assertEqual(self.store.request_cancel("session-a", "request-too-late").status, "completed")

    def test_cannot_finish_cancelled_before_a_cancellation_request(self):
        claim = self.store.claim("session-a", "request-not-cancelled", "合成文本")
        with self.assertRaises(TurnConflict):
            self.store.finish_cancelled("session-a", "request-not-cancelled", claim.token)
        self.assertEqual(self.store.get("session-a", "request-not-cancelled").status, "running")

    def test_exception_after_possible_writes_is_unknown_and_same_id_never_retries(self):
        claim = self.store.claim("session-a", "request-uncertain", "合成文本")
        self.store.mark_unknown("session-a", "request-uncertain", claim.token)
        result = self.store.claim("session-a", "request-uncertain", "合成文本")
        self.assertFalse(result.claimed)
        self.assertEqual(result.record.status, "unknown")

    def test_deleted_session_cleans_ledger_in_same_transaction_and_late_worker_stops(self):
        claim = self.store.claim("session-a", "request-deleted", "合成文本")
        with sqlite3.connect(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self.assertEqual(self.store.delete_for_session("session-a", connection=conn), 1)
            conn.execute("DELETE FROM sessions WHERE id='session-a'")
        self.assertTrue(self.store.is_cancel_requested("session-a", "request-deleted", claim.token))
        with self.assertRaises(TurnLeaseLost):
            self.store.complete("session-a", "request-deleted", claim.token, {"assistant_message_id": "late"})
        with self.assertRaises(TurnNotFound):
            self.store.claim("session-a", "request-new-after-delete", "合成文本")
        with self.assertRaises(TurnNotFound):
            self.store.get("session-a", "request-deleted")

    def test_session_delete_rollback_restores_request_records_together(self):
        self.store.claim("session-a", "request-rollback", "合成文本")
        conn = sqlite3.connect(self.path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            self.store.delete_for_session("session-a", connection=conn)
            conn.execute("DELETE FROM sessions WHERE id='session-a'")
            conn.rollback()
        finally:
            conn.close()
        self.assertEqual(self.store.get("session-a", "request-rollback").status, "running")

    def test_invalid_token_cannot_settle_or_erase_running_work(self):
        self.store.claim("session-a", "request-token", "合成文本")
        with self.assertRaises(TurnLeaseLost):
            self.store.complete("session-a", "request-token", "wrong-token", {"assistant_message_id": "bad"})
        self.assertEqual(self.store.get("session-a", "request-token").status, "running")

    def test_payload_text_and_internal_execution_token_not_in_public_state(self):
        secretish_synthetic_text = "ONLY_SYNTHETIC_NOT_A_REAL_SECRET"
        claim = self.store.claim("session-a", "request-no-plaintext", secretish_synthetic_text)
        public = str(claim.record.public())
        self.assertNotIn(claim.token, public)
        self.assertNotIn("payload_hash", public)
        with sqlite3.connect(self.path) as conn:
            stored = str(conn.execute("SELECT * FROM chat_turns").fetchall())
        self.assertNotIn(secretish_synthetic_text, stored)

    def test_cancel_callback_before_commit_prevents_the_synthetic_assistant_write(self):
        claim = self.store.claim("session-a", "request-callback", "合成文本")
        check = self.store.cancel_check("session-a", "request-callback", claim.token)
        self.assertFalse(check())
        self.store.request_cancel("session-a", "request-callback")
        with self.store.reply_lock("session-a", "request-callback"):
            if not check():
                self.fail("cancelled generation must not enter the assistant commit")
            self.store.finish_cancelled("session-a", "request-callback", claim.token)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM synthetic_messages").fetchone()[0], 0)

    def test_reply_lock_serializes_cancel_with_commit_and_is_reentrant(self):
        claim = self.store.claim("session-a", "request-lock-boundary", "合成文本")
        lock = self.store.reply_lock("session-a", "request-lock-boundary")
        self.assertIs(lock, self.store.reply_lock("session-a", "request-lock-boundary"))
        commit_entered, release_commit, cancel_attempted = threading.Event(), threading.Event(), threading.Event()

        def commit():
            with lock:
                self.assertFalse(self.store.cancel_check("session-a", "request-lock-boundary", claim.token)())
                commit_entered.set()
                self.assertTrue(release_commit.wait(timeout=3))
                # complete reacquires the same RLock without deadlock.
                return self.store.complete("session-a", "request-lock-boundary", claim.token,
                                           {"assistant_message_id": "committed-once"})

        def cancel():
            self.assertTrue(commit_entered.wait(timeout=3))
            cancel_attempted.set()
            return self.store.request_cancel("session-a", "request-lock-boundary")

        with ThreadPoolExecutor(max_workers=2) as pool:
            work = pool.submit(commit)
            stop = pool.submit(cancel)
            self.assertTrue(cancel_attempted.wait(timeout=3))
            self.assertFalse(stop.done())
            release_commit.set()
            self.assertEqual(work.result(timeout=3).status, "completed")
            result = stop.result(timeout=3)
        self.assertEqual(result.status, "completed")
        self.assertFalse(result.cancel_requested)


if __name__ == "__main__":
    unittest.main()
