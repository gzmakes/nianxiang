"""An environment-managed model must not pretend file mutations changed it."""
from fastapi.testclient import TestClient
from server import core, main, model_settings


def test_runtime_settings_report_ready_and_reject_inert_file_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB_PATH', str(tmp_path/'runtime.db'))
    monkeypatch.setattr(model_settings, 'PATH', str(tmp_path/'model-settings.json'))
    monkeypatch.setenv('XINJI_MODEL_BASE_URL', 'https://synthetic.example/v1')
    monkeypatch.setenv('XINJI_MODEL_API_KEY', 'synthetic-only-test-credential')
    monkeypatch.setenv('XINJI_MODEL_NAME', 'synthetic-runtime-model')
    core.init_db()
    client=TestClient(main.app)
    settings=client.get('/api/settings/model')
    assert settings.json()['configured'] and settings.json()['managed_by_environment']
    assert 'synthetic-only-test-credential' not in settings.text
    assert client.get('/api/config').json()['model']['configured']
    assert client.post('/api/settings/model',json={
        'base_url':'https://changed.example/v1','model':'changed','api_key':'unused'}).status_code==409
    assert client.post('/api/settings/model/clear').status_code==409
    assert not (tmp_path/'model-settings.json').exists()
    assert client.get('/api/settings/model').json()['model']=='synthetic-runtime-model'
