"""测试隔离：不要读本机真实模型设置/凭证，避免测试调用外网。"""
import pytest

from server import core, model_settings


@pytest.fixture(autouse=True)
def isolate_local_database(tmp_path, monkeypatch):
    # Some lifecycle/origin tests do not define their own DB fixture. Even those
    # must never acquire the user's live database lease or migrate real data.
    # More specific test fixtures may still replace this path deliberately.
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "isolated-test.db"))


@pytest.fixture(autouse=True)
def isolate_local_model(tmp_path, monkeypatch):
    monkeypatch.setattr(model_settings, "PATH", str(tmp_path / "model-settings.json"))
    for key in ("XINJI_MODEL_BASE_URL", "XINJI_MODEL_API_KEY", "XINJI_MODEL_NAME"):
        monkeypatch.delenv(key, raising=False)
    # 关掉公共演示节点，测试不依赖外网；需要它的用例自行设回。
    monkeypatch.setenv("XINJI_MODEL_PUBLIC", "0")


@pytest.fixture
def legacy_schema_without_changes():
    """Old-schema fixtures must not retain newly introduced R14 triggers."""
    def remove(conn):
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'cc_v1_*'").fetchall():
            conn.execute('DROP TRIGGER "'+name.replace('"','""')+'"')
        conn.execute('DROP TABLE IF EXISTS conversation_change_domains')
        conn.execute('DROP TABLE IF EXISTS conversation_change_clock')
    return remove
