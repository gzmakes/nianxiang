"""标准库降级服务器：无 FastAPI 依赖时提供等价核心 API + 静态页面。

运行：
    python3 server/fallback.py  # http://127.0.0.1:8787
"""
from __future__ import annotations

import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server import apple_source, connectors, core, device_bridge, faults, gmail_source, lark, lark_auth, local_source, model, model_settings, notion_source, plugin_bridge, real_sources, prompts, system_source  # noqa: E402

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


def _read_connector(connector_id: str) -> dict:
    if connector_id in ("apple_reminders", "apple_calendar"):
        out = apple_source.read_reminders() if connector_id == "apple_reminders" else apple_source.read_calendar()
        if out.get("ok"):
            return out
        return out
    if connector_id in ("windows_reminders", "windows_calendar"):
        out = (system_source.read_reminders() if connector_id == "windows_reminders"
               else system_source.read_calendar())
        if out.get("ok"):
            return out
        return out
    if connector_id == "local_files":
        out = local_source.read()
        if out.get("ok"):
            return out
        demo = connectors.read(connector_id)
        demo["fallback_reason"] = out.get("error")
        return demo
    return connectors.read(connector_id)
PORT = int(os.getenv("PORT", "8787"))


class Handler(BaseHTTPRequestHandler):
    server_version = "XinjiFallback/0.1"

    def log_message(self, fmt, *args):  # quiet
        pass

    # ---------- utils ----------
    def _send(self, code: int, payload=None, ctype="application/json; charset=utf-8"):
        body = b""
        if payload is not None:
            body = (json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list))
                    else str(payload)).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def _static(self, path: str):
        rel = path.lstrip("/")
        if rel.startswith("static/"):
            rel = rel[len("static/"):]
        rel = rel or "index.html"
        if rel == "m":
            rel = "m.html"
        full = os.path.normpath(os.path.join(WEB, rel))
        if not full.startswith(WEB) or not os.path.isfile(full):
            return self._send(404, {"error": "not found"})
        ctype = "text/html; charset=utf-8"
        if full.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        elif full.endswith(".js"):
            ctype = "text/javascript; charset=utf-8"
        elif full.endswith(".svg"):
            ctype = "image/svg+xml"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---------- verbs ----------
    def do_OPTIONS(self):  # noqa: N802
        self._send(204, None)

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        if p == "/api/config":
            return self._send(200, {"model": model.status(), "synthetic": True, "budget": core.CHAT_BUDGET})
        if p == "/api/carryover/import":
            return self._send(200, core.import_carryover(b.get("session_id", ""), b.get("ids") or []))
        if p == "/api/lark/docs":
            return self._send(200, lark.search_docs((q.get("q") or [""])[0]))
        if p == "/api/plugins":
            return self._send(200, {"meme": plugin_bridge.memes(), "pet": plugin_bridge.pet()})
        if p.startswith("/plugin-memes/"):
            parts = p.strip("/").split("/")
            if len(parts) == 4:
                f = plugin_bridge.meme_file(parts[1], parts[2], parts[3])
                if f:
                    data = f.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
            return self._send(404, {"error": "meme not found"})
        if p == "/api/auth/lark/setup":
            return self._send(200, lark_auth.setup_keychain())
        if p == "/api/auth/lark/start":
            return self._send(200, lark_auth.start())
        if p == "/api/auth/lark/status":
            return self._send(200, lark_auth.status())
        if p == "/api/onboarding/sources":
            return self._send(200, {"sources": real_sources.sources()})
        if p == "/api/onboarding/real/read":
            return self._send(200, real_sources.read((b.get("source_id") or "").strip()))
        if p == "/api/onboarding/real/start":
            read = real_sources.read((b.get("source_id") or "").strip())
            if not read.get("ok"):
                return self._send(400, {"error": read.get("error", "读取失败")})
            c = read["connector"]
            data = core.create_session("connector", "\n".join(read["understanding"]["facts"]),
                                       source_label=f"{c['name']} · 已连接",
                                       understanding=read["understanding"],
                                       greeting=f"我看过你的{c['name']}（真实只读）。有件事想先和你确认：{read['insights'][0]['title']}。")
            sid = data["session"]["id"]
            for ins in read["insights"]:
                core.add_memory(sid, "inference", f"洞察（{ins['type']}）：{ins['title']}——{ins['text']}", source=f"{c['name']} · 真实只读")
            core.set_session_context(sid, c["id"], read["items"], read["insights"], read.get("starters"))
            core.audit(sid, "real.read", f"{len(read['items'])} 条 · {c['id']}", "用户确认读取真实来源")
            data["memories"] = core.list_memories(sid)
            data["insights"] = read["insights"]
            data["connector"] = c
            data["context"] = core.get_session_context(sid)
            return self._send(200, data)
        if p == "/api/gmail/preview":
            return self._send(200, gmail_source.read(b.get("address") or "", b.get("password") or ""))
        if p == "/api/gmail/start":
            out = gmail_source.read(b.get("address") or "", b.get("password") or "")
            if not out.get("ok"):
                return self._send(400, {"error": out.get("error", "读取失败")})
            data = core.create_session("connector", "\n".join(out["understanding"]["facts"]),
                                       source_label="Gmail · 已连接",
                                       understanding=out["understanding"],
                                       greeting=f"我看过你的 Gmail 未读（只读）。有件事想先和你确认：{out['insights'][0]['title']}。")
            sid = data["session"]["id"]
            for ins in out["insights"]:
                core.add_memory(sid, "inference", f"洞察（{ins['type']}）：{ins['title']}——{ins['text']}", source="Gmail · 只读")
            core.set_session_context(sid, "gmail", out["items"], out["insights"], out.get("starters"))
            core.audit(sid, "gmail.read", f"{len(out['items'])} 封未读", "用户确认读取 Gmail 未读头")
            data["memories"] = core.list_memories(sid)
            data["insights"] = out["insights"]
            data["connector"] = out["connector"]
            data["context"] = core.get_session_context(sid)
            return self._send(200, data)
        if p == "/api/notion/preview":
            return self._send(200, notion_source.read((b.get("token") or "").strip(), b.get("url") or ""))
        if p == "/api/notion/start":
            out = notion_source.read((b.get("token") or "").strip(), b.get("url") or "")
            if not out.get("ok"):
                return self._send(400, {"error": out.get("error", "读取失败")})
            title = out["title"]
            data = core.create_session("connector", "\n".join(out["understanding"]["facts"]),
                                       source_label="Notion · 已连接",
                                       understanding=out["understanding"],
                                       greeting=f"我看过你的 Notion 页面「{title}」（只读）。有件事想先和你确认：{out['insights'][0]['title']}。")
            sid = data["session"]["id"]
            for ins in out["insights"]:
                core.add_memory(sid, "inference", f"洞察（{ins['type']}）：{ins['title']}——{ins['text']}", source="Notion · 只读")
            core.set_session_context(sid, "notion", out["items"], out["insights"], out.get("starters"))
            core.audit(sid, "notion.read", f"{len(out['items'])} 条 · {title[:30]}", "用户确认读取 Notion 页面")
            data["memories"] = core.list_memories(sid)
            data["insights"] = out["insights"]
            data["connector"] = out["connector"]
            data["context"] = core.get_session_context(sid)
            return self._send(200, data)
        if p == "/api/carryover":
            return self._send(200, {"memories": core.carryover_memories((q.get("session_id") or [""])[0])})
        if p == "/api/settings/model":
            return self._send(200, model_settings.redacted())
        if p == "/api/debug/faults":
            return self._send(200, faults.get_faults())
        if p == "/api/onboarding/catalog":
            return self._send(200, connectors.catalog())
        if p == "/api/lark/status":
            return self._send(200, lark.auth_status())
        if p == "/api/health":
            return self._send(200, {"ok": True, "mode": "fallback", "synthetic": True, "version": "0.1.0"})
        if p == "/api/next-step":
            sid = (q.get("session_id") or [""])[0]
            return self._send(200, core.suggest_next_step(sid))
        if p == "/api/device/presentation":
            return self._send(200, device_bridge.state())
        if p == "/api/device/frame":
            return self._send(200, core.device_frame())
        if p == "/api/actions":
            return self._send(200, {"actions": core.list_actions((q.get("session_id") or [None])[0])})
        if p == "/api/metrics":
            return self._send(200, core.metrics((q.get("session_id") or [None])[0]))
        if p == "/api/audit":
            return self._send(200, {"events": core.audit_list((q.get("session_id") or [None])[0])})
        m = re.fullmatch(r"/api/memory/([\w-]+)/history", p)
        if m:
            return self._send(200, {"revisions": core.memory_history(m.group(1))})
        if p == "/api/memory":
            sid = (q.get("session_id") or [""])[0]
            return self._send(200, {"memories": core.list_memories(sid)})
        if p == "/api/bookmark/latest":
            sid = (q.get("session_id") or [""])[0]
            return self._send(200, {"bookmark": core.latest_bookmark(sid)})
        if p == "/api/export":
            return self._send(200, core.export_data((q.get("session_id") or [None])[0]))
        m = re.fullmatch(r"/api/session/([\w-]+)", p)
        if m:
            sid = m.group(1)
            sess = core.get_session(sid)
            if not sess:
                return self._send(404, {"error": "session not found"})
            return self._send(200, {"session": sess, "messages": core.get_messages(sid),
                                    "memories": core.list_memories(sid), "bookmark": core.latest_bookmark(sid),
                                    "context": core.get_session_context(sid)})
        return self._static(p)

    def do_POST(self):  # noqa: N802
        p = urlparse(self.path).path
        b = self._body()
        m = re.fullmatch(r"/api/session/([\w-]+)/delivery/stop", p)
        if m:
            message_id = b.get('message_id') if isinstance(b, dict) else None
            if message_id is not None and (not isinstance(message_id, str) or not 0 < len(message_id) <= 128):
                return self._send(422, {'error': 'invalid message_id'})
            result = core.stop_message_delivery(m.group(1), message_id)
            return self._send(200, result) if result is not None else self._send(404, {"error": "session not found"})
        if p == "/api/carryover/import":
            return self._send(200, core.import_carryover(b.get("session_id", ""), b.get("ids") or []))
        if p == "/api/lark/docs":
            return self._send(200, lark.search_docs((q.get("q") or [""])[0]))
        if p == "/api/plugins":
            return self._send(200, {"meme": plugin_bridge.memes(), "pet": plugin_bridge.pet()})
        if p.startswith("/plugin-memes/"):
            parts = p.strip("/").split("/")
            if len(parts) == 4:
                f = plugin_bridge.meme_file(parts[1], parts[2], parts[3])
                if f:
                    data = f.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
            return self._send(404, {"error": "meme not found"})
        if p == "/api/auth/lark/setup":
            return self._send(200, lark_auth.setup_keychain())
        if p == "/api/auth/lark/start":
            return self._send(200, lark_auth.start())
        if p == "/api/auth/lark/status":
            return self._send(200, lark_auth.status())
        if p == "/api/onboarding/sources":
            return self._send(200, {"sources": real_sources.sources()})
        if p == "/api/onboarding/real/read":
            return self._send(200, real_sources.read((b.get("source_id") or "").strip()))
        if p == "/api/onboarding/real/start":
            read = real_sources.read((b.get("source_id") or "").strip())
            if not read.get("ok"):
                return self._send(400, {"error": read.get("error", "读取失败")})
            c = read["connector"]
            data = core.create_session("connector", "\n".join(read["understanding"]["facts"]),
                                       source_label=f"{c['name']} · 已连接",
                                       understanding=read["understanding"],
                                       greeting=f"我看过你的{c['name']}（真实只读）。有件事想先和你确认：{read['insights'][0]['title']}。")
            sid = data["session"]["id"]
            for ins in read["insights"]:
                core.add_memory(sid, "inference", f"洞察（{ins['type']}）：{ins['title']}——{ins['text']}", source=f"{c['name']} · 真实只读")
            core.set_session_context(sid, c["id"], read["items"], read["insights"], read.get("starters"))
            core.audit(sid, "real.read", f"{len(read['items'])} 条 · {c['id']}", "用户确认读取真实来源")
            data["memories"] = core.list_memories(sid)
            data["insights"] = read["insights"]
            data["connector"] = c
            data["context"] = core.get_session_context(sid)
            return self._send(200, data)
        if p == "/api/gmail/preview":
            return self._send(200, gmail_source.read(b.get("address") or "", b.get("password") or ""))
        if p == "/api/gmail/start":
            out = gmail_source.read(b.get("address") or "", b.get("password") or "")
            if not out.get("ok"):
                return self._send(400, {"error": out.get("error", "读取失败")})
            data = core.create_session("connector", "\n".join(out["understanding"]["facts"]),
                                       source_label="Gmail · 已连接",
                                       understanding=out["understanding"],
                                       greeting=f"我看过你的 Gmail 未读（只读）。有件事想先和你确认：{out['insights'][0]['title']}。")
            sid = data["session"]["id"]
            for ins in out["insights"]:
                core.add_memory(sid, "inference", f"洞察（{ins['type']}）：{ins['title']}——{ins['text']}", source="Gmail · 只读")
            core.set_session_context(sid, "gmail", out["items"], out["insights"], out.get("starters"))
            core.audit(sid, "gmail.read", f"{len(out['items'])} 封未读", "用户确认读取 Gmail 未读头")
            data["memories"] = core.list_memories(sid)
            data["insights"] = out["insights"]
            data["connector"] = out["connector"]
            data["context"] = core.get_session_context(sid)
            return self._send(200, data)
        if p == "/api/notion/preview":
            return self._send(200, notion_source.read((b.get("token") or "").strip(), b.get("url") or ""))
        if p == "/api/notion/start":
            out = notion_source.read((b.get("token") or "").strip(), b.get("url") or "")
            if not out.get("ok"):
                return self._send(400, {"error": out.get("error", "读取失败")})
            title = out["title"]
            data = core.create_session("connector", "\n".join(out["understanding"]["facts"]),
                                       source_label="Notion · 已连接",
                                       understanding=out["understanding"],
                                       greeting=f"我看过你的 Notion 页面「{title}」（只读）。有件事想先和你确认：{out['insights'][0]['title']}。")
            sid = data["session"]["id"]
            for ins in out["insights"]:
                core.add_memory(sid, "inference", f"洞察（{ins['type']}）：{ins['title']}——{ins['text']}", source="Notion · 只读")
            core.set_session_context(sid, "notion", out["items"], out["insights"], out.get("starters"))
            core.audit(sid, "notion.read", f"{len(out['items'])} 条 · {title[:30]}", "用户确认读取 Notion 页面")
            data["memories"] = core.list_memories(sid)
            data["insights"] = out["insights"]
            data["connector"] = out["connector"]
            data["context"] = core.get_session_context(sid)
            return self._send(200, data)
        if p == "/api/carryover":
            return self._send(200, {"memories": core.carryover_memories((q.get("session_id") or [""])[0])})
        if p == "/api/settings/model":
            return self._send(200, model_settings.redacted())
        if p == "/api/debug/faults":
            try:
                return self._send(200, faults.set_faults(b.get("kind", ""), b.get("enabled", True)))
            except ValueError as e:
                return self._send(400, {"error": str(e)})
        if p == "/api/debug/faults/clear":
            return self._send(200, faults.clear())
        if p == "/api/carryover/import":
            return self._send(200, core.import_carryover(b.get("session_id", ""), b.get("ids") or []))
        if p == "/api/lark/docs":
            return self._send(200, lark.search_docs((q.get("q") or [""])[0]))
        if p == "/api/plugins":
            return self._send(200, {"meme": plugin_bridge.memes(), "pet": plugin_bridge.pet()})
        if p.startswith("/plugin-memes/"):
            parts = p.strip("/").split("/")
            if len(parts) == 4:
                f = plugin_bridge.meme_file(parts[1], parts[2], parts[3])
                if f:
                    data = f.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
            return self._send(404, {"error": "meme not found"})
        if p == "/api/auth/lark/setup":
            return self._send(200, lark_auth.setup_keychain())
        if p == "/api/auth/lark/start":
            return self._send(200, lark_auth.start())
        if p == "/api/auth/lark/status":
            return self._send(200, lark_auth.status())
        if p == "/api/onboarding/sources":
            return self._send(200, {"sources": real_sources.sources()})
        if p == "/api/onboarding/real/read":
            return self._send(200, real_sources.read((b.get("source_id") or "").strip()))
        if p == "/api/onboarding/real/start":
            read = real_sources.read((b.get("source_id") or "").strip())
            if not read.get("ok"):
                return self._send(400, {"error": read.get("error", "读取失败")})
            c = read["connector"]
            data = core.create_session("connector", "\n".join(read["understanding"]["facts"]),
                                       source_label=f"{c['name']} · 已连接",
                                       understanding=read["understanding"],
                                       greeting=f"我看过你的{c['name']}（真实只读）。有件事想先和你确认：{read['insights'][0]['title']}。")
            sid = data["session"]["id"]
            for ins in read["insights"]:
                core.add_memory(sid, "inference", f"洞察（{ins['type']}）：{ins['title']}——{ins['text']}", source=f"{c['name']} · 真实只读")
            core.set_session_context(sid, c["id"], read["items"], read["insights"], read.get("starters"))
            core.audit(sid, "real.read", f"{len(read['items'])} 条 · {c['id']}", "用户确认读取真实来源")
            data["memories"] = core.list_memories(sid)
            data["insights"] = read["insights"]
            data["connector"] = c
            data["context"] = core.get_session_context(sid)
            return self._send(200, data)
        if p == "/api/gmail/preview":
            return self._send(200, gmail_source.read(b.get("address") or "", b.get("password") or ""))
        if p == "/api/gmail/start":
            out = gmail_source.read(b.get("address") or "", b.get("password") or "")
            if not out.get("ok"):
                return self._send(400, {"error": out.get("error", "读取失败")})
            data = core.create_session("connector", "\n".join(out["understanding"]["facts"]),
                                       source_label="Gmail · 已连接",
                                       understanding=out["understanding"],
                                       greeting=f"我看过你的 Gmail 未读（只读）。有件事想先和你确认：{out['insights'][0]['title']}。")
            sid = data["session"]["id"]
            for ins in out["insights"]:
                core.add_memory(sid, "inference", f"洞察（{ins['type']}）：{ins['title']}——{ins['text']}", source="Gmail · 只读")
            core.set_session_context(sid, "gmail", out["items"], out["insights"], out.get("starters"))
            core.audit(sid, "gmail.read", f"{len(out['items'])} 封未读", "用户确认读取 Gmail 未读头")
            data["memories"] = core.list_memories(sid)
            data["insights"] = out["insights"]
            data["connector"] = out["connector"]
            data["context"] = core.get_session_context(sid)
            return self._send(200, data)
        if p == "/api/notion/preview":
            return self._send(200, notion_source.read((b.get("token") or "").strip(), b.get("url") or ""))
        if p == "/api/notion/start":
            out = notion_source.read((b.get("token") or "").strip(), b.get("url") or "")
            if not out.get("ok"):
                return self._send(400, {"error": out.get("error", "读取失败")})
            title = out["title"]
            data = core.create_session("connector", "\n".join(out["understanding"]["facts"]),
                                       source_label="Notion · 已连接",
                                       understanding=out["understanding"],
                                       greeting=f"我看过你的 Notion 页面「{title}」（只读）。有件事想先和你确认：{out['insights'][0]['title']}。")
            sid = data["session"]["id"]
            for ins in out["insights"]:
                core.add_memory(sid, "inference", f"洞察（{ins['type']}）：{ins['title']}——{ins['text']}", source="Notion · 只读")
            core.set_session_context(sid, "notion", out["items"], out["insights"], out.get("starters"))
            core.audit(sid, "notion.read", f"{len(out['items'])} 条 · {title[:30]}", "用户确认读取 Notion 页面")
            data["memories"] = core.list_memories(sid)
            data["insights"] = out["insights"]
            data["connector"] = out["connector"]
            data["context"] = core.get_session_context(sid)
            return self._send(200, data)
        if p == "/api/carryover":
            return self._send(200, {"memories": core.carryover_memories((q.get("session_id") or [""])[0])})
        if p == "/api/settings/model":
            if not (b.get("base_url") or "").strip() or not (b.get("model") or "").strip():
                return self._send(400, {"error": "base_url 与 model 必填"})
            key = (b.get("api_key") or "").strip() or model_settings.load().get("api_key", "")
            out = model_settings.save(b["base_url"], key, b["model"], b.get("timeout", 8))
            core.audit(None, "settings.model", f"model={out['model']}", "用户配置模型")
            return self._send(200, out)
        if p == "/api/settings/model/test":
            return self._send(200, model.test_connection())
        if p == "/api/settings/model/clear":
            return self._send(200, model_settings.clear())
        if p == "/api/onboarding/recommend":
            return self._send(200, {"scenario": b.get("scenario"), "items": connectors.recommend(b.get("scenario", ""))})
        if p == "/api/onboarding/read":
            return self._send(200, _read_connector(b.get("connector_id", "")))
        if p == "/api/onboarding/start":
            read = _read_connector(b.get("connector_id", ""))
            if not read.get("ok"):
                return self._send(400, {"error": read.get("error")})
            c = read["connector"]
            data = core.create_session("connector", "\n".join(read["understanding"]["facts"]),
                                       source_label=f"{c['name']} · {mode_label}",
                                       understanding=read["understanding"],
                                       greeting=connectors.greeting(b.get("connector_id", "")))
            sid = data["session"]["id"]
            for ins in read["insights"]:
                core.add_memory(sid, "inference", f"洞察（{ins['type']}）：{ins['title']}——{ins['text']}",
                                source=f"{c['name']} · {mode_label}")
            core.set_session_context(sid, c["id"], read["items"], read["insights"], read.get("starters"))
            core.audit(sid, "connector.read", c["id"],
                       "用户确认读取本地文件" if not read.get("synthetic") else "用户确认读取演示数据")
            data["memories"] = core.list_memories(sid)
            data["insights"] = read["insights"]
            data["connector"] = c
            data["context"] = core.get_session_context(sid)
            return self._send(200, data)
        if p == "/api/lark/preview":
            out = lark.read_doc(b.get("url", ""))
            if out.get("ok"):
                out = {k: v for k, v in out.items() if k != "text"} | {"preview": out["text"][:600]}
            return self._send(200, out)
        if p == "/api/lark/start":
            out = lark.read_doc(b.get("url", ""))
            if not out.get("ok"):
                return self._send(200, out)
            data = core.create_session("paste", out["text"], source_label=f"飞书文档 · {out['title']}")
            core.audit(data["session"]["id"], "lark.read", f"identity={out['identity']} len={out['length']}", "用户选择的单篇文档")
            return self._send(200, data)
        if p in ("/download/desktop", "/download/source"):
            import glob
            prefix = "xinji-echo-desktop-*.zip" if p.endswith("desktop") else "xinji-echo-source-*.zip"
            root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dist")
            files = sorted(glob.glob(os.path.join(root, prefix)), key=os.path.getmtime, reverse=True)
            if not files:
                return self._send(404, {"error": "package not built"})
            path = files[0]
            data = open(path, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(path)}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if p == "/api/personas":
            return self._send(200, {"default_persona": "nianxiang", "personas": prompts.persona_manifest()})
        if p == "/api/sessions":
            return self._send(200, {"sessions": core.list_sessions()})
        if p == "/api/session":
            try:
                if str(b.get("interaction_mode", "companion")).strip().lower() not in prompts.INTERACTION_MODES:
                    raise ValueError("invalid interaction_mode")
                return self._send(200, core.create_session(b.get("mode", "sample"), b.get("text", ""), persona_id=b.get("persona_id", "nianxiang"), interaction_mode=b.get("interaction_mode", "companion")))
            except ValueError as e:
                return self._send(400, {"error": str(e)})
        if p == "/api/chat":
            sid = b.get("session_id", "")
            if not core.get_session(sid):
                return self._send(404, {"error": "session not found"})
            try:
                return self._send(200, core.generate_reply(sid, b.get("text", "")))
            except core.BudgetExceeded as e:
                return self._send(429, {"detail": str(e)})
        if p == "/api/memory":
            return self._send(200, core.add_memory(b["session_id"], b["kind"], b["text"],
                                                   source=b.get("source", "用户手动添加")))
        if p == "/api/source/revoke":
            sid = b.get("session_id") or b.get("text")
            return self._send(200, core.revoke_source(sid)) if sid else self._send(400, {"error": "session_id required"})
        if p == "/api/device/button":
            sid = b.get("session_id") or "demo"
            evt = device_bridge.button_press(sid)
            core.audit(sid, "device.button", evt["id"], "模拟实体按钮按下")
            return self._send(200, evt)
        if p == "/api/device/display":
            cmd = device_bridge.display(b["session_id"], b.get("text", ""), b.get("color", "amber"))
            core.audit(b["session_id"], "device.display", cmd["id"], "显示命令 + ACK")
            return self._send(200, cmd)
        if p == "/api/bookmark":
            return self._send(200, core.create_bookmark(b["session_id"], b["note"],
                                                        b.get("choice", ""), b.get("next_step", "")))
        if p == "/api/action":
            try:
                return self._send(200, core.create_action(b["session_id"], b["kind"], b["title"], b.get("detail", ""), b.get("when", "")))
            except (ValueError, KeyError) as e:
                return self._send(400, {"error": str(e)})
        m = re.fullmatch(r"/api/action/([\w-]+)/commit", p)
        if m:
            out = core.commit_action(m.group(1), real=bool(b.get("real")))
            return self._send(200, out) if out else self._send(404, {"error": "action not found"})
        m = re.fullmatch(r"/api/bookmark/([\w-]+)/commit", p)
        if m:
            out = core.commit_bookmark(m.group(1))
            return self._send(200, out) if out else self._send(404, {"error": "bookmark not found"})
        m = re.fullmatch(r"/api/device/(start|stop)", p)
        if m:
            return self._send(200, core.device_start() if m.group(1) == "start" else core.device_stop())
        return self._send(404, {"error": "not found"})

    def do_PATCH(self):  # noqa: N802
        p = urlparse(self.path).path
        b = self._body()
        m = re.fullmatch(r"/api/memory/([\w-]+)", p)
        if m:
            out = core.update_memory(m.group(1), b.get("text"), b.get("status"))
            return self._send(200, out) if out else self._send(404, {"error": "memory not found"})
        return self._send(404, {"error": "not found"})

    def do_PATCH(self):  # noqa: N802
        p = urlparse(self.path).path
        b = self._body()
        m = re.fullmatch(r"/api/session/([\w-]+)/persona", p)
        if m:
            try:
                out = core.set_session_persona(m.group(1), b.get('persona_id', ''))
            except ValueError as e:
                return self._send(400, {'error': str(e)})
            return self._send(200, out) if out else self._send(404, {'error': 'session not found'})
        m = re.fullmatch(r"/api/session/([\w-]+)", p)
        if not m:
            return self._send(404, {"error": "not found"})
        title = (b.get("title") or "").strip()
        if not title:
            return self._send(400, {"error": "title required"})
        out = core.rename_session(m.group(1), title)
        return self._send(200, out) if out else self._send(404, {"error": "session not found"})

    def do_PUT(self):  # noqa: N802
        p = urlparse(self.path).path
        b = self._body()
        m = re.fullmatch(r"/api/session/([\w-]+)/persona", p)
        if not m:
            m = re.fullmatch(r"/api/session/([\w-]+)/mode", p)
            if not m:
                return self._send(404, {'error': 'not found'})
            try:
                out = core.set_session_mode(m.group(1), b.get('interaction_mode', ''))
            except ValueError as e:
                return self._send(400, {'error': str(e)})
            return self._send(200, out) if out else self._send(404, {'error': 'session not found'})
        try:
            out = core.set_session_persona(m.group(1), b.get('persona_id', ''))
        except ValueError as e:
            return self._send(400, {'error': str(e)})
        return self._send(200, out) if out else self._send(404, {'error': 'session not found'})

    def do_DELETE(self):  # noqa: N802
        p = urlparse(self.path).path
        m = re.fullmatch(r"/api/session/([\w-]+)", p)
        if m:
            if not core.get_session(m.group(1)):
                return self._send(404, {"error": "session not found"})
            return self._send(200, core.delete_session(m.group(1)))
        m = re.fullmatch(r"/api/memory/([\w-]+)", p)
        if m:
            return self._send(200, {"ok": True}) if core.delete_memory(m.group(1)) \
                else self._send(404, {"error": "memory not found"})
        return self._send(404, {"error": "not found"})


if __name__ == "__main__":
    raise SystemExit("备用服务器已停用：请安装依赖并使用 FastAPI 主服务。")
