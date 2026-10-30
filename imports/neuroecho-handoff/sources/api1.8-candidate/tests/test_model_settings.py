"""本机模型设置（数据页配置，不落仓库）。"""
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from server import core, model, model_settings
from server.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(model_settings, "PATH", str(tmp_path / "model-settings.json"))
    for k in ("XINJI_MODEL_BASE_URL", "XINJI_MODEL_API_KEY", "XINJI_MODEL_NAME", "XINJI_MODEL_TIMEOUT"):
        monkeypatch.delenv(k, raising=False)
    core.init_db()
    return TestClient(app)


def test_save_settings_enables_model(client):
    s = client.get("/api/settings/model").json()
    assert s["configured"] is False
    assert s["managed_by_environment"] is False

    r = client.post("/api/settings/model", json={
        "base_url": "https://api.example.com/v1", "api_key": "sk-test", "model": "demo-model"
    }).json()
    assert r["configured"] is True and r["has_key"] is True
    assert "sk-test" not in str(r)  # 不回显 key

    cfg = client.get("/api/config").json()
    assert cfg["model"]["mode"] == "model"


def test_clear_settings(client, tmp_path):
    client.post("/api/settings/model", json={"base_url": "https://x/v1", "api_key": "k", "model": "m"})
    client.post("/api/settings/model/clear")
    cfg = client.get("/api/config").json()
    assert cfg["model"]["mode"] == "rule"
    assert client.get("/api/settings/model").json()["managed_by_environment"] is False


def test_connection(client, monkeypatch):
    from server import model as m

    class Fake:
        model = "demo-model"
        def complete(self, system, user):
            return "OK"
    monkeypatch.setattr(model, "from_env", lambda: Fake())
    r = client.post("/api/settings/model/test").json()
    assert r["ok"] is True and r["latency_ms"] >= 0

    monkeypatch.setattr(model, "from_env", lambda: None)
    r = client.post("/api/settings/model/test").json()
    assert r["ok"] is False


def test_runtime_environment_is_reported_without_saving_or_echoing_key(client, monkeypatch):
    monkeypatch.setenv("XINJI_MODEL_BASE_URL", " https://runtime.example.invalid/v1/ ")
    monkeypatch.setenv("XINJI_MODEL_API_KEY", " synthetic-runtime-private-key ")
    monkeypatch.setenv("XINJI_MODEL_NAME", " runtime-model ")
    monkeypatch.setenv("XINJI_MODEL_TIMEOUT", "11.5")
    result = client.get("/api/settings/model").json()
    runtime = model.from_env()
    assert result == {"configured": True, "base_url": runtime.base_url, "model": runtime.model,
                      "has_key": True, "timeout": runtime.timeout, "managed_by_environment": True}
    assert client.get("/api/config").json()["model"]["configured"] is True
    assert "synthetic-runtime-private-key" not in repr(result)
    assert "api_key" not in result
    assert not Path(model_settings.PATH).exists()


@pytest.mark.parametrize("variable,value", [
    ("XINJI_MODEL_BASE_URL", "https://file.example.invalid/v2/"),
    ("XINJI_MODEL_API_KEY", "synthetic-runtime-private-key"),
    ("XINJI_MODEL_NAME", "runtime-model"),
])
def test_runtime_overrides_merge_with_file_exactly_like_model_client(client, monkeypatch, variable, value):
    model_settings.save("https://file.example.invalid/v1", "synthetic-file-private-key", "file-model", 9)
    monkeypatch.setenv(variable, value)
    result = model_settings.redacted()
    runtime = model.from_env()
    assert result["configured"] is True and result["has_key"] is True
    assert result["managed_by_environment"] is True
    assert (result["base_url"], result["model"], result["timeout"]) == (runtime.base_url, runtime.model, runtime.timeout)
    assert "synthetic-runtime-private-key" not in repr(result)
    assert "synthetic-file-private-key" not in repr(result)


@pytest.mark.parametrize("destination", ["https://different.example.invalid/v1", "http://file.example.invalid/v1",
                                          "https://file.example.invalid:444/v1", "not-a-url"])
def test_changing_environment_destination_never_reuses_saved_key(client, monkeypatch, destination):
    model_settings.save("https://file.example.invalid/v1", "synthetic-file-private-key", "file-model", 9)
    monkeypatch.setenv("XINJI_MODEL_BASE_URL", destination)
    result = model_settings.redacted()
    assert result["configured"] is False and result["has_key"] is False
    assert model.from_env() is None
    assert "synthetic-file-private-key" not in repr(result)
    monkeypatch.setenv("XINJI_MODEL_API_KEY", "synthetic-new-key")
    if model_settings.is_safe_model_url(destination):
        assert model.from_env().api_key == "synthetic-new-key"
    else:
        assert model.from_env() is None


def test_partial_environment_can_have_key_without_being_configured(client, monkeypatch):
    monkeypatch.setenv("XINJI_MODEL_API_KEY", "synthetic-runtime-private-key")
    result = client.get("/api/settings/model").json()
    assert result["configured"] is False and result["has_key"] is True
    assert result["managed_by_environment"] is True
    assert model.from_env() is None
    assert "synthetic-runtime-private-key" not in repr(result)


def test_blank_model_overrides_are_not_managed_and_timeout_alone_is_not_managed(client, monkeypatch):
    for name in ("XINJI_MODEL_BASE_URL", "XINJI_MODEL_API_KEY", "XINJI_MODEL_NAME"):
        monkeypatch.setenv(name, "  ")
    monkeypatch.setenv("XINJI_MODEL_TIMEOUT", "3.5")
    assert model_settings.environment_managed() is False
    result = model_settings.redacted()
    assert result["managed_by_environment"] is False and result["timeout"] == 3.5


def test_invalid_runtime_timeout_uses_same_default_as_model_client(client, monkeypatch):
    model_settings.save("https://file.example.invalid/v1", "synthetic-key", "file-model", 9)
    monkeypatch.setenv("XINJI_MODEL_TIMEOUT", "not-a-number")
    assert model_settings.redacted()["timeout"] == model.from_env().timeout == model_settings.DEFAULT_TIMEOUT


def test_new_configuration_defaults_to_40_seconds_and_existing_timeout_is_preserved(client):
    payload = {"base_url": "https://example.invalid/v1", "model": "synthetic", "api_key": "synthetic"}
    assert client.post('/api/settings/model', json=payload).json()['timeout'] == 40
    assert model.from_env().timeout == 40
    assert client.post('/api/settings/model', json={**payload, 'timeout': 12.5}).json()['timeout'] == 12.5
    assert client.post('/api/settings/model', json={**payload, 'api_key': ''}).json()['timeout'] == 12.5
    assert model.from_env().timeout == 12.5


def test_runtime_timeout_override_is_preserved(client, monkeypatch):
    monkeypatch.setenv('XINJI_MODEL_TIMEOUT', '17.5')
    payload = {"base_url": "https://example.invalid/v1", "model": "synthetic", "api_key": "synthetic"}
    assert client.post('/api/settings/model', json=payload).json()['timeout'] == 17.5
    assert model.from_env().timeout == 17.5


def test_changing_model_service_requires_new_key(client):
    first = {"base_url": "https://one.example/v1", "model": "a", "api_key": "synthetic-original"}
    assert client.post('/api/settings/model', json=first).status_code == 200
    changed = {"base_url": "https://two.example/v1", "model": "b", "api_key": ""}
    result = client.post('/api/settings/model', json=changed)
    assert result.status_code == 400
    assert '输入新服务对应的 API Key' in result.json()['detail']
    assert model.from_env().base_url == first['base_url']
    assert model.from_env().api_key == first['api_key']
    assert client.post('/api/settings/model', json={**changed, 'api_key': 'synthetic-new'}).status_code == 200
    assert model.from_env().api_key == 'synthetic-new'


def test_same_service_can_keep_key_when_only_path_or_default_port_changes(client):
    first = {"base_url": "https://ONE.example/v1", "model": "a", "api_key": "synthetic-original"}
    assert client.post('/api/settings/model', json=first).status_code == 200
    result = client.post('/api/settings/model', json={"base_url":"https://one.example:443/v2", "model":"b", "api_key":""})
    assert result.status_code == 200
    assert model.from_env().api_key == 'synthetic-original'


@pytest.mark.parametrize('url', ['nonsense', 'ftp://example.com/v1', 'https://user:pass@example.com/v1',
                                  'https://example.com/v1?key=secret', 'https://example.com/v1#fragment',
                                  'https://example.com:invalid/v1'])
def test_invalid_model_service_address_rejected_without_saved_configuration(client, url):
    result = client.post('/api/settings/model', json={'base_url':url, 'model':'a', 'api_key':'synthetic'})
    assert result.status_code == 400
    assert client.get('/api/settings/model').json()['configured'] is False
