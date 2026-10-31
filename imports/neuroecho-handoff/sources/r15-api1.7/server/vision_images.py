"""Validate vision inputs and resolve only stickers exposed by our catalog.

The functions return data URLs for the model adapter; they do not fetch URLs,
log image content, or persist user-provided images.
"""
from __future__ import annotations

import base64
import binascii
from io import BytesIO
import re
import warnings

from PIL import Image, UnidentifiedImageError

from . import plugin_bridge

MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
_DATA_URL = re.compile(r"\Adata:(image/(?:jpeg|png|gif|webp));base64,([A-Za-z0-9+/]*={0,2})\Z", re.ASCII)
_FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/gif": "GIF", "image/webp": "WEBP"}


def _validate_image(raw: bytes, mime: str) -> str:
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("image is empty or exceeds 4 MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                if image.format != _FORMATS[mime]:
                    raise ValueError("image type does not match its contents")
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ValueError("image dimensions are too large")
                image.verify()
            # verify() checks structure but not all pixel data; decode the first frame.
            with Image.open(BytesIO(raw)) as image:
                image.load()
                # Animated stickers have one deterministic visual meaning: frame 0.
                # Convert it to PNG so providers need not support GIF input.
                if mime == "image/gif":
                    output = BytesIO()
                    image.convert("RGBA").save(output, format="PNG")
                    raw, mime = output.getvalue(), "image/png"
                    if len(raw) > MAX_IMAGE_BYTES:
                        raise ValueError("converted image exceeds 4 MiB")
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError("invalid image") from exc
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def validate_data_url(data_url: str) -> str:
    """Return a canonical data URL for a valid JPEG, PNG, GIF or WebP image.

    Raises ValueError for unsupported formats, malformed data, or oversized input.
    """
    if not isinstance(data_url, str):
        raise ValueError("image must be a data URL")
    # Reject oversized encoded payloads before the regex or base64 decoder.
    if len(data_url) > 4 * ((MAX_IMAGE_BYTES + 2) // 3) + 32:
        raise ValueError("image exceeds 4 MiB")
    match = _DATA_URL.fullmatch(data_url)
    if not match:
        raise ValueError("unsupported or malformed image data URL")
    mime, payload = match.groups()
    try:
        raw = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid base64 image") from exc
    return _validate_image(raw, mime)


def sticker_data_url(sticker_id: str) -> str:
    """Read an exposed sticker by exact catalog ID, never by caller-supplied path.

    Built-in SVG stickers are rejected until rasterization is available. The
    catalog's file resolver also checks that resolved files stay inside its roots.
    """
    if not isinstance(sticker_id, str) or not any(
        item.get("id") == sticker_id for item in plugin_bridge.memes().get("items", [])
    ):
        raise ValueError("unknown sticker")
    parts = sticker_id.split("/")
    if len(parts) != 3:
        raise ValueError("sticker format is not supported for vision")
    path = plugin_bridge.meme_file(*parts)
    if path is None:
        raise ValueError("sticker is unavailable")
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".gif": "image/gif", ".webp": "image/webp"}.get(path.suffix.lower())
    if not mime:
        raise ValueError("sticker format is not supported for vision")
    try:
        with path.open("rb") as file:
            raw = file.read(MAX_IMAGE_BYTES + 1)
    except OSError as exc:
        raise ValueError("sticker is unavailable") from exc
    return _validate_image(raw, mime)
