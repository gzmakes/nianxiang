"""Small SQLite idempotency ledger for a single-process local chat server.

Initialize after ``core.init_db()`` and share its database path. The ledger stores
the request hash and a caller-supplied result reference, never the request text.
Do not put the whole conversation, tokens, or credentials in ``complete``.

The generator writes messages in a separate transaction. A process interruption
can therefore leave an uncertain outcome: previous-process ``running`` requests
become ``unknown`` and must be reconciled, never automatically executed again.
This module deliberately does not claim exactly-once delivery across crashes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import uuid
from typing import Any, Callable
import weakref


_PROCESS_OWNER = uuid.uuid4().hex
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_LOCKS_GUARD = threading.Lock()
_REQUEST_LOCKS = weakref.WeakValueDictionary()


class TurnConflict(ValueError):
    """A request ID was already bound to a different session or payload."""


class TurnNotFound(LookupError):
    """No request belongs to the requested session."""


class TurnLeaseLost(RuntimeError):
    """The request was removed, recovered, or settled by another owner."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class TurnRecord:
    request_id: str
    session_id: str
    status: str
    cancel_requested: bool
    outcome: dict[str, Any] | None
    error_code: str | None
    created_at: str
    updated_at: str

    def public(self) -> dict[str, Any]:
        """Safe response fields: no payload hash, owner, or execution token."""
        return {
            "request_id": self.request_id, "session_id": self.session_id,
            "status": self.status, "cancel_requested": self.cancel_requested,
            "outcome": self.outcome, "error_code": self.error_code,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class Claim:
    claimed: bool
    record: TurnRecord
    token: str | None = None
    bypassed_busy: bool = False


class ChatTurnStore:
    """One ledger per application process; SQLite serializes concurrent claims.

    ``owner_id`` is injectable for restart tests. The default is shared by all
    store instances in this process. Startup recovery assumes one server worker;
    do not use it to steal work from another live process sharing the database.
    """

    def __init__(self, db_path: str | Path, *, owner_id: str | None = None,
                 recover: bool = True):
        self.db_path = str(db_path)
        self.owner_id = owner_id or _PROCESS_OWNER
        with closing(self._connect()) as conn, conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_turns (
                    request_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('running','completed','cancelled','unknown')),
                    owner_id TEXT NOT NULL,
                    claim_token TEXT NOT NULL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
                    outcome_json TEXT,
                    error_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS chat_turns_session ON chat_turns(session_id)")
            from . import conversation_changes
            conversation_changes.init_schema(conn)
        if recover:
            self.recover_interrupted()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def reply_lock(self, session_id: str, request_id: str):
        """RLock for the short cancellation-check + assistant-commit boundary.

        Do not hold this during a remote model request. Cancellation acquires the
        same lock, so core should check ``cancel_check`` while holding it just
        before writing a result. Weak references release unused lock objects.
        """
        key = (str(Path(self.db_path).resolve()), session_id, request_id)
        with _LOCKS_GUARD:
            lock = _REQUEST_LOCKS.get(key)
            if lock is None:
                lock = threading.RLock()
                _REQUEST_LOCKS[key] = lock
            return lock

    def cancel_check(self, session_id: str, request_id: str, token: str) -> Callable[[], bool]:
        """Callback accepted by core; stale/deleted requests also return True."""
        return lambda: self.is_cancel_requested(session_id, request_id, token)

    @staticmethod
    def _record(row: sqlite3.Row) -> TurnRecord:
        return TurnRecord(
            request_id=row["request_id"], session_id=row["session_id"],
            status=row["status"], cancel_requested=bool(row["cancel_requested"]),
            outcome=json.loads(row["outcome_json"]) if row["outcome_json"] else None,
            error_code=row["error_code"], created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def recover_interrupted(self) -> int:
        """On process startup, quarantine unfinished old-process work."""
        with closing(self._connect()) as conn, conn:
            changed = conn.execute(
                "UPDATE chat_turns SET status='unknown',error_code='process_interrupted',updated_at=? "
                "WHERE status='running' AND owner_id!=?", (_now(), self.owner_id))
            return changed.rowcount

    def claim(self, session_id: str, request_id: str, text: str, *,
              options: dict[str, Any] | None = None, allow_while_busy: bool = False,
              cancel_running: bool = False) -> Claim:
        """Claim once; repeats return the stored state without executing again.

        Include behavior-changing request options (for example memory_proposals)
        in ``options``. The text is hashed exactly as received, not normalized.
        Unknown/cancelled requests are terminal and are never silently reclaimed.
        """
        if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
            raise ValueError("request_id must be 8-128 URL-safe identifier characters")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be nonempty")
        if options is not None and not isinstance(options, dict):
            raise ValueError("options must be an object")
        digest = hashlib.sha256(_json({"text": text, "options": options or {}}).encode()).hexdigest()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM chat_turns WHERE request_id=?", (request_id,)).fetchone()
            if row:
                if row["session_id"] != session_id or row["payload_hash"] != digest:
                    raise TurnConflict("request_id is bound to a different session or payload")
                conn.commit()
                return Claim(False, self._record(row))
            if not conn.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone():
                raise TurnNotFound("session not found")
            token, timestamp = uuid.uuid4().hex, _now()
            busy = bool(conn.execute("SELECT 1 FROM chat_turns WHERE session_id=? AND status='running' LIMIT 1", (session_id,)).fetchone())
            if busy and not allow_while_busy:
                # A durable rejection is essential: a late or duplicated POST
                # with this ID must never become executable after the first
                # request finishes. 'unknown' preserves old DTO compatibility;
                # this exact error code alone means generation never started.
                conn.execute(
                    "INSERT INTO chat_turns(request_id,session_id,payload_hash,status,owner_id,claim_token,error_code,created_at,updated_at) "
                    "VALUES(?,?,?,'unknown',?,?,'conversation_busy_not_accepted',?,?)",
                    (request_id, session_id, digest, self.owner_id, token, timestamp, timestamp))
                row = conn.execute("SELECT * FROM chat_turns WHERE request_id=?", (request_id,)).fetchone()
                conn.commit()
                return Claim(False, self._record(row))
            if busy and allow_while_busy and cancel_running:
                # Safety replies take priority over still-running ordinary turns.
                # A result that already committed cannot be retroactively undone.
                conn.execute("UPDATE chat_turns SET cancel_requested=1,updated_at=? WHERE session_id=? AND status='running'", (timestamp, session_id))
            conn.execute(
                "INSERT INTO chat_turns(request_id,session_id,payload_hash,status,owner_id,claim_token,created_at,updated_at) "
                "VALUES(?,?,?,'running',?,?,?,?)",
                (request_id, session_id, digest, self.owner_id, token, timestamp, timestamp))
            row = conn.execute("SELECT * FROM chat_turns WHERE request_id=?", (request_id,)).fetchone()
            conn.commit()
            return Claim(True, self._record(row), token, busy and allow_while_busy)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get(self, session_id: str, request_id: str) -> TurnRecord:
        with closing(self._connect()) as conn, conn:
            row = conn.execute("SELECT * FROM chat_turns WHERE request_id=? AND session_id=?",
                               (request_id, session_id)).fetchone()
        if row is None:
            raise TurnNotFound("request not found")
        return self._record(row)

    def _settle(self, session_id: str, request_id: str, token: str, status: str, *,
                outcome: dict[str, Any] | None = None, error_code: str | None = None,
                require_cancel: bool = False) -> TurnRecord:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM chat_turns WHERE request_id=? AND session_id=?",
                               (request_id, session_id)).fetchone()
            if (row is None or row["owner_id"] != self.owner_id or row["claim_token"] != token
                    or row["status"] != "running"):
                raise TurnLeaseLost("request no longer belongs to this execution")
            if require_cancel and not row["cancel_requested"]:
                raise TurnConflict("cancellation was not requested")
            conn.execute("UPDATE chat_turns SET status=?,outcome_json=?,error_code=?,updated_at=? WHERE request_id=?",
                         (status, _json(outcome) if outcome is not None else None,
                          error_code, _now(), request_id))
            row = conn.execute("SELECT * FROM chat_turns WHERE request_id=?", (request_id,)).fetchone()
            conn.commit()
            return self._record(row)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def complete(self, session_id: str, request_id: str, token: str,
                 outcome: dict[str, Any]) -> TurnRecord:
        """Persist minimal result IDs after the generator has actually committed.

        Completion may win a late cancel request: completed work must not be
        falsely described as cancelled. The caller decides the commit boundary.
        """
        if not isinstance(outcome, dict):
            raise ValueError("outcome must be an object")
        encoded = _json(outcome)
        if len(encoded.encode()) > 16384:
            raise ValueError("outcome must contain small result references, not a conversation snapshot")
        with self.reply_lock(session_id, request_id):
            return self._settle(session_id, request_id, token, "completed", outcome=outcome)

    def mark_unknown(self, session_id: str, request_id: str, token: str, *,
                     error_code: str = "execution_uncertain") -> TurnRecord:
        """Generator raised after potentially writing: do not automatically retry."""
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error_code):
            raise ValueError("error_code must be a short machine code")
        with self.reply_lock(session_id, request_id):
            return self._settle(session_id, request_id, token, "unknown", error_code=error_code)

    def request_cancel(self, session_id: str, request_id: str) -> TurnRecord:
        """Request cooperative cancellation; this does not promise work stopped."""
        with self.reply_lock(session_id, request_id):
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    "UPDATE chat_turns SET cancel_requested=1,updated_at=? "
                    "WHERE request_id=? AND session_id=? AND status IN ('running','unknown')",
                    (_now(), request_id, session_id))
                # A completed result is returned unchanged; no result is fabricated.
            return self.get(session_id, request_id)

    def is_cancel_requested(self, session_id: str, request_id: str, token: str) -> bool:
        """A removed session or stale execution must also stop before committing."""
        with closing(self._connect()) as conn, conn:
            row = conn.execute("SELECT * FROM chat_turns WHERE request_id=? AND session_id=?",
                               (request_id, session_id)).fetchone()
        return (row is None or row["owner_id"] != self.owner_id or row["claim_token"] != token
                or row["status"] != "running" or bool(row["cancel_requested"]))

    def finish_cancelled(self, session_id: str, request_id: str, token: str, *,
                         outcome: dict[str, Any] | None = None) -> TurnRecord:
        """Call only after the generator confirms no assistant result was committed."""
        with self.reply_lock(session_id, request_id):
            return self._settle(session_id, request_id, token, "cancelled", outcome=outcome,
                                require_cancel=True)

    def delete_for_session(self, session_id: str, *, connection: sqlite3.Connection | None = None) -> int:
        """Delete in the same transaction as session deletion when possible.

        Core's existing connection may not enable foreign keys, so integrate this
        explicit delete there instead of depending solely on ON DELETE CASCADE.
        """
        if connection is not None:
            return connection.execute("DELETE FROM chat_turns WHERE session_id=?", (session_id,)).rowcount
        with closing(self._connect()) as conn, conn:
            return conn.execute("DELETE FROM chat_turns WHERE session_id=?", (session_id,)).rowcount
