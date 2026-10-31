"""飞书 CLI 只读适配器；单篇资料与账户按需检索共用。

安全边界：
- 只读；账户检索权限和每轮读取白名单由 feishu_account 约束；
- 默认使用 user 身份（lark-cli auth login 授权）；测试可用 XINJI_LARK_AS=bot；
- 内容只保存在本机 SQLite 的本次会话；撤回来源会清空派生记忆与原文。
"""
from __future__ import annotations

import json
import html
import hashlib
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

from . import faults, cli_runtime

def _standard_bin_dirs() -> list[Path]:
    home = Path.home()
    return [home / ".npm-global/bin", home / ".local/bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin")]


def discover_lark_bin() -> str:
    """Find an installed executable without assuming the developer's home."""
    candidates = [os.getenv("XINJI_LARK_BIN", "").strip(), shutil.which("lark-cli")]
    candidates.extend(str(directory / "lark-cli") for directory in _standard_bin_dirs())
    for candidate in candidates:
        if candidate:
            path = Path(candidate).expanduser()
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
    return "lark-cli"  # Existing FileNotFoundError handling explains installation.


def resolve_cli() -> str:
    """Prefer a native executable on Windows so no command shell is needed."""
    override = os.getenv("XINJI_LARK_BIN", "").strip()
    if override:
        return override
    found = cli_runtime.resolve("lark-cli", "XINJI_LARK_BIN")
    if os.name == "nt":
        candidates = [Path(Path(__file__).resolve().anchor) / "codex" / "tools" / "lark-cli"]
        if found:
            if Path(found).suffix.lower() == ".exe":
                return found
            candidates.insert(0, Path(found).parent)
        for root in candidates:
            native = root / "node_modules" / "@larksuite" / "cli" / "bin" / "lark-cli.exe"
            if native.is_file():
                return str(native)
    return found or discover_lark_bin()


LARK_BIN = resolve_cli()
LARK_HOME = Path(__file__).resolve().parent.parent / ".lark-home"
LARK_REAL_CONFIG = Path.home() / ".lark-cli"
TIMEOUT = 25
MAX_CHARS = 12000


def cli_env() -> dict:
    """默认用真实 HOME（钥匙串可用）；可用 XINJI_LARK_HOME 显式覆盖。"""
    env = cli_runtime.environment() if os.name == "nt" else os.environ.copy()
    entries = env.get("PATH", "").split(os.pathsep) if env.get("PATH") else []
    for directory in _standard_bin_dirs():
        value = str(directory)
        if directory.is_dir() and value not in entries:
            entries.append(value)
    env["PATH"] = os.pathsep.join(entries)
    override = os.getenv("XINJI_LARK_HOME", "").strip()
    if override:
        env["HOME"] = override
        if os.name == "nt":
            env["USERPROFILE"] = override
    return env


def _clean(markdown: str, *, limit: int | None = MAX_CHARS) -> str:
    text = re.sub(r"<title>.*?</title>", "", markdown, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)  # 去掉 callout/grid/column 等标签，保留正文
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)          # 图片
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)      # 链接
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.S)  # 加粗
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*", r"\1", text)        # 斜体
    text = re.sub(r"`([^`]+)`", r"\1", text)                      # 行内代码
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)            # 标题井号
    text = re.sub(r"^\s*[-*_]{3,}\s*$", "", text, flags=re.M)     # 分隔线
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue  # 表格分隔行
            s = " · ".join(c for c in cells if c)
        lines.append(s)
    text = "\n".join(lines)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return text if limit is None else text[:limit]


def _title(markdown: str) -> str:
    m = re.search(r"<title>(.*?)</title>", markdown, flags=re.S)
    if m:
        return m.group(1).strip()[:120]
    m = re.search(r"^#\s+(.+)$", markdown, flags=re.M)
    return (m.group(1).strip() if m else "飞书文档")[:120]


SETUP_HELP_URL = "https://open.feishu.cn/document/no_class/mcp-archive/feishu-cli-installation-guide.md"
ACCOUNT_READ_SCOPES = ("docx:document:readonly", "search:docs:read")


def cli_dependency_failure(result: subprocess.CompletedProcess) -> dict | None:
    """Recognize only the known env/node launcher failure, without raw output."""
    raw = ((result.stderr or "") + "\n" + (result.stdout or "")).lower()
    if result.returncode and re.search(r"(?:^|\n)(?:/usr/bin/)?env: (?:['\"])?node(?:['\"])?(?::|\s)", raw) and any(
            term in raw for term in ("no such file", "not found")):
        return {"ok": False, "error_code": "cli_dependency_missing",
                "error": "飞书 CLI 启动器需要 Node.js，但当前桌面环境找不到 node。请安装 Node.js 或检查标准安装路径。"}
    return None


def cli_configuration_failure(result: subprocess.CompletedProcess) -> dict | None:
    """Classify only the pinned official CLI's exact missing-app envelope.

    Neither arbitrary errors nor credential-store failures are permission to
    initialize/replace an app. Never return unfiltered CLI output or hints.
    """
    if result.returncode != 3:
        return None
    for raw in (result.stderr, result.stdout):
        try:
            envelope = json.loads(raw or "{}")
        except (ValueError, TypeError):
            continue
        error = envelope.get("error") if isinstance(envelope, dict) else None
        if (isinstance(envelope, dict) and envelope.get("ok") is False and isinstance(error, dict)
                and error.get("type") == "config" and error.get("message") == "not configured"):
            return {"ok": False, "app_configured": False, "config_status": "not_configured",
                    "error_code": "needs_app_setup", "error": "飞书应用尚未配置，请先完成官方应用配置，再回来授权。",
                    "setup_url": SETUP_HELP_URL}
    return None


def auth_status() -> dict:
    try:
        p = subprocess.run([LARK_BIN, "auth", "status"], capture_output=True, text=True, timeout=15, env=cli_env())
        if p.returncode != 0:
            dependency = cli_dependency_failure(p)
            if dependency:
                return dependency
            missing = cli_configuration_failure(p)
            if missing:
                return missing
            return {"ok": False, "app_configured": None, "config_status": "unavailable",
                    "error_code": "configuration_unavailable",
                    "error": f"lark-cli auth status failed (exit {p.returncode})"}
        data = json.loads(p.stdout)
        if not isinstance(data, dict) or data.get("ok") is False:
            return {"ok": False, "app_configured": None, "config_status": "unavailable",
                    "error_code": "configuration_unavailable", "error": "飞书授权状态暂时无法核对。"}
        identities = data.get("identities")
        user = identities.get("user") if isinstance(identities, dict) else None
        user = user if isinstance(user, dict) else {}
        configured = isinstance(data.get("appId"), str) and bool(data["appId"].strip())
        # Expose a one-way account fingerprint, never CLI account identifiers or
        # unrelated grants. Changing either application or user invalidates an
        # in-flight account retrieval instead of borrowing another login.
        app_id, open_id = data.get("appId"), user.get("openId")
        fingerprint = (hashlib.sha256(json.dumps([app_id, open_id], separators=(",", ":")).encode()).hexdigest()
                       if isinstance(app_id, str) and app_id and isinstance(open_id, str) and open_id else "")
        raw_scopes = user.get("scope") or ""
        scopes = re.split(r"[\s,]+", raw_scopes) if isinstance(raw_scopes, str) else raw_scopes
        scopes = set(scopes) if isinstance(scopes, list) and all(isinstance(s, str) for s in scopes) else set()
        return {
            "ok": True,
            "app_configured": True if configured else None,
            "config_status": "configured" if configured else "unknown",
            "identity": data.get("identity"),
            "user_status": user.get("status"),
            "token_status": user.get("tokenStatus"),
            "expires_at": user.get("expiresAt"),
            "account_key": fingerprint,
            "scopes": [scope for scope in ACCOUNT_READ_SCOPES if scope in scopes],
        }
    except Exception:
        # Timeout/JSON/OS exception text can contain arbitrary process output.
        return {"ok": False, "app_configured": None, "config_status": "unavailable",
                "error_code": "configuration_unavailable", "error": "飞书授权状态暂时无法核对。"}


def user_ready(status: dict) -> bool:
    """A configured user is not proof that its reported token is usable."""
    user = str(status.get("user_status") or "").lower()
    token = str(status.get("token_status") or "").lower()
    return bool(status.get("ok")) and user in ("ready", "valid", "authorized") and token not in (
        "expired", "invalid", "missing", "revoked",
    )


def read_doc(url: str, *, identity: str | None = None, keyword: str = "") -> dict:
    """读取单篇飞书文档；返回 {ok,title,text,identity} 或 {ok:false,error,hint}。"""
    if faults.active("lark_auth"):
        return {"ok": False, "error": "飞书授权已过期（演练）",
                "hint": "故障演练：/api/debug/faults 关闭 lark_auth 后重试"}
    url = (url or "").strip()
    if not url or not re.match(r"^https?://", url):
        return {"ok": False, "error": "请提供完整的飞书文档链接（https://…）"}
    identity = identity or os.getenv("XINJI_LARK_AS", "user").strip() or "user"
    cmd = [
        LARK_BIN, "docs", "+fetch", "--api-version", "v2",
        "--as", identity, "--doc", url, "--doc-format", "markdown",
    ]
    if keyword:
        if not isinstance(keyword, str) or len(keyword) > 512 or not keyword.strip():
            return {"ok": False, "error": "文档定位关键词需要 1–512 字"}
        # Official CLI keyword scope searches the whole document before export,
        # so long documents are not silently reduced to their opening section.
        cmd.extend(["--scope", "keyword", "--keyword", keyword.strip(),
                    "--context-before", "1", "--context-after", "2"])
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, env=cli_env())
    except FileNotFoundError:
        return {"ok": False, "error": "未找到 lark-cli", "hint": "安装或检查 PATH"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "读取超时（25s）", "hint": "检查网络或稍后重试"}
    except Exception:
        return {"ok": False, "error": "无法启动飞书文档读取", "hint": "确认 lark-cli 可运行，再重新读取；不会自动重新授权"}

    dependency = cli_dependency_failure(p)
    if dependency:
        return dependency
    raw = p.stdout.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        stderr = (p.stderr or "") + (raw or "")
        if "refresh failed" in stderr or "need_user_authorization" in stderr or "token_missing" in stderr:
            return {
                "ok": False,
                "error": "飞书授权已过期",
                "hint": '在终端执行：lark-cli auth login --scope "docx:document:readonly"',
            }
        return {"ok": False, "error": "lark-cli 返回非 JSON", "hint": "请检查 CLI 安装、授权与网络"}

    if not isinstance(data, dict):
        return {"ok": False, "error": "lark-cli 返回格式无效", "hint": "请检查 CLI 版本"}
    if p.returncode != 0 and data.get("ok"):
        return {"ok": False, "error": f"飞书读取失败（CLI 退出码 {p.returncode}）", "hint": "请检查授权与网络"}

    if not data.get("ok"):
        err = data.get("error") or {}
        if not isinstance(err, dict):
            return {"ok": False, "error": "飞书文档读取失败", "hint": "检查飞书权限和网络，再重新读取"}
        hint = err.get("hint") or "请先在终端执行 lark-cli auth login 授权"
        return {"ok": False, "error": err.get("message") or "读取失败", "hint": hint,
                "subtype": err.get("subtype")}

    payload = data.get("data") or {}
    document = payload.get("document") if isinstance(payload, dict) else None
    if not isinstance(document, dict) or not isinstance(document.get("content", ""), str):
        return {"ok": False, "error": "飞书文档返回格式无法识别", "hint": "确认 lark-cli 版本后重新读取，或换一篇文档"}
    content = document.get("content") or ""
    extracted = _clean(content, limit=None)
    text = extracted[:MAX_CHARS]
    if not text:
        if keyword:
            return {"ok": False, "error": "未找到匹配关键词的正文", "error_code": "keyword_no_match"}
        return {"ok": False, "error": "文档为空或无可读文本"}
    return {
        "ok": True,
        "title": _title(content),
        "text": text,
        "length": len(text),
        "extracted_length": len(extracted),
        "truncated": len(extracted) > len(text),
        "partial": bool(keyword) or len(extracted) > len(text),
        "read_scope": "keyword" if keyword else "full",
        "identity": data.get("identity") or identity,
        "source": "feishu",
    }


def search_docs(query: str = "", limit: int = 10) -> dict:
    """搜索用户可访问的飞书文档（真实）。"""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "先输入要搜索的文档关键词", "hint": "例如：项目、周会、PRD"}
    try:
        p = subprocess.run(
            [LARK_BIN, "docs", "+search", "--as", "user", "--query", q, "--format", "json", "--page-size", str(limit)],
            capture_output=True, text=True, timeout=30, env=cli_env(),
        )
        dependency = cli_dependency_failure(p)
        if dependency:
            return dependency
        data = json.loads(p.stdout or "{}")
    except FileNotFoundError:
        return {"ok": False, "error": "未找到 lark-cli", "hint": "安装或检查 PATH 后重新搜索，也可以直接粘贴文档链接"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "搜索飞书文档超时", "hint": "检查网络后重试，也可以直接粘贴文档链接"}
    except Exception:
        return {"ok": False, "error": "搜索飞书文档失败", "hint": "检查 lark-cli 版本与网络后重试，也可以直接粘贴文档链接"}
    if not isinstance(data, dict):
        return {"ok": False, "error": "飞书搜索返回格式无法识别", "hint": "检查 lark-cli 版本后重试，也可以直接粘贴文档链接"}
    if p.returncode != 0 and data.get("ok"):
        return {"ok": False, "error": f"搜索飞书文档失败（CLI 退出码 {p.returncode}）", "hint": "检查飞书权限和网络后重试，也可以直接粘贴文档链接"}
    if not data.get("ok", False):
        err = data.get("error") or {}
        # Only offer a new grant when the CLI identifies the relevant missing
        # permission; ordinary network and search errors must not trigger it.
        if not isinstance(err, dict):
            return {"ok": False, "error": "搜索失败", "hint": "检查飞书权限和网络，或直接粘贴文档链接。"}
        details = json.dumps(err, ensure_ascii=False).lower()
        if "search:docs:read" in details:
            if "need_user_authorization" in details:
                return {"ok": False, "error": "搜索云空间需要单独授权",
                        "hint": "可选择授权搜索，或直接粘贴文档链接。",
                        "permission_issue": "user_grant"}
            if "console_url" in details:
                return {"ok": False, "error": "飞书应用未开通搜索权限",
                        "hint": "请联系飞书应用管理员开通 search:docs:read；也可以直接粘贴文档链接。",
                        "permission_issue": "app_config"}
            if any(x in details for x in ("need_user_authorization", "authorization", "scope", "permission")):
                return {"ok": False, "error": "搜索云空间需要单独授权",
                        "hint": "可选择授权搜索，或直接粘贴文档链接。",
                        "permission_issue": "user_grant"}
        return {"ok": False, "error": err.get("message") or "搜索失败",
                "hint": err.get("hint") or "确认授权后可搜索文档"}
    raw = data.get("data", {})
    if not isinstance(raw, dict):
        return {"ok": False, "error": "飞书搜索返回格式无法识别", "hint": "检查 lark-cli 版本后重试，也可以直接粘贴文档链接"}
    rows = raw.get("items") or raw.get("docs") or raw.get("results") or []
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return {"ok": False, "error": "飞书搜索返回格式无法识别", "hint": "检查 lark-cli 版本后重试，也可以直接粘贴文档链接"}
    items = []
    for r in rows:
        meta = r.get("result_meta") if isinstance(r.get("result_meta"), dict) else {}
        title = r.get("title") or r.get("name") or r.get("doc_title") or r.get("title_highlighted") or "未命名文档"
        title = html.unescape(re.sub(r"<[^>]*>", "", str(title)))
        url = r.get("url") or r.get("doc_url") or r.get("link") or meta.get("url") or ""
        token = r.get("token") or r.get("doc_token") or ""
        kind = r.get("type") or r.get("doc_type") or meta.get("doc_types") or ""
        if not all(isinstance(value, str) for value in (url, token, kind)):
            return {"ok": False, "error": "飞书搜索条目格式无法识别", "hint": "检查 lark-cli 版本后重试，也可以直接粘贴文档链接"}
        path = {"DOCX": "docx", "DOC": "docs", "WIKI": "wiki"}.get(str(kind).upper())
        if not url and token and path:
            url = f"https://feishu.cn/{path}/{token}"
        if title:
            items.append({"title": title[:80], "url": url, "type": kind or "unknown"})
    return {"ok": True, "items": items[:limit], "query": q}


def parse_search_time(value) -> datetime | None:
    """Normalize public Search v2 timestamps; missing dates never mean recent."""
    try:
        if isinstance(value, bool) or value in (None, ""):
            return None
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
            stamp = float(value)
            if stamp > 10**11:
                stamp /= 1000
            return datetime.fromtimestamp(stamp, timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def search_recent_docs(since: datetime, until: datetime, *, activity: str = "edited", limit: int = 8) -> dict:
    """Browse a bounded real personal-activity window with official CLI filters.

    Both filters describe the current user's actions, not all tenant activity.
    Only public document metadata is returned. Search v2 may snap my-edit
    boundaries to an hour; the adapter checks returned dates again so a boundary
    match is not silently represented as a precise seven-day match.
    """
    if (not isinstance(since, datetime) or not isinstance(until, datetime)
            or since.tzinfo is None or until.tzinfo is None or activity not in ("edited", "opened")
            or not 0 < (until - since).total_seconds() <= timedelta(days=7).total_seconds()):
        return {"ok": False, "error_code": "invalid_recent_window", "error": "近期文档需要不超过 7 天的明确时间范围。"}
    limit = min(max(int(limit), 1), 8)
    # my_edit_time is hour-aggregated. Query only complete hours INSIDE the
    # requested interval rather than accepting the CLI's outward hour snapping.
    # opened activity is precise; the union still covers newly opened documents.
    query_since, query_until = since, until
    if activity == "edited":
        query_since = since.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        if query_since < since:
            query_since += timedelta(hours=1)
        query_until = until.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        if query_since >= query_until:
            return {"ok": False, "error_code": "invalid_recent_window", "error": "编辑记录的时间范围需要至少覆盖一个完整小时。"}
    start, end = query_since.isoformat(timespec="seconds"), query_until.isoformat(timespec="seconds")
    command = [LARK_BIN, "drive", "+search", "--as", "user", "--query", "",
               f"--{activity}-since", start, f"--{activity}-until", end,
               "--sort", "edit_time" if activity == "edited" else "open_time",
               "--doc-types", "docx,doc,wiki", "--page-size", str(limit), "--format", "json"]
    try:
        process = subprocess.run(command, capture_output=True, text=True, timeout=30, env=cli_env())
        dependency = cli_dependency_failure(process)
        if dependency:
            return dependency
        envelope = json.loads(process.stdout or "{}")
    except FileNotFoundError:
        return {"ok": False, "error_code": "cli_missing", "error": "未找到飞书 CLI，请安装后再连接。"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error_code": "recent_search_timeout", "error": "读取近期飞书文档超时，请稍后重试。"}
    except Exception:
        return {"ok": False, "error_code": "recent_search_failed", "error": "近期飞书文档暂时无法读取。"}
    if not isinstance(envelope, dict) or process.returncode != 0 or envelope.get("ok") is not True:
        error = envelope.get("error") if isinstance(envelope, dict) else None
        details = json.dumps(error, ensure_ascii=False).lower() if isinstance(error, dict) else ""
        permission = ("user_grant" if "need_user_authorization" in details else
                      "app_config" if "search:docs:read" in details and "console_url" in details else "")
        return {"ok": False, "error_code": "recent_search_failed", "error": "近期飞书文档暂时无法读取。",
                **({"permission_issue": permission} if permission else {})}
    data = envelope.get("data")
    rows = data.get("results") if isinstance(data, dict) else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return {"ok": False, "error_code": "recent_search_invalid", "error": "近期飞书文档的返回格式无法识别。"}
    items, excluded = [], 0
    for row in rows[:limit]:
        meta = row.get("result_meta")
        if not isinstance(meta, dict):
            excluded += 1
            continue
        updated = parse_search_time(meta.get("update_time_iso") or meta.get("update_time"))
        opened = parse_search_time(meta.get("last_open_time_iso") or meta.get("last_open_time"))
        matched = updated if activity == "edited" else opened
        if matched is None or not since <= matched <= until:
            excluded += 1
            continue
        title = row.get("title") or row.get("title_highlighted") or row.get("name") or "未命名文档"
        url, kind = meta.get("url"), meta.get("doc_types")
        if not isinstance(url, str) or not isinstance(kind, str):
            excluded += 1
            continue
        items.append({"title": html.unescape(re.sub(r"<[^>]*>", "", str(title)))[:120],
                      "url": url, "type": kind,
                      "updated_at": updated.isoformat(timespec="seconds") if updated else "",
                      "opened_at": opened.isoformat(timespec="seconds") if opened else "",
                      "matched_at": matched.isoformat(timespec="seconds"), "matched_by": [activity]})
    return {"ok": True, "items": items, "activity": activity,
            "has_more": data.get("has_more") is True, "excluded_count": excluded,
            "since": start, "until": end}
