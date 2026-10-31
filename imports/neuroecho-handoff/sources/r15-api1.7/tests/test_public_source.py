import unittest
from unittest.mock import patch

from server import public_source as source


class PublicSourceTests(unittest.TestCase):
    def test_public_jike_body_is_not_account_login(self):
        html = '<html><head><title>公开动态</title></head><body><div class="text"><div>这是一个真实公开网页中可以看到的动态内容。</div></div></body></html>'
        with patch.object(source, '_fetch', return_value=html):
            result = source.read('https://m.okjike.com/originalPosts/67a4126c887087ba04e42f71?token=private')
        self.assertTrue(result['ok'])
        self.assertEqual(result['source'], 'jike')
        self.assertEqual(result['text'], '这是一个真实公开网页中可以看到的动态内容。')
        self.assertNotIn('token', result['url'])
        self.assertEqual(result['connector']['mode'], 'public-readonly')
        self.assertFalse(result['synthetic'])

    def test_waytoagi_question_extracts_only_selected_content(self):
        html = '<title>如何登录 WaytoAGI</title><header>无关导航</header><div class="max-w-5xl"><h1>提问</h1><div class="markdown-body"><p>这是 WaytoAGI 问答的公开正文。</p><script>泄漏内容</script></div><div>其他人在问：不属于这篇回答的推荐问题</div></div>'
        with patch.object(source, '_fetch', return_value=html):
            result = source.read('https://www.waytoagi.com/zh/question/94437')
        self.assertTrue(result['ok'])
        self.assertEqual(result['title'], '如何登录 WaytoAGI')
        self.assertIn('WaytoAGI', result['text'])
        self.assertNotIn('无关导航', result['text'])
        self.assertNotIn('泄漏内容', result['text'])
        self.assertNotIn('其他人在问', result['text'])

    def test_refuses_login_or_empty_shell(self):
        for html in ('<title>登录</title><div class="text">请先登录以查看这篇公开内容。</div>',
                     '<title>即刻</title><div class="text">请先登录以查看这篇公开内容。</div>',
                     '<title>即刻</title><div>页面壳，没有正文</div>'):
            with self.subTest(html=html), patch.object(source, '_fetch', return_value=html):
                self.assertFalse(source.read('https://m.okjike.com/originalPosts/67a4126c887087ba04e42f71')['ok'])

    def test_no_unapproved_hosts_paths_or_ports(self):
        invalid = ['http://about.waytoagi.com/', 'https://about.waytoagi.com.evil.test/',
                   'https://about.waytoagi.com@127.0.0.1/', 'https://about.waytoagi.com:444/',
                   'https://m.okjike.com/', 'https://www.waytoagi.com/zh/question/../admin',
                   'https://m.okjike.com/originalPosts/abc']
        with patch.object(source, '_fetch') as fetch:
            for url in invalid:
                with self.subTest(url=url):
                    self.assertFalse(source.read(url)['ok'])
            fetch.assert_not_called()

    def test_wrong_selected_platform_is_rejected_before_fetch(self):
        with patch.object(source, '_fetch') as fetch:
            result = source.read('https://m.okjike.com/originalPosts/67a4126c887087ba04e42f71',
                                 expected_source='waytoagi')
        self.assertFalse(result['ok'])
        self.assertEqual(result['error_code'], 'source_url_mismatch')
        fetch.assert_not_called()

    def test_rejects_private_dns_and_mixed_answers(self):
        with patch.object(source.socket, 'getaddrinfo', return_value=[
                (2, 1, 6, '', ('8.8.8.8', 443)), (2, 1, 6, '', ('127.0.0.1', 443))]):
            with self.assertRaises(ValueError):
                source._public_address('about.waytoagi.com')

    def test_truncation_is_explicit(self):
        html = '<title>标题</title><main><p>' + ('内容' * 7000) + '</p></main>'
        with patch.object(source, '_fetch', return_value=html):
            result = source.read('https://about.waytoagi.com/')
        self.assertEqual(result['length'], 12000)
        self.assertEqual(result['extracted_length'], 14000)
        self.assertTrue(result['truncated'])

    def test_redirect_and_non_html_rejected(self):
        class FakeResponse:
            status = 302
            def getheader(self, name): return 'text/html'
        class FakeConnection:
            def __init__(self, *args): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return FakeResponse()
            def close(self): pass
        with patch.object(source, '_public_address', return_value='8.8.8.8'), patch.object(source, '_PinnedHTTPS', FakeConnection):
            self.assertFalse(source.read('https://about.waytoagi.com/')['ok'])


if __name__ == '__main__':
    unittest.main()
