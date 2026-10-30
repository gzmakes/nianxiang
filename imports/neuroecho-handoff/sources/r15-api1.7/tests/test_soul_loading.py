from server import prompts


def test_persona_changes_are_read_on_each_model_request(tmp_path, monkeypatch):
    path = tmp_path / 'SOUL.md'
    monkeypatch.setattr(prompts, 'SOUL_PATH', path)
    path.write_text('温柔但不假装了解。', encoding='utf-8')
    first = prompts.system_prompt()
    assert prompts.SYSTEM_PROMPT in first and '温柔但不假装了解。' in first
    path.write_text('认真一点。', encoding='utf-8')
    second = prompts.system_prompt()
    assert '认真一点。' in second and '温柔但不假装了解。' not in second
    assert '安全、授权、真实性规则' in second


def test_missing_empty_invalid_or_oversized_soul_falls_back_to_guardrails(tmp_path, monkeypatch):
    path = tmp_path / 'SOUL.md'
    monkeypatch.setattr(prompts, 'SOUL_PATH', path)
    assert prompts.system_prompt() == prompts.SYSTEM_PROMPT
    path.write_text('', encoding='utf-8')
    assert prompts.system_prompt() == prompts.SYSTEM_PROMPT
    path.write_bytes(b'\xff')
    assert prompts.system_prompt() == prompts.SYSTEM_PROMPT
    path.write_bytes(b'x' * (prompts.MAX_SOUL_BYTES + 1))
    assert prompts.system_prompt() == prompts.SYSTEM_PROMPT


def test_chat_model_gets_current_persona_each_turn(tmp_path, monkeypatch):
    from server import core
    from server.main import app
    from fastapi.testclient import TestClient
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path / 'chat.db'))
    path = tmp_path / 'SOUL.md'
    monkeypatch.setattr(prompts, 'SOUL_PATH', path)
    core.init_db()
    captured = []
    class Fake:
        model = 'synthetic'
        def complete(self, system, user):
            captured.append(system)
            return '我在听。'
    monkeypatch.setattr(core.model, 'from_env', lambda: Fake())
    client = TestClient(app)
    sid = client.post('/api/session', json={'mode': 'sample'}).json()['session']['id']
    path.write_text('人格版本一', encoding='utf-8')
    assert client.post('/api/chat', json={'session_id': sid, 'text': '今天很累'}).status_code == 200
    path.write_text('人格版本二', encoding='utf-8')
    assert client.post('/api/chat', json={'session_id': sid, 'text': '想休息一下'}).status_code == 200
    assert len(captured) == 2
    assert '人格版本一' in captured[0] and '人格版本二' in captured[1]
