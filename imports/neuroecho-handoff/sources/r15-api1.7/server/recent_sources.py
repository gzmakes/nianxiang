"""Bounded real recent activity for an account's connection conversation.

No persistent index or login is created. The private _access value is a live
revocation guard for the calling job; it must not be serialized or stored.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import feishu_account


def read_feishu(*, get_current, now: datetime | None = None) -> dict:
    until = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    if until.tzinfo is None:
        raise ValueError("recent activity requires a timezone-aware clock")
    until = until.astimezone(timezone.utc)
    since = until - timedelta(days=7)
    scope = {"kind": "last_7_days", "since": since.isoformat(timespec="seconds"),
             "until": until.isoformat(timespec="seconds"),
             "label": "最近 7 天你编辑或打开过的飞书文档（有限读取）"}
    access = feishu_account.RecentAccess(get_current)
    found = access.recent(since, until)
    base = {"source": "feishu", "scope": scope, "_access": access}
    if not found.get("ok"):
        return {**base, **found}
    items, paragraphs, citations, failures = [], [], [], 0
    for row in found["items"][:feishu_account.MAX_READS]:
        result = access.read(row["url"])
        if not result.get("ok"):
            if not access.is_current():
                return {**base, "ok": False, "error_code": "connection_changed",
                        "error": "连接已断开或发生变化，这次读取已停止。"}
            failures += 1
            items.append({**row, "read_ok": False})
            continue
        item = {**row, "title": result["title"], "text": result["text"],
                "read_ok": True, "truncated": result["truncated"]}
        items.append(item)
        activity = "、".join("编辑过" if value == "edited" else "打开过" for value in row["matched_by"])
        paragraphs.append(f"文档：{item['title']}\n最近活动：{activity}；文档更新/最近打开匹配时间 {row['matched_at']}\n"
                          f"链接：{row['url']}\n正文节选：\n{result['text']}")
        citations.append({"kind": "feishu_document", "title": item["title"],
                          "url": row["url"], "text": item["title"]})
    if not access.is_current():
        return {**base, "ok": False, "error_code": "connection_changed",
                "error": "连接已断开或发生变化，这次读取已停止。"}
    if found["items"] and not citations:
        return {**base, "ok": False, "error_code": "recent_read_failed",
                "error": "找到了近期飞书文档，但正文暂时读取失败，尚未生成内容洞察。",
                "items": items, "text": "", "citations": [], "empty": False,
                "read_failures": failures, "matched_count": len(found["items"]), "read_count": 0,
                "has_more": found["has_more"], "limited": True}
    return {**base, "ok": True, "items": items, "text": "\n\n".join(paragraphs), "citations": citations,
            "empty": not found["items"], "read_failures": failures,
            "matched_count": len(found["items"]), "read_count": len(citations),
            "has_more": found["has_more"], "limited": True,
            "notice": "最多查询各 8 份近期编辑、打开的文档，合并后读取最新 3 篇节选；编辑筛选使用窗口内整点以避开小时聚合越界，不代表全部飞书内容。"}
