from __future__ import annotations

import asyncio
import hashlib
import io
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from dataclasses import dataclass

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field


def _csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


@dataclass(frozen=True)
class Settings:
    token_hashes: frozenset[str]
    tts_url: str
    ref_audio_path: str
    prompt_text: str
    prompt_lang: str
    text_lang: str
    max_chars: int
    max_audio_bytes: int
    timeout_seconds: float
    max_queue: int
    bind_host: str
    bind_port: int

    @classmethod
    def from_env(cls) -> "Settings":
        # VOICE_GATEWAY_TOKENS is accepted for deployment convenience, but raw
        # values are immediately reduced to hashes and never logged/returned.
        hashes = set(_csv(os.getenv("VOICE_GATEWAY_TOKEN_HASHES", "")))
        for token in _csv(os.getenv("VOICE_GATEWAY_TOKENS", "")):
            hashes.add(hashlib.sha256(token.encode("utf-8")).hexdigest())
        return cls(
            token_hashes=frozenset(value.lower() for value in hashes if len(value) == 64),
            tts_url=os.getenv("VOICE_GATEWAY_TTS_URL", "http://127.0.0.1:9880/tts").strip(),
            ref_audio_path=os.getenv("VOICE_GATEWAY_REFERENCE_AUDIO", "").strip(),
            prompt_text=os.getenv("VOICE_GATEWAY_PROMPT_TEXT", "").strip(),
            prompt_lang=os.getenv("VOICE_GATEWAY_PROMPT_LANG", "zh").strip() or "zh",
            text_lang=os.getenv("VOICE_GATEWAY_TEXT_LANG", "zh").strip() or "zh",
            max_chars=max(1, int(os.getenv("VOICE_GATEWAY_MAX_CHARS", "800"))),
            max_audio_bytes=max(1024, int(os.getenv("VOICE_GATEWAY_MAX_AUDIO_BYTES", "20000000"))),
            timeout_seconds=max(1.0, float(os.getenv("VOICE_GATEWAY_TIMEOUT", "120"))),
            max_queue=max(0, int(os.getenv("VOICE_GATEWAY_MAX_QUEUE", "10"))),
            bind_host=os.getenv("VOICE_GATEWAY_HOST", "127.0.0.1"),
            bind_port=int(os.getenv("VOICE_GATEWAY_PORT", "9881")),
        )


settings = Settings.from_env()
_semaphore = asyncio.Semaphore(1)
_queue_lock = asyncio.Lock()
_queued = 0


def _token_hash(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:].strip()
    if not token or len(token) > 512:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def require_token(authorization: str | None = Header(default=None)) -> str:
    supplied = _token_hash(authorization)
    if supplied is None or not any(secrets.compare_digest(supplied, expected) for expected in settings.token_hashes):
        raise HTTPException(status_code=401, detail="invalid gateway token", headers={"WWW-Authenticate": "Bearer"})
    return supplied


class TTSRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    persona_id: str = Field(default="whale", min_length=1, max_length=32)
    text: str = Field(min_length=1, max_length=4000)


def _validate_wav(data: bytes) -> bytes:
    if not data or len(data) > settings.max_audio_bytes:
        raise RuntimeError("tts audio is empty or too large")
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            if audio.getnframes() < max(1, audio.getframerate() // 10):
                raise RuntimeError("tts audio is empty")
    except (wave.Error, EOFError) as exc:
        raise RuntimeError("tts did not return a valid wav") from exc
    return data


def synthesize(text: str, persona_id: str) -> bytes:
    if persona_id != "whale":
        raise ValueError("unsupported persona")
    clean = text.strip()
    if not clean:
        raise ValueError("text is empty")
    if len(clean) > settings.max_chars:
        raise ValueError(f"text exceeds {settings.max_chars} characters")
    if not settings.ref_audio_path or not os.path.isfile(settings.ref_audio_path):
        raise RuntimeError("reference audio is not configured")
    # GPT-SoVITS api_v2 exposes /tts as a GET endpoint.  Keep the gateway
    # contract JSON/POST, but translate it to the local service's query
    # parameters here.  Booleans must be lowercase strings because the
    # service parses them through FastAPI/Pydantic query coercion.
    params = {
        "text": clean,
        "text_lang": settings.text_lang,
        "ref_audio_path": settings.ref_audio_path,
        "prompt_text": settings.prompt_text,
        "prompt_lang": settings.prompt_lang,
        "text_split_method": "cut5",
        "batch_size": 1,
        "media_type": "wav",
        "streaming_mode": "false",
    }
    separator = "&" if "?" in settings.tts_url else "?"
    request = urllib.request.Request(
        f"{settings.tts_url}{separator}{urllib.parse.urlencode(params)}",
        headers={"Accept": "audio/wav, application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.timeout_seconds) as response:
            data = response.read(settings.max_audio_bytes + 1)
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("local tts service unavailable") from exc
    if data.lstrip().startswith(b"{"):
        raise RuntimeError("local tts service returned an error")
    return _validate_wav(data)


async def _acquire_slot() -> None:
    global _queued
    async with _queue_lock:
        if _queued >= settings.max_queue:
            raise HTTPException(status_code=503, detail="voice queue is full", headers={"Retry-After": "2"})
        _queued += 1
    try:
        await asyncio.wait_for(_semaphore.acquire(), timeout=settings.timeout_seconds)
    except asyncio.TimeoutError as exc:
        async with _queue_lock:
            _queued = max(0, _queued - 1)
        raise HTTPException(status_code=504, detail="voice queue timed out") from exc


async def _release_slot() -> None:
    global _queued
    _semaphore.release()
    async with _queue_lock:
        _queued = max(0, _queued - 1)


app = FastAPI(title="Nianxiang Voice Gateway", version="1.0.0")


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException):
    return JSONResponse({"detail": exc.detail, "error_code": "unauthorized" if exc.status_code == 401 else "voice_gateway_error"}, status_code=exc.status_code, headers=exc.headers or {})


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/v1/status")
async def status(_token: str = Depends(require_token)):
    return {"ok": True, "provider": "gpt-sovits", "persona_ids": ["whale"], "queue_depth": _queued, "max_queue": settings.max_queue}


@app.post("/v1/tts")
async def tts(body: TTSRequest, _token: str = Depends(require_token)):
    if body.persona_id != "whale":
        raise HTTPException(status_code=422, detail="unsupported persona")
    await _acquire_slot()
    started = time.monotonic()
    try:
        data = await asyncio.to_thread(synthesize, body.text, body.persona_id)
        return Response(data, media_type="audio/wav", headers={"Cache-Control": "no-store", "X-Voice-Duration-Ms": str(round((time.monotonic() - started) * 1000))})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        await _release_slot()
