"""Small, local relevance filter for memories the user has permitted us to use.

This is deliberately lexical, not a semantic classifier: when it cannot find a
clear link to the current topic it abstains instead of guessing. The caller is
responsible for consent, provenance and revocation before passing memories in.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

_HAN = re.compile(r"[\u3400-\u9fff]+")
_LATIN = re.compile(r"[a-z0-9][a-z0-9_-]{1,}", re.I)
_NO_RECALL = ("不要提记忆", "别提记忆", "不要提起记忆", "别提起记忆", "不要提以前", "别提以前",
              "不想提以前", "不要提过去", "别提过去", "不要提我的记忆", "别提我的记忆")
# This conservative match applies to the current turn only. It does not erase
# history or assert that a persistent topic preference has been stored.
_DECLINE_TOPIC = re.compile(
    r"(?:别|不要|不用|不想|不愿意|不愿|暂不|先不)"
    r"(?:再|继续|去|跟我|和我|向我|给我|跟你|和你|再跟我|再和我|再跟你|再和你){0,3}"
    r"(?:提(?!防|升|高|前|醒|取)|聊|谈|说(?!服|明|谎))"
)
_BROAD_RECALL = ("你还记得我吗", "你记得我吗", "记得我什么", "记得关于我的", "记得关于我",
                 "记得我的什么", "记得哪些", "记住了什么", "知道我什么", "关于我的记忆",
                 "看看我的记忆", "查看我的记忆", "列出我的记忆", "有哪些记忆", "你记得什么",
                 "还记得什么", "你记得我的偏好吗", "你记得我的偏好", "我喜欢什么", "我不喜欢什么")
# Generic conversational words are poor evidence of shared topic. Strip them
# before forming contiguous Chinese n-grams, so e.g. “今天我喜欢...” does not
# retrieve every unrelated memory containing “喜欢”.
_FILLERS = ("你还记得", "你记得", "还记得", "能不能", "可不可以", "帮我", "告诉我", "说说",
            "聊聊", "想聊", "一下", "关于", "之前", "以前", "最近", "今天", "明天", "昨天",
            "我想", "我们", "你们", "他们", "我觉得", "我的", "你的", "自己", "现在", "这个",
            "那个", "一下子", "什么", "怎么", "如何", "哪些", "哪个", "为何", "为什么",
            "是不是", "有没有", "喜欢", "不喜欢", "需要", "可以", "想要", "时候", "感觉",
            "事情", "时候", "一下", "please", "about", "what", "where", "when", "tell", "remember")
_COMMON = {"就是", "还是", "真的", "一起", "因为", "所以", "一个", "一些", "如果", "这些", "那些"}
# A few high-precision topic bridges, not an inference about the user's state.
# The actual memory text is passed through unchanged and can still conflict.
_TOPICS = (("失眠", "睡不着", "入睡困难", "睡眠"),
           ("咖啡", "拿铁", "卡布奇诺"),
           ("茶", "红茶", "绿茶", "乌龙", "普洱"),
           ("跑步", "慢跑", "晨跑", "夜跑"),
           ("散步", "走路", "步行"))


def user_declines_recall(query: str) -> bool:
    return any(phrase in query for phrase in _NO_RECALL) or bool(_DECLINE_TOPIC.search(query))


def _terms(text: str) -> tuple[set[str], set[str]]:
    cleaned = text.lower()[:4000]
    for filler in _FILLERS:
        if filler.isascii():
            cleaned = re.sub(r"\b" + re.escape(filler) + r"\b", " ", cleaned)
        else:
            cleaned = cleaned.replace(filler, " ")
    latin = set(_LATIN.findall(cleaned))
    grams: set[str] = set()
    for segment in _HAN.findall(cleaned):
        for width in (2, 3, 4):
            grams.update(segment[i:i + width] for i in range(len(segment) - width + 1)
                         if segment[i:i + width] not in _COMMON)
    return latin, grams


def relevant_memories(memories: Sequence[dict], query: str, *, limit: int = 8) -> list[dict]:
    """Rank already-authorized cards for a turn, preserving ties and conflicts.

    Broad questions explicitly asking what is remembered can see a bounded set;
    otherwise a meaningful literal match is required. Similar ideas expressed
    with unrelated words may be missed; in that case we do not invent a link.
    """
    if not query or limit <= 0:
        return []
    query = query.strip()
    if user_declines_recall(query):
        return []
    broad = any(phrase in query for phrase in _BROAD_RECALL)
    latin, grams = _terms(query)
    topics = [topic for topic in _TOPICS if any(word in query for word in topic)]
    ranked = []
    for index, memory in enumerate(memories):
        value = str(memory.get('text') or '').lower()
        latin_hits = {word for word in latin if re.search(
            r"(?<![a-z0-9_-])" + re.escape(word) + r"(?![a-z0-9_-])", value)}
        gram_hits = {gram for gram in grams if gram in value}
        score = sum(6 + min(len(word), 12) for word in latin_hits)
        score += sum(len(gram) - 1 for gram in gram_hits)
        score += 8 * sum(any(word in value for word in topic) for topic in topics)
        if score or broad:
            # Equal-quality matches prefer confirmed material. Unconfirmed
            # material remains separately labelled by the prompt builder.
            ranked.append((-score, memory.get('status') != 'confirmed', index, memory))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in ranked[:limit]]
