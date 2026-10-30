"""Notion 真实只读连接器（内部集成 token）。

用户需在 Notion 创建 internal integration，并把目标页面「连接」给该集成。
token 只在本次请求内存中使用，不写库、不写日志。
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
TIMEOUT = 10


def parse_page_id(raw: str) -> str | None:
    s = (raw or "").strip()
    m = re.search(r"([0-9a-fA-F]{32})", s.replace("-", ""))
    if m:
        h = m.group(1).lower()
        return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
    return None


def _post(path: str, token: str, body: dict) -> dict:
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Notion-Version": VERSION,
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(path: str, token: str) -> dict:
    req = urllib.request.Request(
        API + path,
        headers={"Authorization": f"Bearer {token}", "Notion-Version": VERSION},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _text(block: dict) -> str:
    t = block.get("type")
    payload = block.get(t) or {}
    rt = payload.get("rich_text") or payload.get("title") or []
    return "".join(x.get("plain_text", "") for x in rt).strip()


def _title(page: dict) -> str:
    props = page.get("properties") or {}
    for v in props.values():
        if v.get("type") == "title":
            return "".join(x.get("plain_text", "") for x in v.get("title", [])).strip()
    return "Notion 页面"


def _prop_text(prop: dict) -> str:
    t = prop.get("type")
    if t == "title":
        return "".join(x.get("plain_text", "") for x in prop.get("title", []))
    if t == "rich_text":
        return "".join(x.get("plain_text", "") for x in prop.get("rich_text", []))
    if t in ("select", "status"):
        return (prop.get(t) or {}).get("name", "")
    if t == "multi_select":
        return "、".join(x.get("name", "") for x in prop.get(t) or [])
    return ""


def _read_database(pid: str, token: str) -> dict | None:
    try:
        db = _get(f"/databases/{pid}", token)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    title = "".join(x.get("plain_text", "") for x in db.get("title", [])) or "Notion 数据库"
    rows = _post(f"/databases/{pid}/query", token, {"page_size": 20})
    items = []
    for r in rows.get("results", []):
        props = r.get("properties") or {}
        vals = [(_prop_text(v), k) for k, v in props.items() if _prop_text(v)]
        name = next((v for v, k in vals if any(p.get("type") == "title" for p in [props.get(k, {})])), "")
        if not name and vals:
            name = vals[0][0]
        status = next((v for v, k in vals if k.lower() in ("status", "状态", "stage")), "")
        items.append({"type": "row", "title": (name or "未命名条目")[:48],
                      "meta": f"Notion · {status or '数据库条目'}", "summary": " · ".join(v for v, _ in vals[:3])[:110]})
    if not items:
        return {"ok": False, "error": "数据库里没有可读条目", "hint": "先在数据库里加一行再试"}
    return _package(title, items, "数据库", "页面集合（只读）")


def _package(title: str, items: list[dict], kind: str, blurb: str) -> dict:
    titles = [i["title"] for i in items]
    facts = [f"{i['title']}：{i['summary']}" for i in items[:3]]
    inferences = [f"「{title}」里有 {len(items)} 条{kind}，前几条是：{'、'.join(titles[:3])}。",
                  "这是当前快照，不是全部事实。"]
    questions = [f"「{titles[0]}」这条，现在最想推进哪一步？"]
    insights = [
        {"type": "pattern", "title": f"{kind}主线：{titles[0][:20]}", "text": "前几条是：" + "、".join(titles[:3]) + "。"},
        {"type": "risk", "title": "列表不是优先级", "text": "条数多不等于重要；先选一条今天能动的。"},
        {"type": "opportunity", "title": "把一条改成下一步", "text": "选最卡的一条，改成可验证的小动作。"},
    ]
    return {
        "ok": True,
        "connector": {"id": "notion", "name": "Notion", "category": "工作协作", "icon": "N",
                      "blurb": blurb, "reads": [kind], "scopes": ["notion:read"], "mode": "real-readonly"},
        "title": title,
        "items": items,
        "understanding": {"facts": facts, "inferences": inferences, "questions": questions},
        "insights": insights,
        "starters": [f"「{titles[0][:16]}」先做什么？", "为什么这么判断？", "把这条变成下一步"],
        "synthetic": False,
        "source": "notion",
    }


def read(token: str, page_url: str) -> dict:
    token = (token or "").strip()
    if not token:
        return {"ok": False, "error": "缺少 Notion integration token", "hint": "在 Notion 设置 → 集成 创建内部集成并复制 token"}
    pid = parse_page_id(page_url)
    if not pid:
        return {"ok": False, "error": "无法识别 Notion 页面链接", "hint": "粘贴 https://www.notion.so/... 的完整页面链接"}
    try:
        db = _read_database(pid, token)
        if db is not None:
            return db
        page = _get(f"/pages/{pid}", token)
        title = _title(page)
        children = _get(f"/blocks/{pid}/children?page_size=50", token)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return {"ok": False, "error": "Notion 访问频率受限", "hint": "请稍后重新读取，不必重新创建集成"}
        if e.code >= 500:
            return {"ok": False, "error": "Notion 服务暂不可用", "hint": "请稍后重新读取"}
        msg = "token 无效或页面未授权" if e.code in (401, 403) else "页面不存在或当前集成无权读取" if e.code == 404 else f"Notion 返回 {e.code}"
        return {"ok": False, "error": msg,
                "hint": "确认集成已邀请到该页面：页面右上角 … → 连接 → 选择你的集成"}
    except TimeoutError:
        return {"ok": False, "error": "连接 Notion 超时", "hint": "检查网络后重新读取"}
    except Exception:
        return {"ok": False, "error": "读取 Notion 失败", "hint": "检查网络后重试"}

    items = []
    for b in children.get("results", []):
        text = _text(b)
        if text:
            items.append({"type": b.get("type", "block"), "title": text[:48],
                          "meta": f"Notion · {b.get('type','block')}", "summary": text[:110]})
    if not items:
        items = [{"type": "page", "title": title, "meta": "Notion · 页面", "summary": "页面没有可读文本块"}]

    titles = [i["title"] for i in items]
    facts = [f"{i['title']}：{i['summary']}" for i in items[:3]]
    inferences = [
        f"你的 Notion 页面「{title}」最近有 {len(items)} 个可读块，前几条围绕「{titles[0]}」。",
        "这是页面快照，可能落后于你当前的想法。",
    ]
    questions = [f"「{titles[0]}」这条，现在最想改哪一句？"]
    insights = [
        {"type": "pattern", "title": f"页面主线：{titles[0][:20]}", "text": "前三条是：" + "、".join(titles[:3]) + "。"},
        {"type": "risk", "title": "文档是快照，不是现状", "text": "读到的只是这一刻的页面，别把它当成你的全部判断。"},
        {"type": "opportunity", "title": "把一条改成下一步", "text": "选一句最卡的，改成今天能验证的小动作。"},
    ]
    return {
        "ok": True,
        "connector": {"id": "notion", "name": "Notion", "category": "工作协作", "icon": "N",
                      "blurb": "真实页面（只读）", "reads": ["页面文本块"], "scopes": ["notion:read"], "mode": "real-readonly"},
        "title": title,
        "items": items,
        "understanding": {"facts": facts, "inferences": inferences, "questions": questions},
        "insights": insights,
        "starters": [f"「{titles[0][:16]}」先做什么？", "为什么这么判断？", "把这条变成下一步"],
        "synthetic": False,
        "source": "notion",
    }
