"""Account-level, on-demand Feishu reading without a persistent document index.

Only connection state is stored. A TurnAccess owns a short-lived search allowlist
and bounded reads; document bodies are returned to its caller, never cached here.
CLI authentication remains owned by the official CLI.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
import threading
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

from . import document_retrieval, lark

REQUIRED_SCOPES = frozenset(lark.ACCOUNT_READ_SCOPES)
MAX_SEARCHES = 2
MAX_READS = 3
MAX_DOCUMENT_CHARS = 4000
MAX_CONTEXT_CHARS = 12000


def _keyword_or(query: str) -> str:
    """Make bounded literal OR branches; document queries are not raw regex."""
    branches = list(dict.fromkeys(part for part in re.split(r"[\s|]+", query) if part))
    if (query and not branches) or len(branches) > 12:
        raise ValueError("too many keyword branches")
    # The CLI falls back to RE2. Escape regex operators within each word while
    # retaining the explicit OR separators we create between words.
    return "|".join(re.sub(r"([\\.^$*+?{}\[\]()])", r"\\\1", part) for part in branches)


def init_schema(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS feishu_account_connections(
        session_id TEXT PRIMARY KEY,
        enabled INTEGER NOT NULL DEFAULT 0,
        version INTEGER NOT NULL DEFAULT 0,
        account_key TEXT NOT NULL DEFAULT '',
        connected_at TEXT NOT NULL DEFAULT ''
    )""")


def snapshot(conn, sid: str) -> dict:
    row = conn.execute("SELECT enabled,version,account_key,connected_at "
                       "FROM feishu_account_connections WHERE session_id=?", (sid,)).fetchone()
    enabled, version, key, connected = tuple(row) if row is not None else (0, 0, "", "")
    return {"enabled": bool(enabled), "version": int(version), "account_key": key,
            "connected_at": connected, "mode": "account_readonly"}


def set_enabled(conn, sid: str, enabled: bool, account_key: str | None = None) -> dict:
    """Update within the caller's transaction; every transition invalidates turns.

    Enabling requires the fingerprint returned by verify_access. This function
    never starts login, reads documents, or commits a caller's transaction.
    """
    previous = snapshot(conn, sid)
    key = account_key if account_key is not None else previous["account_key"]
    if enabled and not re.fullmatch(r"[a-f0-9]{64}", key or ""):
        raise ValueError("Verify the Feishu account before enabling it")
    # A retry after the same successful authorization is the same connection
    # receipt, not a new generation of its first assistant conversation.
    if enabled and previous["enabled"] and key == previous["account_key"]:
        return previous
    from . import connection_intro
    # Keep cancellation in this caller-owned transaction with the transition;
    # no old pending introduction survives a disconnect/account replacement.
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='connection_intro_jobs'").fetchone():
        connection_intro.cancel_for_account(conn, sid)
    connected = datetime.now(timezone.utc).isoformat(timespec="seconds") if enabled else previous["connected_at"]
    conn.execute("""INSERT INTO feishu_account_connections(session_id,enabled,version,account_key,connected_at)
        VALUES(?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET enabled=excluded.enabled,
        version=feishu_account_connections.version+1, account_key=excluded.account_key,
        connected_at=excluded.connected_at""", (sid, int(bool(enabled)), previous["version"] + 1, key or "", connected))
    return snapshot(conn, sid)


def canonical_document_url(value: str) -> str:
    """Only real Feishu/Lark HTTPS docx/docs/wiki resources can be read."""
    if not isinstance(value, str) or len(value) > 2048:
        return ""
    try:
        parts = urlsplit(value.strip())
        host = (parts.hostname or "").lower()
        official = host in ("feishu.cn", "larksuite.com") or host.endswith((".feishu.cn", ".larksuite.com"))
        if (parts.scheme != "https" or not official or parts.username is not None or parts.password is not None
                or parts.port not in (None, 443) or not re.fullmatch(r"/(?:docx|docs|wiki)/[A-Za-z0-9_-]+/?", parts.path)):
            return ""
        return urlunsplit(("https", host, parts.path.rstrip("/"), "", ""))
    except (TypeError, ValueError):
        return ""


def _failure(code: str, message: str, *, permission_issue: str = "") -> dict:
    result = {"ok": False, "ready": False, "error_code": code, "error": message}
    if permission_issue:
        result["permission_issue"] = permission_issue
    return result


def _readiness(status: dict) -> dict | None:
    if not status.get("ok"):
        if status.get("error_code") == "cli_dependency_missing":
            return _failure("cli_dependency_missing", "飞书 CLI 启动器找不到 Node.js，请检查桌面环境的标准安装路径。")
        app_setup = status.get("error_code") == "needs_app_setup"
        return _failure("needs_app_setup" if app_setup else "authorization_unavailable",
                        "请先完成飞书应用配置。" if app_setup else "暂时无法核对飞书授权，请稍后重试。",
                        permission_issue="app_config" if app_setup else "")
    # An official CLI refreshable grant may renew itself during the read. Do not
    # force a fresh login merely because the short-lived access token needs that
    # routine renewal; revoked/expired/missing grants always remain blocked.
    refreshable = (status.get("user_status") == "needs_refresh"
                   and status.get("token_status") not in ("expired", "invalid", "missing", "revoked"))
    if not lark.user_ready(status) and not refreshable:
        return _failure("authorization_not_ready", "飞书授权尚未就绪或已过期，请重新连接。", permission_issue="user_grant")
    if not status.get("account_key"):
        return _failure("account_unavailable", "暂时无法核对当前飞书账户，请检查 CLI 版本后重试。")
    scopes = status.get("scopes")
    granted = set(scopes) if isinstance(scopes, list) and all(isinstance(s, str) for s in scopes) else set()
    if not REQUIRED_SCOPES.issubset(granted):
        return _failure("missing_account_scopes", "账户连接需要文档只读与搜索权限，请在官方页面核对授权。", permission_issue="user_grant")
    return None


def _search_failure(result: dict) -> dict:
    issue = result.get("permission_issue")
    if issue == "app_config":
        return _failure("search_app_permission", "飞书应用未开通搜索权限，请联系应用管理员。", permission_issue=issue)
    if issue == "user_grant":
        return _failure("search_user_permission", "当前飞书账户缺少搜索授权，请重新连接并核对权限。", permission_issue=issue)
    return _failure("search_failed", "飞书搜索未完成，请检查网络后重试。")


def grant_readiness(status: dict) -> dict | None:
    """Public local-status check; None means the existing grant may be used.

    This does not execute search or login and does not prove the remote API
    responds. It accepts the CLI's refreshable state for its routine renewal.
    """
    return _readiness(status)


def verify_access(query: str = "念响") -> dict:
    """Check existing grants and the real search API; no login or body retrieval."""
    before = lark.auth_status()
    problem = _readiness(before)
    if problem:
        return problem
    result = lark.search_docs(query, limit=1)
    if not result.get("ok"):
        return _search_failure(result)
    after = lark.auth_status()
    problem = _readiness(after)
    if problem:
        return problem
    if before["account_key"] != after["account_key"]:
        return _failure("account_changed", "核对期间飞书账户发生变化，请重新连接。")
    return {"ok": True, "ready": True, "account_key": after["account_key"],
            "scopes": list(lark.ACCOUNT_READ_SCOPES), "search_checked": True,
            "mode": "account_readonly"}


class TurnAccess:
    """One turn's read-only capability, with revocation and account-switch checks."""

    def __init__(self, get_current: Callable[[], dict]):
        self.get_current = get_current
        self.initial = dict(get_current())
        self.search_count = 0
        self.read_count = 0
        self.context_chars = 0
        self._allowed: dict[str, dict] = {}
        self._read_requests: set[tuple[str, str]] = set()
        self._has_context = False
        self._lock = threading.Lock()

    @property
    def has_context(self) -> bool:
        """Whether any account document metadata/body was exposed this turn."""
        return self._has_context

    def _guard(self) -> dict | None:
        current = self.get_current()
        if (not self.initial.get("enabled") or not current.get("enabled")
                or any(current.get(k) != self.initial.get(k) for k in ("version", "account_key"))):
            return _failure("connection_changed", "飞书连接已断开或发生变化，本轮检索已停止。")
        status = lark.auth_status()
        problem = _readiness(status)
        if problem:
            return problem
        if status["account_key"] != self.initial.get("account_key"):
            return _failure("account_changed", "当前飞书账户已切换，请重新连接后再读取。")
        return None

    def is_current(self) -> bool:
        return self._guard() is None

    def search(self, query: str) -> dict:
        with self._lock:
            problem = self._guard()
            if problem:
                return problem
            if self.search_count >= MAX_SEARCHES:
                return _failure("search_budget_exhausted", "本轮飞书搜索次数已用完。")
            if not isinstance(query, str) or not query.strip() or len(query.strip()) > 256:
                return _failure("invalid_query", "请输入 1–256 字的文档搜索关键词。")
            self.search_count += 1
            result = lark.search_docs(query.strip(), limit=8)
            problem = self._guard()
            if problem:
                return problem  # Never return content retrieved after revocation.
            if not result.get("ok"):
                return _search_failure(result)
            items = []
            unsupported = 0
            for row in result.get("items") or []:
                if not isinstance(row, dict):
                    continue
                url = canonical_document_url(row.get("url", ""))
                if not url:
                    unsupported += 1
                    continue
                title = row.get("title") if isinstance(row.get("title"), str) else "飞书文档"
                item = {"title": title[:120], "url": url, "type": str(row.get("type") or "unknown")[:40]}
                self._allowed[url] = item
                items.append(item)
            answer = {"ok": True, "items": items, "query": query.strip(), "unsupported_count": unsupported}
            if unsupported:
                answer["notice"] = (f"本次搜索另有 {unsupported} 项暂不支持读取；目前支持文本文档和 Wiki 中的文本文档，"
                                    "表格、多维表格和妙搭应用需另接对应能力。")
            if items:
                self._has_context = True
            return answer

    def read(self, url: str, query: str = "") -> dict:
        with self._lock:
            problem = self._guard()
            if problem:
                return problem
            url = canonical_document_url(url)
            if not url or url not in self._allowed:
                return _failure("document_not_in_search", "只能读取本轮飞书搜索实际返回的文档。")
            if not isinstance(query, str) or len(query.strip()) > 256:
                return _failure("invalid_query", "文档定位关键词需要不超过 256 字。")
            query = query.strip()
            try:
                keyword = _keyword_or(query)
            except ValueError:
                return _failure("invalid_query", "文档定位请使用不超过 12 个短关键词，以空格或 | 分隔。")
            if (url, keyword) in self._read_requests:
                return _failure("document_already_read", "本轮已读取该文档的相同范围，请使用已返回的内容。")
            if self.read_count >= MAX_READS or self.context_chars >= MAX_CONTEXT_CHARS:
                return _failure("read_budget_exhausted", "本轮飞书文档读取额度已用完。")
            self.read_count += 1
            self._read_requests.add((url, keyword))
            result = lark.read_doc(url, identity="user", **({"keyword": keyword} if keyword else {}))
            problem = self._guard()
            if problem:
                return problem
            fallback = False
            if query and not result.get("ok") and result.get("error_code") == "keyword_no_match":
                # Only a genuine no-match may broaden the same allowed document
                # read. Permission, transport and arbitrary failures never do.
                problem = self._guard()
                if problem:
                    return problem
                result = lark.read_doc(url, identity="user")
                problem = self._guard()
                if problem:
                    return problem
                fallback = True
            if not result.get("ok"):
                if result.get("subtype") == "need_user_authorization":
                    return _failure("document_user_permission", "当前账户无权读取该文档，请检查文档分享与授权范围。", permission_issue="user_grant")
                return _failure("document_read_failed", "该飞书文档读取失败，可能已删除、权限不足或网络异常。")
            original = result.get("text")
            if not isinstance(original, str) or not original.strip():
                return _failure("document_empty", "该文档没有可读取的正文。")
            limit = min(MAX_DOCUMENT_CHARS, MAX_CONTEXT_CHARS - self.context_chars)
            passages = document_retrieval.relevant_excerpts(original, query) if fallback else []
            text = ("\n\n".join(passages) if passages else original)[:limit]
            self.context_chars += len(text)
            title = result.get("title")
            if not isinstance(title, str) or not title.strip() or title == "飞书文档":
                title = self._allowed[url]["title"]
            self._has_context = True
            answer = {"ok": True, "title": title[:120], "url": url, "text": text, "length": len(text),
                    "truncated": bool(result.get("truncated")) or len(text) < len(original),
                    "partial": bool(query) or bool(result.get("partial")) or bool(result.get("truncated")) or len(text) < len(original),
                    "excerpt": bool(query) or bool(result.get("partial")) or bool(result.get("truncated")) or len(text) < len(original),
                    "read_scope": ("full_fallback_relevant_excerpts" if passages else "full_fallback_opening") if fallback else ("keyword" if query else "full"),
                    "query": query, "effective_keyword": keyword, "fallback_used": fallback,
                    "keyword_missed": fallback and not passages, "source": "feishu"}
            if fallback:
                answer["notice"] = ("关键词直接定位未命中，已真实读取文档并按相关词提取节选，并非全文。" if passages else
                                    "关键词未匹配，返回文档开头供核对，不代表与问题相关。")
            return answer


class RecentAccess(TurnAccess):
    """Connection-intro capability: two real activity queries, same read guards.

    Arbitrary URLs cannot be registered by callers: only validated dated search
    results become readable. No document body survives outside the result.
    """

    def recent(self, since: datetime, until: datetime) -> dict:
        with self._lock:
            problem = self._guard()
            if problem:
                return problem
            if self.search_count:
                return _failure("search_budget_exhausted", "本次近期文档查询已经完成。")
            gathered = {}
            excluded, has_more = 0, False
            for activity in ("edited", "opened"):
                problem = self._guard()
                if problem:
                    return problem
                self.search_count += 1
                result = lark.search_recent_docs(since, until, activity=activity, limit=8)
                problem = self._guard()
                if problem:
                    return problem
                if not result.get("ok"):
                    return _search_failure(result)
                has_more = has_more or bool(result.get("has_more"))
                excluded += result.get("excluded_count", 0)
                for row in result.get("items", []):
                    url = canonical_document_url(row.get("url", ""))
                    matched = lark.parse_search_time(row.get("matched_at"))
                    if not url or matched is None or not since <= matched <= until:
                        excluded += 1
                        continue
                    item = {"title": str(row.get("title") or "飞书文档")[:120], "url": url,
                            "type": str(row.get("type") or "unknown")[:40],
                            "updated_at": row.get("updated_at", ""), "opened_at": row.get("opened_at", ""),
                            "matched_at": matched.isoformat(timespec="seconds"), "matched_by": [activity]}
                    previous = gathered.get(url)
                    if previous:
                        item["matched_by"] = list(dict.fromkeys(previous["matched_by"] + [activity]))
                        if previous["matched_at"] > item["matched_at"]:
                            item["matched_at"] = previous["matched_at"]
                    gathered[url] = item
            items = sorted(gathered.values(), key=lambda row: row["matched_at"], reverse=True)[:8]
            self._allowed = {row["url"]: row for row in items}
            self._has_context = bool(items)
            return {"ok": True, "items": items, "has_more": has_more or len(gathered) > 8,
                    "excluded_count": excluded, "limited": True}
