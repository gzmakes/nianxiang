"""Small, local lexical retrieval for user-approved text sources.

This is a bounded aid to conversation, not a semantic search engine. It never
reads a source or calls a model itself. The caller must enforce consent and
revocation before supplying document text.
"""
from __future__ import annotations

import re

_HAN = re.compile(r"[\u3400-\u9fff]+")
_LATIN = re.compile(r"[a-z0-9][a-z0-9_-]{1,}", re.I)
_FILLERS = (
    "这份文档", "这个文档", "文档里面", "文档中", "文档里", "文档", "里面", "这里", "关于",
    "告诉我", "请问", "能不能", "可不可以", "有没有", "是什么", "怎么样", "为什么", "多少",
    "哪些", "什么", "如何", "哪里", "哪个", "怎样", "给我", "帮我", "总结", "一下", "内容",
    "the", "and", "what", "where", "when", "which", "does", "about", "document", "please", "tell",
)
_COMMON_HAN = {"我们", "你们", "他们", "一个", "这个", "那个", "可以", "是否", "知道", "提到", "说的"}


def _terms(query: str) -> tuple[set[str], set[str]]:
    cleaned = query.lower()
    for filler in _FILLERS:
        # Latin fillers are removed as whole words, not from identifiers.
        if filler.isascii():
            cleaned = re.sub(r"\b" + re.escape(filler) + r"\b", " ", cleaned)
        else:
            cleaned = cleaned.replace(filler, " ")
    latin = set(_LATIN.findall(cleaned))
    grams: set[str] = set()
    for segment in _HAN.findall(cleaned):
        for width in (2, 3, 4):
            grams.update(segment[i:i + width] for i in range(len(segment) - width + 1)
                         if segment[i:i + width] not in _COMMON_HAN)
    return latin, grams


def relevant_excerpts(text: str, query: str, *, limit: int = 3) -> list[str]:
    """Return up to three relevant 260-char windows, maximum 780 chars total.

    Matching uses case-insensitive Latin tokens and contiguous Chinese n-grams;
    it deliberately abstains when no terms match. Offsets are not citations.
    """
    latin, grams = _terms(query[:4000])
    if not text or not (latin or grams) or limit <= 0:
        return []
    candidates: list[tuple[int, int, str]] = []
    # Overlap prevents a matching phrase at a window boundary being missed.
    for start in range(0, min(len(text), 20000), 200):
        chunk = text[start:start + 260].strip()
        if not chunk:
            continue
        lower = chunk.lower()
        latin_hits = {word for word in latin if re.search(r"(?<![a-z0-9_-])" + re.escape(word) + r"(?![a-z0-9_-])", lower)}
        gram_hits = {gram for gram in grams if gram in lower}
        score = sum(6 + min(len(word), 12) for word in latin_hits)
        score += sum(len(gram) - 1 for gram in gram_hits)
        if score:
            candidates.append((score, start, chunk))
    candidates.sort(key=lambda row: (-row[0], row[1]))
    chosen: list[tuple[int, str]] = []
    for _, start, chunk in candidates:
        if any(abs(start - previous) < 260 for previous, _ in chosen):
            continue
        chosen.append((start, chunk))
        if len(chosen) >= min(limit, 3):
            break
    return [chunk for _, chunk in chosen]
