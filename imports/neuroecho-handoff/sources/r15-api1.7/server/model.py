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


def from_env() -> ModelClient | None:
    base = os.getenv("XINJI_MODEL_BASE_URL", "").strip()
    key = os.getenv("XINJI_MODEL_API_KEY", "").strip()
    name = os.getenv("XINJI_MODEL_NAME", "").strip()
    if not (base and key and name):
        try:
            s = model_settings.load()
        except Exception:
            s = {}
        base = base or (s.get("base_url") or "").strip()
        key = key or (s.get("api_key") or "").strip()
        name = name or (s.get("model") or "").strip()
    if not (base and key and name):
        return None
    try:
        timeout = float(os.getenv("XINJI_MODEL_TIMEOUT", "") or model_settings.load().get("timeout") or DEFAULT_TIMEOUT)
    except (ValueError, Exception):
        timeout = DEFAULT_TIMEOUT
    return ModelClient(base, key, name, timeout)


def status() -> dict:
    base = os.getenv("XINJI_MODEL_BASE_URL", "").strip()
    name = os.getenv("XINJI_MODEL_NAME", "").strip()
    try:
        s = model_settings.load()
    except Exception:
        s = {}
    base = base or (s.get("base_url") or "").strip()
    name = name or (s.get("model") or "").strip()
    ready = bool(from_env())
    return {
        "mode": "model" if ready else "rule",
        "model": name or None,
        "base_url": base or None,
        "configured": ready,
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
