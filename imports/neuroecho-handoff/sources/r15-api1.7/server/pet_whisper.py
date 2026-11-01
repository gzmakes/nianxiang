"""A short standalone pet utterance, separate from chat and memory."""
from __future__ import annotations

from datetime import datetime
from threading import Lock

from . import model


SYSTEM = (
    "你是一位俏皮温柔的网页小伙伴。只说一句自然、轻松的中文碎碎念，"
    "不要超过25个字，不加引号或标题，不要解释。"
    "不要假装知道用户的情况、行程、情绪或身边环境。"
)

# All tabs on this local server share one short model request at a time.
# A second request falls back immediately instead of accumulating work.
_generation_lock = Lock()


def generate() -> dict:
    """Send no user content and persist nothing; the caller may choose a fallback."""
    if not _generation_lock.acquire(blocking=False):
        return {"available": False, "text": None}
    try:
        client = model.from_env()
        if client is None:
            return {"available": False, "text": None}
        hour = datetime.now().hour
        period = "早上" if 5 <= hour < 11 else "中午" if 11 <= hour < 14 else "下午" if 14 <= hour < 19 else "晚上"
        text = client.complete(SYSTEM, f"现在是{period}，随口说一句吧。", max_tokens=100)
        if not isinstance(text, str):
            return {"available": False, "text": None}
        text = " ".join(text.split()).strip(' \t\r\n"\'“”‘’`')
        if not text:
            return {"available": False, "text": None}
        return {"available": True, "text": text[:50]}
    except Exception:
        return {"available": False, "text": None}
    finally:
        _generation_lock.release()
