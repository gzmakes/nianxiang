"""Explicit, unauthenticated reads of selected public WaytoAGI and 即刻 pages.

Never follows redirects or loads page resources. This is not account linking.
"""
from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
from html.parser import HTMLParser
from urllib.parse import urlsplit

TIMEOUT = 8
MAX_BYTES = 1024 * 1024
MAX_CHARS = 12000
_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
_SKIP = {'script', 'style', 'noscript', 'svg', 'nav', 'header', 'footer', 'aside', 'form'}
_BLOCK = {'p', 'div', 'h1', 'h2', 'h3', 'h4', 'li', 'br', 'section', 'article'}


def _validate(raw: str) -> tuple[str, str, str]:
    if not isinstance(raw, str) or len(raw) > 2048:
        raise ValueError('链接格式不正确')
    u = urlsplit(raw.strip())
    if u.scheme != 'https' or not u.hostname or u.username or u.password or u.port not in (None, 443):
        raise ValueError('只支持官方 HTTPS 链接')
    host, path = u.hostname.lower(), u.path or '/'
    if host == 'about.waytoagi.com' and path == '/':
        platform = 'waytoagi'
    elif host == 'www.waytoagi.com' and re.fullmatch(r'/zh/question/[0-9]{1,20}/?', path):
        platform = 'waytoagi'
    elif host == 'm.okjike.com' and re.fullmatch(r'/originalPosts/[0-9a-fA-F]{24}/?', path):
        platform = 'jike'
    else:
        raise ValueError('暂不支持此链接，请使用 WaytoAGI 问答页或即刻公开动态链接')
    # Discard all query parameters and fragments, which can contain tracking or private tokens.
    return platform, host, path


def _public_address(host: str) -> str:
    addresses = {x[4][0].split('%')[0] for x in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(addr).is_global for addr in addresses):
        raise ValueError('目标地址不安全，无法读取')
    return sorted(addresses)[0]


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str):
        super().__init__(host, timeout=TIMEOUT, context=ssl.create_default_context())
        self._address = address

    def connect(self):
        raw = socket.create_connection((self._address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _fetch(host: str, path: str) -> str:
    conn = _PinnedHTTPS(host, _public_address(host))
    try:
        conn.request('GET', path, headers={'User-Agent': 'Nianxiang/1.0 (public source reader)',
                                          'Accept': 'text/html', 'Accept-Encoding': 'identity'})
        res = conn.getresponse()
        if 300 <= res.status < 400:
            raise ValueError('页面发生跳转，暂不支持读取')
        if res.status in (401, 403):
            raise ValueError('页面需要登录或拒绝公开访问')
        if res.status != 200:
            raise ValueError('公开页面暂时无法读取')
        if 'text/html' not in (res.getheader('Content-Type') or '').lower():
            raise ValueError('返回内容不是网页')
        raw = res.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('页面过大，无法安全读取')
        return raw.decode('utf-8', errors='replace')
    finally:
        conn.close()


class _Extract(HTMLParser):
    def __init__(self, platform: str, host: str):
        super().__init__(convert_charrefs=True)
        self.platform, self.host = platform, host
        self.depth = 0
        self.inside = None
        self.skip = 0
        self.done = False
        self.title_depth = None
        self.title_done = False
        self.title_parts = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'title' and not self.title_done:
            self.title_depth = self.depth
        if not self.done and self.inside is None:
            classes = set((attrs.get('class') or '').split())
            found = ((self.host == 'about.waytoagi.com' and tag == 'main') or
                     (self.host == 'www.waytoagi.com' and tag == 'div' and 'markdown-body' in classes) or
                     (self.platform == 'jike' and tag == 'div' and 'text' in classes))
            if found:
                self.inside = self.depth
        if self.inside is not None:
            if tag in _SKIP:
                self.skip += 1
            elif not self.skip and tag in _BLOCK:
                self.parts.append('\n')
        if tag not in _VOID:
            self.depth += 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag not in _VOID:
            self.depth = max(0, self.depth - 1)
        if self.title_depth == self.depth and tag == 'title':
            self.title_depth = None
            self.title_done = True
        if self.inside is not None:
            if tag in _SKIP and self.skip:
                self.skip -= 1
            if self.depth == self.inside:
                self.inside = None
                self.done = True

    def handle_data(self, data):
        if self.title_depth is not None:
            self.title_parts.append(data)
        if self.inside is not None and not self.skip:
            self.parts.append(data)


def _extract(html: str, platform: str, host: str) -> tuple[str, str]:
    parser = _Extract(platform, host)
    parser.feed(html)
    title = ' '.join(''.join(parser.title_parts).split())[:160]
    lines = [re.sub(r'\s+', ' ', x).strip() for x in ''.join(parser.parts).splitlines()]
    body = '\n'.join(x for x in lines if x)
    # Login and bot challenge screens are not useful article content.
    title_lower = title.lower()
    if any(term in title_lower for term in ('just a moment', 'access denied', '安全验证', '验证您是人类')) or re.fullmatch(r'(请先)?登录(?:\s*[-|·]\s*[^ ]+)?', title_lower):
        raise ValueError('页面需要登录或安全验证，无法读取公开正文')
    if re.search(r'^(请先登录|登录后查看|请完成安全验证|verify you are human|checking your browser|enable javascript)', body, re.I):
        raise ValueError('页面需要登录或安全验证，无法读取公开正文')
    if not parser.done or len(body) < 15:
        raise ValueError('没有读取到公开正文，页面可能不可用或需要登录')
    return title or ('即刻公开动态' if platform == 'jike' else 'WaytoAGI 公开页面'), body


def read(url: str, *, expected_source: str | None = None) -> dict:
    try:
        platform, host, path = _validate(url)
        if expected_source is not None and platform != expected_source:
            return {'ok': False, 'error_code': 'source_url_mismatch',
                    'error': '链接不属于所选平台，请重新核对。'}
        page = _fetch(host, path)
        title, body = _extract(page, platform, host)
    except (ValueError, OSError, http.client.HTTPException) as exc:
        message = str(exc) if isinstance(exc, ValueError) else '网络异常或读取超时'
        return {'ok': False, 'error': message, 'hint': '请确认链接公开可访问，再重试'}
    link = f'https://{host}{path}'
    text = body[:MAX_CHARS]
    name = '即刻公开动态' if platform == 'jike' else 'WaytoAGI 公开页面'
    return {'ok': True, 'source': platform, 'synthetic': False, 'title': title, 'url': link,
            'text': text, 'length': len(text), 'extracted_length': len(body), 'truncated': len(body) > MAX_CHARS,
            'connector': {'id': platform, 'name': name, 'category': '公开资料', 'icon': '文',
                          'blurb': '公开页面，只读；没有连接个人账号', 'reads': ['公开正文'],
                          'scopes': [], 'mode': 'public-readonly'},
            'items': [{'type': 'public_page', 'title': title, 'meta': name, 'summary': text[:200], 'url': link}],
            'understanding': {'facts': [text[:200]], 'inferences': [], 'questions': []},
            'insights': [], 'starters': ['帮我总结这份公开资料', '这份资料有哪些重点？']}
