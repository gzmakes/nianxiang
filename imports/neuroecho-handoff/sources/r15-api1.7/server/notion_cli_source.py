"""Read one explicitly chosen Notion page through the official ntn CLI.

Uses the CLI's existing login; does not inspect its credential files or launch
login. Every supported request explicitly uses GET with no stdin/body.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from . import notion_source, cli_runtime

TIMEOUT = 15
BASE = Path(__file__).resolve().parent.parent


def executable() -> str | None:
    candidates = [cli_runtime.resolve("ntn", "XINJI_NOTION_CLI"),
                  str(BASE.parent.parent / "work" / "ntn-runtime" / "node_modules" / ".bin" / "ntn")]
    return next((path for path in candidates if path and Path(path).is_file() and (os.name == "nt" or os.access(path, os.X_OK))), None)


def status() -> dict:
    # Installation does not prove authentication. Avoid background keychain/API access.
    installed = executable() is not None
    return {"installed": installed, "auth_checked": False,
            "hint": "可使用本机 Notion CLI 的既有登录，读取你指定的单页" if installed else
                    "可选安装官方 Notion CLI：npm install -g ntn，再执行 ntn login；也可继续使用集成 Token"}


class ReadError(Exception):
    def __init__(self, reason: str):
        self.reason = reason


def _reason(raw: str) -> str:
    lower = (raw or "").lower()
    if any(text in lower for text in ("rate_limit", "rate limit", "429")):
        return "rate_limit"
    if any(text in lower for text in ("unauthorized", "not logged", "not authenticated", "login", "credential", "401")):
        return "auth"
    if any(text in lower for text in ("restricted_resource", "object_not_found", "403", "404")):
        return "access"
    return "network"


def _get(path: str, query: list[str] | None = None) -> dict:
    cli = executable()
    if not cli:
        raise ReadError("missing")
    args = [cli, "api", path, "-X", "GET", "--notion-version", notion_source.VERSION, *(query or [])]
    try:
        process = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                                 text=True, timeout=TIMEOUT, cwd=BASE, env=cli_runtime.environment())
    except FileNotFoundError:
        raise ReadError("missing") from None
    except subprocess.TimeoutExpired:
        raise ReadError("timeout") from None
    except Exception:
        raise ReadError("network") from None
    if process.returncode:
        raise ReadError(_reason(process.stderr or process.stdout))
    try:
        value = json.loads(process.stdout)
    except (ValueError, TypeError):
        raise ReadError("format") from None
    if not isinstance(value, dict):
        raise ReadError("format")
    if value.get("object") == "error":
        raise ReadError(_reason(str(value.get("code", "")) + " " + str(value.get("status", ""))))
    return value


def read(page_url: str) -> dict:
    page_id = notion_source.parse_page_id(page_url)
    if not page_id:
        return {"ok": False, "error": "无法识别 Notion 页面链接", "hint": "粘贴你想读取的单个 Notion 页面完整链接"}
    try:
        page = _get(f"v1/pages/{page_id}")
        children = _get(f"v1/blocks/{page_id}/children", ["page_size==50"])
    except ReadError as error:
        messages = {
            "missing": ("尚未安装 Notion CLI", "安装官方 ntn 并登录，或切换到集成 Token 方式"),
            "auth": ("Notion CLI 尚未登录或登录已失效", "在终端执行 ntn login，完成官方授权后重新读取"),
            "access": ("Notion CLI 无权读取该页面或页面不存在", "核对当前登录的工作区与该页面访问权；CLI 方式目前只支持单个页面"),
            "timeout": ("Notion CLI 读取超时", "检查网络后重试，不必重新创建集成"),
            "rate_limit": ("Notion 访问频率受限", "请稍后重新读取"),
            "format": ("Notion CLI 返回格式无法识别", "确认安装的是官方 ntn，或切换到集成 Token 方式"),
            "network": ("Notion CLI 暂时无法读取", "检查网络与 ntn --version 后重新读取"),
        }
        message, hint = messages.get(error.reason, messages["network"])
        return {"ok": False, "error": message, "hint": hint}
    title = notion_source._title(page)
    items = []
    for block in (children.get("results") or [])[:50]:
        text = notion_source._text(block)
        if text:
            items.append({"type": block.get("type", "block"), "title": text[:48],
                          "meta": f"Notion · {block.get('type', 'block')}", "summary": text[:110]})
    if not items:
        return {"ok": False, "error": "这个页面没有可读的顶层文本", "hint": "CLI 当前只读该页前 50 个顶层文本块；可换一个页面，或直接聊聊"}
    result = notion_source._package(title, items, "页面文本块", "本机 Notion CLI 单页（只读）")
    result["connector"]["reads"] = ["指定页面的前 50 个顶层文本块"]
    result["source"] = "notion-cli"
    return result
