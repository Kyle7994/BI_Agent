import importlib
import app.config as config

def test_config_defaults(monkeypatch):
    monkeypatch.delenv("MYSQL_HOST", raising=False)
    monkeypatch.delenv("MYSQL_PORT", raising=False)
    monkeypatch.delenv("ENABLE_ADMIN_OPS", raising=False)

    importlib.reload(config)

    assert config.MYSQL_HOST == "mysql"
    assert config.MYSQL_PORT == 3306
    assert config.ENABLE_ADMIN_OPS is False

def test_config_env_override(monkeypatch):
    monkeypatch.setenv("MYSQL_HOST", "127.0.0.1")
    monkeypatch.setenv("MYSQL_PORT", "3307")
    monkeypatch.setenv("ENABLE_ADMIN_OPS", "true")

    importlib.reload(config)

    assert config.MYSQL_HOST == "127.0.0.1"
    assert config.MYSQL_PORT == 3307
    assert config.ENABLE_ADMIN_OPS is True