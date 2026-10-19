"""Settings from .env: defaults, mode lists and QUERY_EXTRA_PARAMS."""
import pytest

from app.config import Settings, key_state


def test_defaults_are_generic():
    s = Settings.from_env()
    assert s.lightrag_url == "http://lightrag:9621"
    assert s.query_modes == ["mix", "hybrid", "local", "global", "naive"] and s.default_mode == "hybrid"
    assert s.enable_insert is True and s.kb_description == "" and s.auth_token == ""
    assert s.port == 8700


def test_url_loses_its_trailing_slash(monkeypatch):
    monkeypatch.setenv("LIGHTRAG_URL", "http://kb.example:9621/ ")
    assert Settings.from_env().lightrag_url == "http://kb.example:9621"


def test_modes_can_be_narrowed(monkeypatch):
    monkeypatch.setenv("QUERY_MODES", " Hybrid , naive ")
    monkeypatch.setenv("DEFAULT_MODE", "naive")
    s = Settings.from_env()
    assert s.query_modes == ["hybrid", "naive"] and s.default_mode == "naive"


@pytest.mark.parametrize("modes,default", [("hybrid,fast", "hybrid"), (" , ", "hybrid"), ("local,global", "hybrid")])
def test_bad_modes_stop_start_up(monkeypatch, modes, default):
    monkeypatch.setenv("QUERY_MODES", modes)
    monkeypatch.setenv("DEFAULT_MODE", default)
    with pytest.raises(ValueError):
        Settings.from_env()


def test_extra_params_are_parsed(monkeypatch):
    monkeypatch.setenv("QUERY_EXTRA_PARAMS", '{"top_k": 40, "response_type": "Bullet Points"}')
    assert Settings.from_env().query_extra_params == {"top_k": 40, "response_type": "Bullet Points"}


@pytest.mark.parametrize("raw", ['[1, 2]', '{"mode": "naive"}', '{"query": "x"}', "{not json"])
def test_bad_extra_params_stop_start_up(monkeypatch, raw):
    monkeypatch.setenv("QUERY_EXTRA_PARAMS", raw)
    with pytest.raises(ValueError):            # json.JSONDecodeError is a ValueError
        Settings.from_env()


@pytest.mark.parametrize("value,expected", [("false", False), ("0", False), ("no", False), ("TRUE", True), ("1", True)])
def test_enable_insert(monkeypatch, value, expected):
    monkeypatch.setenv("ENABLE_INSERT", value)
    assert Settings.from_env().enable_insert is expected


@pytest.mark.parametrize("key,state", [
    ("", "empty"),
    ("change-me", "placeholder"),                      # the value in .env.example
    ("xxxxxxxxxxxxxxxx", "placeholder"),
    ("YOUR_API_KEY", "placeholder"),
    ("test-key-not-real-0123456789", "set"),
])
def test_key_state(key, state):
    assert key_state(key) == state


def test_secrets_are_not_in_repr(monkeypatch):
    monkeypatch.setenv("LIGHTRAG_API_KEY", "test-key-not-real-0123")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token-not-real")
    text = repr(Settings.from_env())
    assert "test-key-not-real" not in text and "test-token-not-real" not in text
