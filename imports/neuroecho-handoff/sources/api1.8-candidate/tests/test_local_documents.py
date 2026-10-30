import base64
import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from server import core, local_documents
from server.main import app

WORD_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def document(body, *, duplicate=False, xml=None):
    xml = xml or f'<w:document xmlns:w="{WORD_NS}"><w:body>{body}</w:body></w:document>'
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('word/document.xml', xml)
        if duplicate:
            archive.writestr('word/document.xml', xml)
    return base64.b64encode(out.getvalue()).decode()


def test_extracts_word_body_and_retains_unicode_boundary():
    body = '<w:p><w:r><w:t>' + ('中' * 3999) + '😀后</w:t></w:r></w:p>'
    result = local_documents.extract_docx(document(body))
    assert result['text'] == ('中' * 3999) + '😀'
    assert result['truncated'] is True
    assert result['length']==4000 and result['extracted_length']==4001


@pytest.mark.parametrize('value', ['not-base64!', base64.b64encode(b'not-a-zip').decode(), ''])
def test_malformed_files_fail_without_fallback_text(value):
    with pytest.raises(ValueError):
        local_documents.extract_docx(value)


def test_corrupt_deflate_returns_readable_error():
    data = bytearray(base64.b64decode(document('<w:p><w:r><w:t>sample</w:t></w:r></w:p>')))
    name_length = int.from_bytes(data[26:28], 'little')
    extra_length = int.from_bytes(data[28:30], 'little')
    data[30 + name_length + extra_length] = 0xff
    with pytest.raises(ValueError, match='无法读取 Word 文档'):
        local_documents.extract_docx(base64.b64encode(data).decode())


def test_docx_rejects_duplicate_xml_and_forbidden_entities():
    with pytest.warns(UserWarning):
        duplicate = document('<w:p/>', duplicate=True)
    with pytest.raises(ValueError):
        local_documents.extract_docx(duplicate)
    xml = '<!DOCTYPE doc [<!ENTITY a "boom">]><w:document xmlns:w="' + WORD_NS + '"><w:p><w:t>&a;</w:t></w:p></w:document>'
    with pytest.raises(ValueError):
        local_documents.extract_docx(document('', xml=xml))


@pytest.mark.parametrize('encoding', ['utf-16', 'utf-16-le', 'utf-16-be'])
def test_utf16_declarations_cannot_bypass_entity_guard(encoding):
    xml = ('<!DOCTYPE doc [<!ENTITY a "expanded">]>'
           f'<w:document xmlns:w="{WORD_NS}"><w:p><w:t>&a;</w:t></w:p></w:document>')
    with pytest.raises(ValueError):
        local_documents.extract_docx(document('', xml=xml.encode(encoding)))


def test_compressed_oversized_document_body_is_not_decompressed():
    oversized = document('', xml='<root>' + ('a' * local_documents.MAX_XML_BYTES) + '</root>')
    with pytest.raises(ValueError, match='正文过大'):
        local_documents.extract_docx(oversized)


def test_selected_word_is_previewed_locally_without_model_or_persistence(monkeypatch):
    core.init_db()
    sid = core.create_session('empty')['session']['id']
    monkeypatch.setattr(core.model, 'from_env', lambda: pytest.fail('preview must not call model'))
    data = document('<w:p><w:r><w:t>合成资料</w:t></w:r></w:p>')
    with TestClient(app) as client:
        preview = client.post('/api/local-files/preview-document', json={'name':'示例.docx','data':data})
        assert preview.status_code == 200
        assert preview.json()['text'] == '合成资料'
        assert core.list_sources(sid) == []
        assert client.post('/api/local-files/preview-document', json={'name':'../示例.docx','data':data}).status_code == 400
        assert client.post('/api/local-files/preview-document', headers={'origin':'https://evil.example'}, json={'name':'示例.docx','data':data}).status_code == 403
        saved = client.post('/api/local-files/confirm', json={'session_id':sid,'files':[{'name':'示例.docx','text':preview.json()['text']}]})
        assert saved.status_code == 200
        assert len(core.list_sources(sid)) == 1


def test_blank_or_image_only_document_is_not_misrepresented_as_text():
    with pytest.raises(ValueError, match='没有可提取的正文'):
        local_documents.extract_docx(document('<w:p><w:r><w:drawing/></w:r></w:p>'))
