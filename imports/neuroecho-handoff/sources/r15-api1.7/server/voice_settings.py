"""Voice configuration. Speech input is browser-local; TTS may be local or remote."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# The paired service points this at its private data directory.  Keeping the
# source-tree path as the default preserves the existing standalone launcher.
PATH: Path | None = None
DEFAULTS = {
    "asr": {"enabled": False, "region": "ap-shanghai", "engine": "16k_zh",
            "max_record_seconds": 55, "max_upload_bytes": 4_194_304,
            "max_converted_wav_bytes": 2_100_000,
            "ffmpeg_path": r"D:\Apps\GPT-SoVITS\bin\ffmpeg.exe"},
    "tts": {"enabled": False, "provider": "local", "base_url": "http://127.0.0.1:9880",
            "gateway_url": "", "gateway_token": "", "persona_id": "whale",
            "ref_audio_path": r"D:\Apps\GPT-SoVITS\refs\fish_20261027.wav",
            "prompt_text": "你终于来了，我好饿啊，爸爸给我喂点饭吧，我要吃大白饭",
            "text_lang": "zh", "prompt_lang": "zh", "timeout_seconds": 180,
            "max_chars": 800, "max_audio_bytes": 20_000_000},
}


def _env_override(settings: dict) -> dict:
    """Allow portable installs to configure paths without editing tracked files."""
    asr, tts = settings.setdefault("asr", {}), settings.setdefault("tts", {})
    if (value := os.environ.get("XINJI_ASR_ENABLED")) is not None:
        asr["enabled"] = value.strip().lower() in {"1", "true", "yes", "on"}
    if (value := os.environ.get("XINJI_ASR_REGION")):
        asr["region"] = value.strip()
    if (value := os.environ.get("XINJI_ASR_ENGINE")):
        asr["engine"] = value.strip()
    if (value := os.environ.get("XINJI_FFMPEG_PATH")):
        asr["ffmpeg_path"] = value.strip()
    if (value := os.environ.get("NIANXIANG_TTS_ENABLED") or os.environ.get("XINJI_TTS_ENABLED")) is not None:
        tts["enabled"] = value.strip().lower() in {"1", "true", "yes", "on"}
    if (value := os.environ.get("XINJI_TTS_URL")):
        tts["base_url"] = value.strip()
    provider_from_env = os.environ.get("NIANXIANG_TTS_PROVIDER") or os.environ.get("XINJI_TTS_PROVIDER")
    if provider_from_env:
        tts["provider"] = provider_from_env.strip().lower()
        # The remote provider is an explicit opt-in and the public deployment
        # configuration does not need a second legacy XINJI_TTS_ENABLED flag.
        # An explicit enabled=false still wins.
        if os.environ.get("NIANXIANG_TTS_ENABLED") is None and os.environ.get("XINJI_TTS_ENABLED") is None:
            tts["enabled"] = tts["provider"] == "remote"
    # NIANXIANG_* is the public portable configuration.  Keep the XINJI_*
    # aliases for existing local launchers and saved setup instructions.
    if (value := os.environ.get("NIANXIANG_TTS_BASE_URL") or os.environ.get("XINJI_TTS_GATEWAY_URL")):
        tts["gateway_url"] = value.strip()
    if (value := os.environ.get("NIANXIANG_TTS_TOKEN") or os.environ.get("XINJI_TTS_GATEWAY_TOKEN")):
        tts["gateway_token"] = value.strip()
    if (value := os.environ.get("NIANXIANG_TTS_PERSONA_ID") or os.environ.get("XINJI_TTS_PERSONA_ID")):
        tts["persona_id"] = value.strip()
    if (value := os.environ.get("NIANXIANG_TTS_TIMEOUT")):
        try:
            tts["timeout_seconds"] = max(1.0, float(value.strip()))
        except ValueError:
            pass
    if (value := os.environ.get("XINJI_TTS_REFERENCE_AUDIO")):
        tts["ref_audio_path"] = value.strip()
    return settings


def _merge(base, override):
    out = dict(base)
    for key, value in (override or {}).items():
        out[key] = {**out.get(key, {}), **value} if isinstance(value, dict) else value
    return out


def _sanitize(settings: dict) -> dict:
    """Keep damaged local text from breaking GPT-SoVITS on Windows."""
    tts = settings.setdefault("tts", {})
    prompt = str(tts.get("prompt_text", ""))
    if any(0xE000 <= ord(char) <= 0xF8FF for char in prompt) or "\ufffd" in prompt:
        tts["prompt_text"] = DEFAULTS["tts"]["prompt_text"]
    return settings


def load_settings() -> dict:
    target = Path(PATH) if PATH is not None else ROOT / "voice-settings.json"
    if not target.is_file():
        return _env_override(_sanitize(_merge(DEFAULTS, {})))
    try:
        # PowerShell's UTF-8 output may include a BOM; accept both BOM and
        # BOM-less JSON so a generated local config is never mistaken for a
        # missing config and silently replaced by defaults.
        return _env_override(_sanitize(_merge(DEFAULTS, json.loads(target.read_text(encoding="utf-8-sig")))))
    except (OSError, ValueError, TypeError):
        return _env_override(_sanitize(_merge(DEFAULTS, {})))


def _credentials_available() -> bool:
    try:
        from tencentcloud.common import credential
        # The SDK returns None when no profile exists instead of raising.
        return credential.ProfileCredential().get_credential() is not None
    except Exception:
        return False


def status(settings=None) -> dict:
    settings = settings or load_settings()
    asr, tts = settings.get("asr", {}), settings.get("tts", {})
    return {
        "asr_enabled": bool(asr.get("enabled")),
        "asr_credentials_configured": _credentials_available(),
        "ffmpeg_available": Path(str(asr.get("ffmpeg_path", ""))).is_file(),
        "tts_enabled": bool(tts.get("enabled")),
        "tts_reference_audio": Path(str(tts.get("ref_audio_path", ""))).is_file(),
        "tts_base_url": str(tts.get("base_url", "")),
        "tts_port": 9880,
    }
