"""Google Workspace CLI: read five unread INBOX headers, never bodies."""
import json
import subprocess

from . import cli_runtime, gmail_source

SCOPE = "https://www.googleapis.com/auth/gmail.metadata"


def executable():
    return cli_runtime.resolve("gws", "XINJI_GWS_CLI")


def _get(resource, params):
    cli = executable()
    if not cli:
        raise FileNotFoundError()
    result = subprocess.run([*cli_runtime.command_for_path(cli), "gmail", "users", "messages", resource,
                             "--params", json.dumps(params)],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True,
                            timeout=20, env=cli_runtime.environment())
    if result.returncode:
        raise RuntimeError()
    data = json.loads(result.stdout)
    if not isinstance(data, dict) or data.get("error"):
        raise RuntimeError()
    return data


def read():
    try:
        listing = _get("list", {"userId": "me", "labelIds": ["INBOX", "UNREAD"], "maxResults": 5})
        messages = listing.get("messages", [])
        if not isinstance(messages, list):
            raise ValueError()
        items = []
        for message in messages[:5]:
            data = _get("get", {"userId": "me", "id": message["id"], "format": "metadata",
                                "metadataHeaders": ["Subject", "From", "Date"]})
            headers = {h["name"].lower(): gmail_source._dec(h.get("value", ""))
                       for h in data.get("payload", {}).get("headers", [])}
            items.append({"type": "email", "title": headers.get("subject", "（无主题）")[:60],
                          "meta": "Gmail · " + headers.get("from", "")[:60],
                          "summary": headers.get("date", "")[:40] + " · 未读"})
        if not items:
            return {"ok": False, "error": "收件箱没有未读邮件", "hint": "已连接，但本次没有可接入的未读邮件头。"}
        result = gmail_source.package(items)
        result["source"] = "gmail-cli"
        return result
    except FileNotFoundError:
        return {"ok": False, "error": "Gmail 连接组件尚未安装", "hint": "请安装 Google Workspace CLI（gws），再从网页连接 Google。"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Gmail 读取超时", "hint": "检查网络后重试。"}
    except Exception:
        return {"ok": False, "error": "Gmail CLI 读取失败", "hint": "点击连接 Google 重新核对授权；若仍失败，检查 Gmail API 和 Google 应用配置。"}
