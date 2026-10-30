"""User-requested on-device WAV synthesis. No user text or audio is retained."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path

MAX_CHARS = 800
MAX_BYTES = 20_000_000
_slot = threading.BoundedSemaphore(1)


class VoiceUnavailable(Exception):
    pass


def spoken_text(value: str) -> str:
    value = re.sub(r'\[表情[:：]\s*[^\]\r\n]+\]', '', value)
    value = re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)', r'\1', value)
    return re.sub(r'[*_`#]', '', value).strip()


def synthesize(text: str) -> bytes:
    """Generate audio using macOS voices, rejecting empty output even on exit 0."""
    text = spoken_text(text)
    if not text:
        raise ValueError('这条回复没有可生成语音的文字。')
    if len(text) > MAX_CHARS:
        raise ValueError(f'这条回复超过 {MAX_CHARS} 字，请使用朗读功能。')
    if sys.platform != 'darwin' or not os.path.exists('/usr/bin/say') or not os.path.exists('/usr/bin/afconvert'):
        raise VoiceUnavailable('本机语音生成不可用，可使用浏览器朗读。')
    if not _slot.acquire(blocking=False):
        raise VoiceUnavailable('正在生成另一条语音，请稍后再试。')
    try:
        with tempfile.TemporaryDirectory(prefix='xinji-voice-') as folder:
            aiff, wav = Path(folder) / 'voice.aiff', Path(folder) / 'voice.wav'
            try:
                subprocess.run(['/usr/bin/say', '-v', 'Tingting', '-o', str(aiff)],
                               input=text.encode('utf-8'), stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, check=True, timeout=45)
                subprocess.run(['/usr/bin/afconvert', '-f', 'WAVE', '-d', 'LEI16', str(aiff), str(wav)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=15)
                if not wav.is_file() or wav.stat().st_size > MAX_BYTES:
                    raise VoiceUnavailable('本机没有生成有效音频，可使用浏览器朗读。')
                with wave.open(str(wav), 'rb') as audio:
                    if audio.getnframes() < audio.getframerate() // 10:
                        raise VoiceUnavailable('本机语音服务返回空音频，可使用浏览器朗读。')
                return wav.read_bytes()
            except (OSError, subprocess.SubprocessError, wave.Error, EOFError) as exc:
                raise VoiceUnavailable('本机语音生成失败，可使用浏览器朗读。') from exc
    finally:
        _slot.release()
