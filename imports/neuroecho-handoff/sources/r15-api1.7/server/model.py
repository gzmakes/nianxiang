"""模型适配器：OpenAI 兼容 Chat Completions（可配置 base URL）。

环境变量：
    XINJI_MODEL_BASE_URL   例如 https://api.deepseek.com/v1
    XINJI_MODEL_API_KEY    模型服务密钥（不写入仓库）
    XINJI_MODEL_NAME       例如 deepseek-chat
    XINJI_MODEL_TIMEOUT    秒，默认 8

未配置时返回 None，调用方降级到规则引擎（PRD F13：服务不可用降级）。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from . import model_settings

DEFAULT_TIMEOUT = 8


class ModelError(RuntimeError):
    pass


class ModelClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(self, system: str, user: str, max_tokens: int = 1200) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.6,
            "max_tokens": max_tokens,
        }
        from urllib.parse import urlparse
        # The official DeepSeek API enables thinking by default. Companion
        # replies have a limited output budget; use non-thinking mode just as
        # the tool-call path does, without sending vendor fields elsewhere.
        if urlparse(self.base_url).hostname == "api.deepseek.com":
            payload["thinking"] = {"type": "disabled"}
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise ModelError(f"model http {e.code}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ModelError(f"model network: {e}") from e
        except (json.JSONDecodeError, UnicodeError) as e:
            raise ModelError("model invalid json") from e

        try:
            choice = data["choices"][0]
            if not isinstance(choice, dict):
                raise TypeError("choice is not an object")
            if choice.get("finish_reason") == "length":
                raise ModelError("model incomplete response")
            text = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise ModelError("model malformed response") from e
        if not isinstance(text, str) or not text.strip():
            raise ModelError("model empty response")
        return text.strip()


    def complete_tools(self, messages: list[dict], tools: list[dict], max_tokens: int = 700) -> dict:
        """One OpenAI-compatible tool-capable step; no model content is logged."""
        payload = {"model": self.model, "messages": messages, "tools": tools,
                   "tool_choice": "auto", "temperature": 0.6, "max_tokens": max_tokens}
        from urllib.parse import urlparse
        # DeepSeek thinking defaults on; opt out for short companion tool calls.
        # Other compatible providers need not accept DeepSeek-specific fields.
        if urlparse(self.base_url).hostname == "api.deepseek.com":
            payload["thinking"] = {"type": "disabled"}
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise ModelError(f"model http {e.code}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ModelError(f"model network: {e}") from e
        except (json.JSONDecodeError, UnicodeError) as e:
            raise ModelError("model invalid json") from e
        try:
            choice = data["choices"][0]
            message = choice["message"]
            if not isinstance(message, dict) or choice.get("finish_reason") == "length":
                raise ValueError("incomplete response")
            return message
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise ModelError("model malformed or incomplete response") from e


def _resolve() -> dict:
    """env > model-settings.json > 公共演示节点（可用 XINJI_MODEL_PUBLIC=0 关闭）。"""
    base = os.getenv("XINJI_MODEL_BASE_URL", "").strip()
    key = os.getenv("XINJI_MODEL_API_KEY", "").strip()
    name = os.getenv("XINJI_MODEL_NAME", "").strip()
    source = "env" if (base and key and name) else ""
    timeout = None
    if not (base and key and name):
        try:
            s = model_settings.load()
        except Exception:
            s = {}
        base = base or (s.get("base_url") or "").strip()
        key = key or (s.get("api_key") or "").strip()
        name = name or (s.get("model") or "").strip()
        timeout = s.get("timeout")
        if base and key and name:
            source = "file"
    if not (base and key and name):
        public = model_settings.public_endpoint()
        if public:
            return {"base_url": public["base_url"], "api_key": public["api_key"],
                    "model": public["model"], "timeout": public["timeout"], "source": "public"}
    return {"base_url": base, "api_key": key, "model": name,
            "timeout": timeout, "source": source}


def from_env() -> ModelClient | None:
    cfg = _resolve()
    if not (cfg["base_url"] and cfg["api_key"] and cfg["model"]):
        return None
    fallback = 20.0 if cfg["source"] == "public" else DEFAULT_TIMEOUT
    try:
        timeout = float(os.getenv("XINJI_MODEL_TIMEOUT", "") or cfg["timeout"] or fallback)
    except (ValueError, TypeError):
        timeout = fallback
    client = ModelClient(cfg["base_url"], cfg["api_key"], cfg["model"], timeout)
    client.source = cfg["source"] or "env"
    return client


def status() -> dict:
    cfg = _resolve()
    ready = bool(cfg["base_url"] and cfg["api_key"] and cfg["model"])
    return {
        "mode": "model" if ready else "rule",
        "model": cfg["model"] or None,
        "base_url": cfg["base_url"] or None,
        "configured": ready,
        "source": cfg["source"] or None,
    }


def test_connection() -> dict:
    """最小连通性测试：一次短调用，返回延迟/错误。"""
    client = from_env()
    if client is None:
        return {"ok": False, "error": "未配置模型（base_url / key / model）"}
    import time as _time
    t0 = _time.time()
    try:
        out = client.complete("你是一个连通性测试。只回复 OK。", "OK?")
        return {"ok": True, "latency_ms": round((_time.time() - t0) * 1000),
                "model": client.model, "reply": out[:40]}
    except ModelError as e:
        return {"ok": False, "error": str(e)[:160],
                "latency_ms": round((_time.time() - t0) * 1000)}
