"""Small, local lexical retrieval for user-approved text sources.

This is a bounded aid to conversation, not a semantic search engine. It never
reads a source or calls a model itself. The caller must enforce consent and
revocation before supplying document text.
"""
from __future__ import annotations

import re

_HAN = re.compile(r"[\u3400-\u9fff]+")
_LATIN = re.compile(r"[a-z0-9][a-z0-9_-]{1,}", re.I)
_SENTENCE_END = re.compile(r"[。！？!?\r\n]+|(?<!\d)\.(?=\s|$)")
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
    """Return up to three relevant 260-char passages, maximum 780 chars total.

    Matching uses case-insensitive Latin tokens and contiguous Chinese n-grams;
    it deliberately abstains when no terms match. Prefer complete sentences and
    cover unmatched query terms before repeating evidence for one topic.
    Offsets are internal selection data, not citations.
    """
    latin, grams = _terms(query[:4000])
    if not text or not (latin or grams) or limit <= 0:
        return []
    text = text[:20000]
    boundaries = [0] + [match.end() for match in _SENTENCE_END.finditer(text)]
    if boundaries[-1] != len(text):
        boundaries.append(len(text))
    windows: list[tuple[int, int]] = []
    for index, start in enumerate(boundaries[:-1]):
        end = boundaries[index + 1]
        if end - start > 260:
            # An unusually long sentence still has bounded, overlapping views.
            windows.extend((offset, min(offset + 260, end))
                           for offset in range(start, end, 200))
            continue
        following = index + 2
        while following < len(boundaries) and boundaries[following] - start <= 260:
            end = boundaries[following]
            following += 1
        windows.append((start, end))

    weights = {('latin', word): 6 + min(len(word), 12) for word in latin}
    weights.update({('han', gram): len(gram) - 1 for gram in grams})
    candidates: list[tuple[int, int, str, set[tuple[str, str]]]] = []
    for start, end in windows:
        chunk = text[start:end].strip()
        if not chunk:
            continue
        lower = chunk.lower()
        latin_hits = {word for word in latin if re.search(r"(?<![a-z0-9_-])" + re.escape(word) + r"(?![a-z0-9_-])", lower)}
        gram_hits = {gram for gram in grams if gram in lower}
        hits = {('latin', word) for word in latin_hits} | {('han', gram) for gram in gram_hits}
        if hits:
            candidates.append((start, end, chunk, hits))
    chosen: list[tuple[int, int, str, set[tuple[str, str]]]] = []
    covered: set[tuple[str, str]] = set()
    while candidates and len(chosen) < min(limit, 3):
        eligible = [row for row in candidates if row[3] - covered or not any(
            row[0] < previous[1] and previous[0] < row[1] for previous in chosen)]
        if not eligible:
            break
        selected = max(eligible, key=lambda row: (
            sum(weights[term] for term in row[3] - covered),
            sum(weights[term] for term in row[3]), -row[0]))
        candidates.remove(selected)
        chosen.append(selected)
        covered.update(selected[3])
    return [chunk for _, _, chunk, _ in chosen]
