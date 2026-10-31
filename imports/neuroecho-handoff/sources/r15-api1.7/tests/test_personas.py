import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from server import core, prompts
from server.main import app


def test_manifest_is_exactly_two_public_personas():
    data = prompts.persona_manifest()
    assert [item['id'] for item in data] == ['nianxiang', 'whale']
    assert prompts.normalize_persona_id('../SOUL.md') == 'nianxiang'


def test_selected_persona_prompt_does_not_hardcode_nianxiang_identity():
    rendered = prompts.system_prompt('whale')
    assert '你是当前会话选定的具身伙伴。' in rendered
    assert '你是「念响」的具身伙伴。' not in rendered
    assert '小鲸鱼' in rendered


def test_whale_backup_is_byte_identical():
    root = Path(__file__).parents[1]
    backup = root / 'personas' / 'whale' / 'SOUL.md'
    assert backup.stat().st_size == 17773
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == '1a649d503c14d437d309c88ba80cf04e08469f50dd8d041ed021d1e35762c317'


def test_new_session_and_persona_switch_persist(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'persona.db'))
    core.init_db()
    with TestClient(app) as client:
        response = client.post('/api/session', json={'mode': 'empty'})
        assert response.status_code == 200
        sid = response.json()['session']['id']
        assert response.json()['session']['persona_id'] == 'nianxiang'
        switched = client.put(f'/api/session/{sid}/persona', json={'persona_id': 'whale'})
        assert switched.status_code == 200
        assert switched.json()['persona_id'] == 'whale'
        loaded = client.get(f'/api/session/{sid}').json()
        assert loaded['session']['persona_id'] == 'whale'
        assert loaded['messages'][0]['persona_id'] == 'nianxiang'
        assert client.put(f'/api/session/{sid}/persona', json={'persona_id': 'nianxiang'}).status_code == 200
        assert client.get(f'/api/session/{sid}').json()['messages']
