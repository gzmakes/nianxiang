import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from server import chat_delivery, core, plugin_bridge


class DeliveryTests(unittest.TestCase):
 def test_five_paragraphs_have_four_ordered_persisted_sends(self):
    db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
    db.execute('create table messages(id text primary key, session_id text, text text)')
    chat_delivery.initialize(db)
    original = '一\n\n二\n\n三\n\n四\n\n五'
    db.execute('insert into messages values(?,?,?)', ('m', 's', original))
    chat_delivery.register(db, 's', 'm', original, at=100)
    m = [{'id':'m', 'text':original}]
    chat_delivery.annotate(db, 's', m, at=100)
    assert m[0]['bubbles'] == ['一'] and m[0]['delivery_pending']
    chat_delivery.annotate(db, 's', m, at=101)
    assert m[0]['bubbles'] == ['一', '二']
    m2 = [{'id':'m', 'text':original}]
    chat_delivery.annotate(db, 's', m2, at=200)
    assert m2[0]['bubbles'] == ['一', '二', '三', '四\n\n五']
    assert m2[0]['text'] == original and not m2[0]['delivery_pending']


 def test_interrupt_truncates_unsent_content_and_survives_refresh(self):
    db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
    db.execute('create table messages(id text primary key, session_id text, text text)')
    chat_delivery.initialize(db)
    text = '第一段\n\n第二段\n\n第三段'
    db.execute('insert into messages values(?,?,?)', ('m', 's', text))
    chat_delivery.register(db, 's', 'm', text, at=100)
    chat_delivery.interrupt(db, 's', at=100.9)
    assert db.execute('select text from messages').fetchone()[0] == '第一段\n\n第二段'
    msg = [{'id':'m', 'text':text}]
    chat_delivery.annotate(db, 's', msg, at=999)
    assert msg[0]['bubbles'] == ['第一段', '第二段'] and not msg[0]['delivery_pending']


 def test_user_input_atomically_interrupts_old_reply(self):
    tmp_path = Path(self.enterContext(tempfile.TemporaryDirectory()))
    self.enterContext(patch.object(core, "DB_PATH", str(tmp_path/"local.db")))
    core.init_db()
    sid = core.create_session(mode='empty')['session']['id']
    conn = core.get_db(); conn.execute('BEGIN IMMEDIATE')
    conn.execute("insert into messages(id,session_id,role,text,created_at) values('m',?,'assistant',?,?)", (sid,'前面\n\n后面',core.now()))
    chat_delivery.register(conn,sid,'m','前面\n\n后面',at=100)
    conn.commit(); conn.close()
    with patch('server.chat_delivery.time.time', return_value=100.1):
        core.add_message(sid, 'user', '等一下')
    conn=core.get_db()
    assert conn.execute("select text from messages where id='m'").fetchone()[0] == '前面'
    conn.close()


 def test_builtin_stickers_are_present_and_unknown_model_markers_removed(self):
    items = plugin_bridge.memes()['items']
    builtin = next(item for item in items if item['id'] == 'builtin/happy.svg')
    assert builtin['url'] == '/static/stickers/happy.svg'
    assert plugin_bridge.sanitize_meme_markers('你好 [表情: happy] [表情: invented]') == '你好 [表情: builtin/happy.svg] '


class StyleTests(unittest.TestCase):
 def test_direct_style_intent_and_persistence_across_turns(self):
    from server.conversation_intent import requested_conversation_style
    for text, expected in [('认真一点','serious'), ('请你说话正经一点','serious'), ('你能不能活泼一点','playful'), ('恢复默认语气','warm'), ('朋友说「认真一点」',None), ('我今天想认真一点工作',None)]:
        self.assertEqual(requested_conversation_style(text), expected)
    tmp_path = Path(self.enterContext(tempfile.TemporaryDirectory()))
    self.enterContext(patch.object(core, 'DB_PATH', str(tmp_path/'style.db')))
    core.init_db(); sent=[]
    class Fake:
        model='synthetic'
        def complete(self, system, prompt):
            sent.append(prompt); return '我在。'
    self.enterContext(patch.object(core.model, 'from_env', lambda: Fake()))
    sid=core.create_session(mode='empty')['session']['id']
    core.generate_reply(sid, '活泼一点')
    self.assertEqual(core.get_session(sid)['conversation_style'], 'playful')
    core.init_db()
    core.generate_reply(sid, '今天有点累')
    self.assertIn('用户选择活泼', sent[-1])
    self.assertIn('认真倾诉时仍须认真', sent[-1])
    core.generate_reply(sid, '认真一点')
    self.assertEqual(core.get_session(sid)['conversation_style'], 'serious')
    self.assertIn('减少玩笑', sent[-1])
    self.assertEqual(core.list_memories(sid), [])
