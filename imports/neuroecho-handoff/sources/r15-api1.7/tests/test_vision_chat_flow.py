import base64
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from server import core, main, model, agent_runtime

class VisionChatTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(core, 'DB_PATH', str(Path(self.tmp.name) / 'test.db'))
        self.db_patch.start()
        core.init_db()
        self.sid = core.create_session('empty')['session']['id']
        out = BytesIO(); Image.new('RGB', (8, 8), 'blue').save(out, format='PNG')
        self.url = 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()
    def tearDown(self):
        self.db_patch.stop(); self.tmp.cleanup()
    def test_upload_reaches_model_and_bytes_not_persisted(self):
        captured=[]
        class Fake:
            model='test'
            def complete(self, system, user, **kwargs):
                captured.append((system, kwargs.get('image_data_url'))); return '蓝色图片。'
        with patch.object(model, 'from_env', return_value=Fake()):
            result=main.chat(main.ChatIn(session_id=self.sid, text='看这张图片', image_data_url=self.url, request_id='vision-test-123'))
        self.assertEqual(result['action'], 'model.reply')
        self.assertEqual(captured[0][1], self.url)
        self.assertIn('本轮用户消息附有一张图片', captured[0][0])
        conn=core.get_db()
        try:
            self.assertNotIn(self.url, str([tuple(row) for row in conn.execute('select text from messages')]))
            self.assertNotIn(self.url, str([tuple(row) for row in conn.execute('select payload_hash from chat_turns')]))
        finally: conn.close()
    def test_command_caption_is_still_seen(self):
        captured=[]
        class Fake:
            model='test'
            def complete(self, system, user, **kwargs): captured.append(kwargs); return '我看到一张图。'
        with patch.object(model, 'from_env', return_value=Fake()):
            result=main.chat(main.ChatIn(session_id=self.sid, text='记住这张图', image_data_url=self.url))
        self.assertEqual(result['action'], 'model.reply')
        self.assertEqual(captured[0]['image_data_url'],self.url)
        self.assertIn('图片只用于本次识别，不会保存',result['reply'])
        self.assertEqual(core.list_memories(self.sid), [])
    def test_image_memory_caption_does_not_create_detached_memory(self):
        class Fake:
            model='test'
            def complete(self, system, user, **kwargs): return '我看到一张蓝色图片。'
        with patch.object(model, 'from_env', return_value=Fake()):
            for text in ('记住：这张图', '记住：这张图，也帮我描述一下'):
                result=main.chat(main.ChatIn(session_id=self.sid,text=text,image_data_url=self.url))
                self.assertIn('图片只用于本次识别，不会保存',result['reply'])
                self.assertNotIn('记下了',result['reply'])
                self.assertEqual(core.list_memories(self.sid), [])
    def test_unsupported_image_reports_failure(self):
        class Fake:
            model='test'
            def complete(self, system, user, **kwargs): raise model.ModelError('model http 400')
        with patch.object(model, 'from_env', return_value=Fake()):
            result=main.chat(main.ChatIn(session_id=self.sid,text='看图片',image_data_url=self.url))
        self.assertEqual(result['action'],'model.image_unavailable')
        self.assertIn('没有识别成功',result['reply'])
    def test_tool_path_preserves_image(self):
        seen=[]
        class Fake:
            def complete_tools(self, messages, tools):
                seen.append(messages[1]['content']); return {'content':'图是蓝色。'}
        out,_=agent_runtime.run(Fake(),'sys','user',user_text='帮我整理资料',has_sources=True,search=lambda q:[],image_data_url=self.url)
        self.assertEqual(out,'图是蓝色。')
        self.assertEqual(seen[0][1]['image_url']['url'],self.url)

if __name__ == '__main__': unittest.main()
