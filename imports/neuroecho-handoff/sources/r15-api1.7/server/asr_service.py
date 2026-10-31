"""Bounded, temporary Tencent Cloud SentenceRecognition adapter."""
from __future__ import annotations

import base64
import json
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path


class TranscriptionError(Exception):
    pass


def run_ffmpeg(data: bytes, content_type: str, settings: dict) -> Path:
    cfg = settings.get("asr", {})
    folder = Path(tempfile.mkdtemp(prefix="xinji-asr-"))
    source, target = folder / "input.bin", folder / "converted.wav"
    source.write_bytes(data)
    try:
        subprocess.run([str(cfg.get("ffmpeg_path", "ffmpeg")), "-nostdin", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        return target
    except (OSError, subprocess.SubprocessError) as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise TranscriptionError("录音格式转换失败，请重试。") from exc


def _validate_wav(path: Path, settings: dict) -> tuple[bytes, int]:
    cfg = settings.get("asr", {})
    if not path.is_file() or path.stat().st_size == 0 or path.stat().st_size > int(cfg.get("max_converted_wav_bytes", 2_100_000)):
        raise TranscriptionError("转换后的录音无效或过大。")
    try:
        with wave.open(str(path), "rb") as audio:
            if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or audio.getframerate() != 16000:
                raise TranscriptionError("录音格式不是 16kHz 单声道 PCM。")
            duration = int(audio.getnframes() * 1000 / audio.getframerate())
            if duration <= 0 or duration > 60_000:
                raise TranscriptionError("录音时长必须在 60 秒以内。")
        return path.read_bytes(), duration
    except (wave.Error, EOFError, OSError) as exc:
        raise TranscriptionError("转换后的录音无效。") from exc


def recognize_wav(wav_data: bytes, settings: dict) -> dict:
    try:
        from tencentcloud.common import credential
        from tencentcloud.asr.v20190614 import asr_client, models
    except ImportError as exc:
        raise TranscriptionError("未安装腾讯云 ASR SDK。") from exc
    cfg = settings.get("asr", {})
    try:
        cred = credential.ProfileCredential().get_credential()
        if cred is None:
            raise TranscriptionError("腾讯云 ASR 凭证未配置，请先配置本机凭证文件。")
        client = asr_client.AsrClient(cred, cfg.get("region", "ap-shanghai"))
        request = models.SentenceRecognitionRequest()
        request.from_json_string(json.dumps({"ProjectId": 0, "SubServiceType": 2, "EngSerViceType": cfg.get("engine", "16k_zh"), "SourceType": 1, "VoiceFormat": "wav", "Data": base64.b64encode(wav_data).decode("ascii"), "DataLen": len(wav_data)}))
        response = client.SentenceRecognition(request)
        return {"Result": getattr(response, "Result", ""), "RequestId": getattr(response, "RequestId", "")}
    except TranscriptionError:
        raise
    except Exception as exc:
        message = str(exc)
        if "UnauthorizedOperation" in message or "AuthFailure" in message:
            raise TranscriptionError("腾讯云 ASR 权限不足，请检查 CAM 权限。") from exc
        if "UserNotRegistered" in message:
            raise TranscriptionError("腾讯云 ASR 尚未开通。") from exc
        if "UserHasNoFreeAmount" in message or "UserHasNoAmount" in message:
            raise TranscriptionError("腾讯云 ASR 免费额度已用尽。") from exc
        raise TranscriptionError("腾讯云 ASR 调用失败，请稍后重试。") from exc


def transcribe_bytes(data: bytes, content_type: str, *, settings=None) -> dict:
    if settings is None:
        from .voice_settings import load_settings
        settings = load_settings()
    cfg = settings.get("asr", {})
    if not cfg.get("enabled"):
        raise TranscriptionError("ASR 未配置。")
    if not data or len(data) > int(cfg.get("max_upload_bytes", 4_194_304)):
        raise TranscriptionError("录音为空或超过 4MB 限制。")
    converted = None
    folder = None
    try:
        converted = run_ffmpeg(data, content_type, settings)
        folder = converted.parent
        wav_data, duration = _validate_wav(converted, settings)
        result = recognize_wav(wav_data, settings)
        text = str(result.get("Result") or "").strip()
        if not text:
            raise TranscriptionError("没有识别到可用文字，请再说一次。")
        return {"text": text, "request_id": str(result.get("RequestId") or ""), "audio_duration_ms": duration}
    finally:
        if folder:
            shutil.rmtree(folder, ignore_errors=True)
