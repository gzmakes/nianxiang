"""飞书只读冷启动：按用户给出的文档 URL 读取单篇（PRD F21/F22/F23）。

安全边界：
- 只读、只读用户明确给出的那一篇；不搜索、不遍历、不自动扫描；
- 默认使用 user 身份（lark-cli auth login 授权）；测试可用 XINJI_LARK_AS=bot；
- 内容只保存在本机 SQLite 的本次会话；撤回来源会清空派生记忆与原文。
"""
from __future__ import annotations

import json
import html
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import faults, cli_runtime

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
    return found or "lark-cli"


LARK_BIN = resolve_cli()
LARK_HOME = Path(__file__).resolve().parent.parent / ".lark-home"
LARK_REAL_CONFIG = Path.home() / ".lark-cli"
TIMEOUT = 25
MAX_CHARS = 12000


def cli_env() -> dict:
    """默认用真实 HOME（钥匙串可用）；可用 XINJI_LARK_HOME 显式覆盖。"""
    env = cli_runtime.environment()
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


def auth_status() -> dict:
    try:
        p = subprocess.run([LARK_BIN, "auth", "status"], capture_output=True, text=True, timeout=15, env=cli_env())
        if p.returncode != 0:
            return {"ok": False, "error": f"lark-cli auth status failed (exit {p.returncode})"}
        data = json.loads(p.stdout)
        if not isinstance(data, dict) or data.get("ok") is False:
            return {"ok": False, "error": "lark-cli auth status returned an error"}
        user = (data.get("identities") or {}).get("user") or {}
        return {
            "ok": True,
            "identity": data.get("identity"),
            "user_status": user.get("status"),
            "token_status": user.get("tokenStatus"),
            "expires_at": user.get("expiresAt"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:160]}


def user_ready(status: dict) -> bool:
    """A configured user is not proof that its reported token is usable."""
    user = str(status.get("user_status") or "").lower()
    token = str(status.get("token_status") or "").lower()
    return bool(status.get("ok")) and user in ("ready", "valid", "authorized") and token not in (
        "expired", "invalid", "missing", "revoked",
    )


def read_doc(url: str) -> dict:
    """读取单篇飞书文档；返回 {ok,title,text,identity} 或 {ok:false,error,hint}。"""
    if faults.active("lark_auth"):
        return {"ok": False, "error": "飞书授权已过期（演练）",
                "hint": "故障演练：/api/debug/faults 关闭 lark_auth 后重试"}
    url = (url or "").strip()
    if not url or not re.match(r"^https?://", url):
        return {"ok": False, "error": "请提供完整的飞书文档链接（https://…）"}
    identity = os.getenv("XINJI_LARK_AS", "user").strip() or "user"
    cmd = [
        LARK_BIN, "docs", "+fetch", "--api-version", "v2",
        "--as", identity, "--doc", url, "--doc-format", "markdown",
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, env=cli_env())
    except FileNotFoundError:
        return {"ok": False, "error": "未找到 lark-cli", "hint": "安装或检查 PATH"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "读取超时（25s）", "hint": "检查网络或稍后重试"}
    except Exception:
        return {"ok": False, "error": "无法启动飞书文档读取", "hint": "确认 lark-cli 可运行，再重新读取；不会自动重新授权"}

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
        return {"ok": False, "error": "文档为空或无可读文本"}
    return {
        "ok": True,
        "title": _title(content),
        "text": text,
        "length": len(text),
        "extracted_length": len(extracted),
        "truncated": len(extracted) > len(text),
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
