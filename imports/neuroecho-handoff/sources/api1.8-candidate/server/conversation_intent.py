"""Small explicit conversation controls; ordinary mentions are not commands.

Only the start of a user turn is considered. These controls stay within one
session and are not facts about the person or cross-session memory.
"""
from __future__ import annotations

import re

_LISTEN = (
    '先听我说', '我希望你先听我说', '我想先说完', '先让我说完',
    '先别给建议', '先不要给建议', '别急着给建议',
    '我现在只想吐槽', '今天只想吐槽', '我现在只想说说',
    '我只想说说', '我只想吐槽',
)
_REFLECT = (
    '帮我梳理', '一起梳理', '我们一起梳理', '帮我想想', '帮我分析',
    '我想听你的建议', '我想听听你的建议', '现在可以给建议了',
    '给我点建议', '给我一些建议', '帮我写', '帮我回', '帮我接着写',
    '帮我决定', '帮我选', '帮我做', '下一步怎么办', '怎么办',
)
_AUTO = ('恢复自然聊天', '恢复默认回应', '不用只听我说', '别只听我说')

# Exact user-authored statements only. This is deliberately not a sentiment
# classifier: a quoted anecdote, uncertain claim or document excerpt cannot
# silently become a behavioral instruction.
_CONFIRMED_PREFERENCES = {
    '我希望你先听我说': 'listen',
    '我希望你先听我说完': 'listen',
    '我不希望你马上给建议': 'listen',
    '我不希望你立刻给建议': 'listen',
    '我希望你先听我说，不急着给建议': 'listen',
    '我希望你先听我说，不要急着给建议': 'listen',
    '我希望你主动给我建议': 'reflect',
    '我希望你直接给我建议': 'reflect',
}


def confirmed_preference_mode(text: str) -> str | None:
    """Interpret only an exact, independently confirmed companion preference."""
    return _CONFIRMED_PREFERENCES.get(text.strip().rstrip('。'))


def requested_response_mode(text: str) -> str | None:
    """Read unquoted direct requests, without interpreting wider context.

    The exact vocabulary is intentionally small. For other phrasing the model
    still sees the current user message and can respond to its actual intent.
    """
    opening = text.strip()
    if opening.startswith(_AUTO):
        return 'auto'
    if opening.startswith(_LISTEN):
        return 'listen'
    # Optional polite prefix is bounded so a recollection such as
    # '同事说，帮我分析…' cannot set the conversation mode.
    opening = re.sub(r'^(?:请你|请|可以|能不能|你能不能|你能)\s*', '', opening, count=1)
    if opening.startswith(_REFLECT):
        return 'reflect'
    return None

def requested_conversation_style(text: str) -> str | None:
    """Only an explicit direct opening changes the lasting conversation style.

    Quoted messages, recollections and ordinary uses of these words do not
    count. The setting is a conversation control, not a remembered fact.
    """
    opening = re.sub(r'^(?:请你|请|可以|能不能|你能不能|你能)\s*', '', text.strip(), count=1)
    opening = re.sub(r'^(?:你|说话|回复|回答|聊天|你的语气|语气)\s*', '', opening, count=1)
    if re.match(r'^(?:再)?(?:认真|严肃|正经)(?:一|点|些)', opening):
        return 'serious'
    if re.match(r'^(?:再)?(?:活泼|俏皮|轻松)(?:一|点|些)', opening):
        return 'playful'
    if re.match(r'^恢复(?:默认|自然|原来)(?:的)?(?:风格|语气|说话方式)', opening):
        return 'warm'
    return None
