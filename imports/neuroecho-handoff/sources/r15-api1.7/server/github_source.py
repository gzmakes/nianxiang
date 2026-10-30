"""GitHub CLI 真实只读连接器（需要 gh auth login）。"""
from __future__ import annotations

import json
import shutil
import subprocess

GH = shutil.which("gh") or "/opt/homebrew/bin/gh"
TIMEOUT = 12


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([GH, *args], capture_output=True, text=True, timeout=TIMEOUT)


def status() -> dict:
    try:
        p = _run(["auth", "status", "--hostname", "github.com"])
        if p.returncode == 0:
            return {"ok": True, "status": "ready", "hint": "GitHub CLI 已登录"}
        return {"ok": False, **_failure(p.stderr or p.stdout)}
    except FileNotFoundError:
        return {"ok": False, "status": "needs_install", "hint": "先安装 GitHub CLI（gh），再执行 gh auth login -h github.com"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "unavailable", "hint": "GitHub 登录检查超时，请检查网络后重试"}
    except Exception:
        return {"ok": False, "status": "unavailable", "hint": "无法检查 GitHub CLI，请确认 gh 可运行后重试"}


def _failure(raw: str) -> dict:
    """Classify locally, never expose CLI output that may contain account details."""
    lower = (raw or "").lower()
    if any(x in lower for x in ("rate limit", "secondary rate")):
        return {"status": "unavailable", "hint": "GitHub 访问频率受限，请稍后重试"}
    if any(x in lower for x in ("could not resolve", "connection", "timeout", "timed out", "tls handshake", "error connecting")):
        return {"status": "unavailable", "hint": "暂时无法连接 GitHub，请检查网络后重试，无需重新授权"}
    if any(x in lower for x in ("insufficient", "resource not accessible", "missing required scope", "scope")):
        return {"status": "needs_auth", "hint": "GitHub 当前授权缺少读取范围，请先核对 gh auth status；本产品不会自动扩大权限"}
    return {"status": "needs_auth", "hint": "GitHub 未登录或授权已失效；终端执行 gh auth login -h github.com 后回来重试"}


def read(limit: int = 5) -> dict:
    try:
        p = _run(["search", "prs", "--author", "@me", "--limit", str(limit), "--sort", "updated", "--order", "desc",
                  "--json", "title,repository,state,updatedAt,url"])
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "GitHub 查询超时", "hint": "检查网络后重试"}
    except FileNotFoundError:
        return {"ok": False, "error": "尚未安装 GitHub CLI", "hint": "先安装 GitHub CLI（gh），再执行 gh auth login -h github.com"}
    except Exception:
        return {"ok": False, "error": "无法调用 GitHub CLI", "hint": "先在终端确认 gh --version 可运行"}
    if p.returncode != 0:
        return {"ok": False, "error": "GitHub PR 查询失败", **_failure(p.stderr or p.stdout)}
    try:
        rows = json.loads(p.stdout or "[]")
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise ValueError("invalid result shape")
    except Exception:
        return {"ok": False, "error": "gh 返回无法解析", "hint": "先在终端试 gh search prs --author @me --limit 1"}
    items = []
    for r in rows:
        repo = (r.get("repository") or {}).get("nameWithOwner") or (r.get("repository") or {}).get("name") or "repo"
        items.append({"type": "pr", "title": (r.get("title") or "未命名 PR")[:80],
                      "meta": f"{repo} · {r.get('state','')}", "summary": f"{r.get('updatedAt','')[:10]} · {r.get('url','')}"})
    if not items:
        return {"ok": False, "error": "没有找到你创建的 PR", "hint": "可先用其他来源开始对话"}
    titles = [i["title"] for i in items]
    insights = [
        {"type": "pattern", "title": "最近在推进这些 PR", "text": "、".join(titles[:3]) + "。"},
        {"type": "risk", "title": "PR 不等于优先级", "text": "开着不代表现在必须推。"},
        {"type": "opportunity", "title": "选一个推进到可评审", "text": "把最早卡住的那个变小。"},
    ]
    return {
        "ok": True,
        "connector": {"id": "github", "name": "GitHub", "category": "开发", "icon": "gh",
                      "blurb": "我的 PR（只读）", "reads": ["最近 PR"], "scopes": ["gh:pr-read"], "mode": "real"},
        "title": "GitHub PR",
        "items": items,
        "understanding": {"facts": [f"{i['title']}（{i['meta']}）" for i in items[:3]],
                          "inferences": ["这些是你 gh 账号能看到的真实 PR。"],
                          "questions": [f"「{titles[0][:20]}」需要先推进吗？"]},
        "insights": insights,
        "starters": [f"「{titles[0][:18]}」先推到哪一步？", "为什么？", "变成下一步"],
        "synthetic": False,
        "source": "github",
    }
