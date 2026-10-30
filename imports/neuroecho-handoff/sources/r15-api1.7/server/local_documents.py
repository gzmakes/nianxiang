"""Bounded, local-only DOCX extraction for a user-selected preview.

The binary is never saved or sent to a model. Only the preview that the user
subsequently confirms may be attached as a source.
"""
from __future__ import annotations

import base64
import binascii
import io
import zipfile
from xml.etree import ElementTree

from . import local_source

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_XML_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 512
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def extract_docx(data: str) -> dict:
    """Extract up to the confirmed-source character limit from Word body text."""
    if not isinstance(data, str) or not data or len(data) > ((MAX_DOCUMENT_BYTES + 2) // 3) * 4:
        raise ValueError('Word 文件为空或超过 2 MB。')
    try:
        raw = base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError('文件数据格式无效，请重新选择。') from exc
    if not raw or len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError('Word 文件为空或超过 2 MB。')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            documents = [entry for entry in entries if entry.filename == 'word/document.xml']
            if len(entries) > MAX_ENTRIES or len(documents) != 1:
                raise ValueError('Word 文件结构无效或过于复杂。')
            document = documents[0]
            if document.flag_bits & 1 or document.file_size > MAX_XML_BYTES:
                raise ValueError('文档已加密或正文过大，暂无法预览。')
            with archive.open(document) as stream:
                xml = stream.read(MAX_XML_BYTES + 1)
            if len(xml) > MAX_XML_BYTES:
                raise ValueError('文档正文过大，暂无法预览。')
        upper = xml.upper()
        if b'\x00' in xml or b'<!DOCTYPE' in upper or b'<!ENTITY' in upper:
            raise ValueError('文档正文格式不受支持。')
        root = ElementTree.fromstring(xml)
        paragraphs = []
        for paragraph in root.iter(W + 'p'):
            pieces = []
            for node in paragraph.iter():
                if node.tag == W + 't' and node.text:
                    pieces.append(node.text)
                elif node.tag == W + 'tab':
                    pieces.append('\t')
                elif node.tag in (W + 'br', W + 'cr'):
                    pieces.append('\n')
            text = ''.join(pieces).strip()
            if text:
                paragraphs.append(text)
        text = '\n'.join(paragraphs)
        if not text.strip() or '\x00' in text:
            raise ValueError('没有可提取的正文；图片和扫描内容暂不支持。')
        return {'text':text[:local_source.MAX_CHARS],'length':len(text[:local_source.MAX_CHARS]),'extracted_length':len(text),'truncated':len(text)>local_source.MAX_CHARS}
    except (zipfile.BadZipFile, KeyError, RuntimeError, OSError, ElementTree.ParseError) as exc:
        raise ValueError('无法读取 Word 文档，请检查文件是否损坏。') from exc
