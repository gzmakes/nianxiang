"""本地 Git 代码库真实只读连接器。"""
from __future__ import annotations

import subprocess
import os
from pathlib import Path

from . import cli_runtime

BASE = Path(__file__).resolve().parent.parent
TIMEOUT = 8


def repos() -> list[Path]:
    found = []
    for candidate in [BASE, BASE.parent]:
        if (candidate / ".git").exists():
            found.append(candidate)
        if candidate.is_dir():
            for child in candidate.iterdir():
                if child.is_dir() and (child / ".git").exists():
                    found.append(child)
    return sorted(set(found))[:5]


def _run(cmd: list[str]) -> str:
    env = {key: value for key, value in cli_runtime.environment().items()
           if key not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                          "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_COUNT"}
           and not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})
    p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT, env=env)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "git failed").strip()[:160])
    return p.stdout


def read(limit: int = 8, path: str | Path | None = None) -> dict:
    limit = max(1, min(int(limit), 8))
    selected = None
    if path is not None:
        raw = str(path).strip()
        if not raw or "\x00" in raw:
            return {"ok": False, "error": "请填写代码库目录", "hint": "例如 Windows 的 C:\\Users\\你的用户名\\Projects\\my-project，或 macOS 的 ~/Projects/my-project；仅读取该库最近最多 8 条提交"}
        try:
            candidate = Path(raw).expanduser()
        except (OSError, RuntimeError):
            return {"ok": False, "error": "无法识别这个用户目录", "hint": "请使用 Windows 或 macOS 的完整目录路径"}
        if not candidate.is_absolute():
            return {"ok": False, "error": "请填写完整目录路径", "hint": "使用完整目录路径，不要输入终端命令"}
        try:
            selected = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            return {"ok": False, "error": "这个目录不存在或无法访问", "hint": "在文件管理器中找到代码库，复制其完整路径后重试"}
        if not selected.is_dir():
            return {"ok": False, "error": "请选择目录，不是文件", "hint": "填写包含 Git 工作树的代码库目录"}
        try:
            if _run(["git", "-C", str(selected), "rev-parse", "--is-inside-work-tree"]).strip() != "true":
                return {"ok": False, "error": "这个目录不是 Git 工作树", "hint": "请选择平时编辑代码的仓库目录；不支持 bare 仓库"}
            selected = Path(_run(["git", "-C", str(selected), "rev-parse", "--show-toplevel"]).strip()).resolve(strict=True)
        except FileNotFoundError:
            return {"ok": False, "error": "尚未安装 Git", "hint": "先在终端确认 git --version 可运行，再重新读取"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "检查代码库超时", "hint": "检查该目录是否仍可访问后重试"}
        except Exception:
            return {"ok": False, "error": "这个目录不是可读取的 Git 工作树", "hint": "确认目录是已克隆且属于你的仓库；请勿输入命令或 .git 内部目录"}
    items = []
    for repo in ([selected] if selected is not None else repos()):
        try:
            out = _run(["git", "--no-pager", "-C", str(repo), "log", f"-{limit}", "--pretty=format:%h|%s|%ar"])
        except subprocess.TimeoutExpired:
            if selected is not None:
                return {"ok": False, "error": "读取代码库提交超时", "hint": "检查本地磁盘或仓库访问状态后重试"}
            continue
        except Exception:
            if selected is not None:
                return {"ok": False, "error": "这个代码库还没有可读提交", "hint": "确认至少已有一次提交，或换一个代码库；不会创建提交或修改文件"}
            continue
        for line in out.splitlines():
            parts = line.split("|")
            if len(parts) < 3:
                continue
            h, subject, when = parts[0], "|".join(parts[1:-1]), parts[-1]
            items.append({"type": "commit", "title": subject[:70],
                          "meta": f"{repo.name} · {h} · {when}", "summary": f"{repo.name} 的最近提交：{subject}"})
    items = items[:limit]
    if not items:
        return {"ok": False, "error": "没有找到可读的 Git 仓库",
                "hint": "填写一个已有提交的代码库完整目录后重试"}
    titles = [i["title"] for i in items]
    facts = [f"{i['title']}（{i['meta']}）" for i in items[:3]]
    inferences = [f"你最近在 {len({i['meta'].split(' · ')[0] for i in items})} 个仓库里有提交。",
                  "提交信息是真实记录，但不能代表全部工作。"]
    questions = [f"「{titles[0]}」这条，是当前最该继续的吗？"]
    insights = [
        {"type": "pattern", "title": "最近在动这些代码", "text": "最近提交：" + "、".join(titles[:3]) + "。"},
        {"type": "risk", "title": "提交≠优先级", "text": "动过的代码不一定是现在最重要的事。"},
        {"type": "opportunity", "title": "从一条提交接回上下文", "text": "选最近一条，看看下一步该改哪里。"},
    ]
    return {
        "ok": True,
        "connector": {"id": "git", "name": "本地代码库", "category": "开发", "icon": "git",
                      "blurb": "最近提交（只读）", "reads": ["最近提交"], "scopes": ["git:log"], "mode": "real"},
        "title": "本地代码库",
        "selected_path": str(selected) if selected is not None else None,
        "items": items,
        "understanding": {"facts": facts, "inferences": inferences, "questions": questions},
        "insights": insights,
        "starters": [f"「{titles[0][:18]}」接下来做什么？", "为什么这么判断？", "变成下一步"],
        "synthetic": False,
        "source": "git",
    }
