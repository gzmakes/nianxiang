"""Local files are only accepted as browser-selected, user-reviewed text."""
from pathlib import Path

EXTS = {".md", ".markdown", ".txt", ".json", ".py", ".ts", ".js", ".csv", ".docx"}
MAX_BYTES = 256 * 1024
MAX_FILES = 3
MAX_CHARS = 4000

def list_files(limit: int = 0) -> list:
    # Kept for compatibility: enumerating the user’s directories is not consent.
    return []

def read(limit: int = 0) -> dict:
    return {"ok": False, "error": "请先在页面选择文本文件并预览", "hint": "只读取你选择的文件"}
