"""Conservative, local-only extraction of literal user self-statements.

No conversation history, assistant output or connected material is processed here.
The intentionally narrow recognizer misses many valid statements; it never uses
an LLM or sends extra data to a model service.
"""
import hashlib
import re

SOURCE = '对话原话 · 自动记录'

# Whole sentences only: do not turn quoted text, hypotheticals, questions,
# roleplay, or other people's statements into personal facts.
_PATTERN = re.compile(r'^我(?:叫|名叫|的名字是|住在|生活在|来自|工作于|在.{1,20}工作|是|做|从事|负责|目前在做|正在做|喜欢|不喜欢|偏好|习惯|通常|平时|希望|不希望|更喜欢|需要|有|养了|会说|使用)(.{2,80})$')
_UNCERTAIN = re.compile(r'可能|也许|或许|大概|似乎|好像|假如|如果|假设|假装|扮演|举例|比如|例如|听说|据说|他们说|他说|她说|别人说|对方说|客户说|朋友说|同事说|用户说|有人说|我猜|我觉得|我认为|我感觉|我想象|我怀疑|我担心')
# Do not absorb conversational instructions, private secrets or transient states.
_EXCLUDE = re.compile(r'密码|验证码|身份证|银行卡|密钥|令牌|token|password|secret|今天|昨天|明天|此刻|现在感觉|刚才|暂时|这次|请你|帮我|帮忙|你能|你可以|不要记|别记|忘记|删除|不再|以前|曾经|过去|不确定|抑郁|疾病|患病|服药|药物|赌博|自虐|治疗|焦虑症|精神疾病|地址|住址|氟西汀|舍曲林', re.I)


def extract(text: str) -> str | None:
    quote = text.strip().strip('。.!！ \t\r\n')
    if (not quote or len(quote) > 100 or re.search(r'[？?，,；;：:。.!！\n\r“”‘’"「」『』]', quote)
            or re.search(r'[0-9０-９]{5,}|@|https?://', quote, re.I)
            or _UNCERTAIN.search(quote) or _EXCLUDE.search(quote)):
        return None
    match = _PATTERN.fullmatch(quote)
    return quote if match and len(match.group(1).strip()) >= 2 else None


def fingerprint(sid: str, text: str) -> str:
    return hashlib.sha256((sid + '\0' + text.strip()).encode('utf-8')).hexdigest()


def suppress(conn, sid: str, text: str) -> None:
    conn.execute('INSERT OR IGNORE INTO memory_suppressions(session_id,fingerprint) VALUES(?,?)',
                 (sid, fingerprint(sid, text)))


def save(conn, sid: str, message_id: str, text: str, uid, now, *, explicit_restore: bool = False) -> bool:
    quote = extract(text)
    if not quote:
        return False
    if conn.execute('SELECT 1 FROM memory_suppressions WHERE session_id=? AND fingerprint=?',
                    (sid, fingerprint(sid, quote))).fetchone():
        if not explicit_restore:
            return False
        conn.execute('DELETE FROM memory_suppressions WHERE session_id=? AND fingerprint=?',
                     (sid, fingerprint(sid, quote)))
    # Preserve edited cards and deduplicate exact personal quotes without
    # conflating an unrelated source document with a user's own statement.
    existing = conn.execute("SELECT * FROM memories WHERE session_id=? AND (source_message_id=? OR "
                    "(kind='fact' AND status IN ('auto','confirmed') AND text=? AND source IN (?, '对话原话 · 用户选存', '对话原话 · 用户纠正', '对话中用户要求', '用户手动添加'))) LIMIT 1",
                    (sid, message_id, quote, SOURCE)).fetchone()
    if existing:
        if explicit_restore and existing['source'] == SOURCE and existing['status'] == 'auto':
            ts, version = now(), existing['version'] + 1
            conn.execute("UPDATE memories SET source='对话原话 · 用户选存', source_message_id=?, version=?, updated_at=? WHERE id=?", (message_id, version, ts, existing['id']))
            conn.execute("INSERT INTO memory_revisions(id,memory_id,session_id,text,status,version,source,created_at) VALUES(?,?,?,?,?,?,?,?)", (uid('rev'), existing['id'], sid, quote, 'auto', version, '对话原话 · 用户选存', ts))
            return True
        return False
    mid, ts = uid('mem'), now()
    source = '对话原话 · 用户选存' if explicit_restore else SOURCE
    conn.execute('INSERT INTO memories(id,session_id,kind,text,status,version,source,created_at,updated_at,source_message_id) VALUES(?,?,?,?,?,?,?,?,?,?)',
                 (mid, sid, 'fact', quote, 'auto', 1, source, ts, ts, message_id))
    conn.execute('INSERT INTO memory_revisions(id,memory_id,session_id,text,status,version,source,created_at) VALUES(?,?,?,?,?,?,?,?)',
                 (uid('rev'), mid, sid, quote, 'auto', 1, source, ts))
    return True
