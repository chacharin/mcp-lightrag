"""Shared fixtures. No test calls a real LightRAG: lightrag.transport is replaced by an httpx.MockTransport."""
from __future__ import annotations

import importlib

import httpx
import pytest

TEST_KEY = "test-key-not-real-0123"
ENV_KEYS = ["LIGHTRAG_URL", "LIGHTRAG_API_KEY", "QUERY_MODES", "DEFAULT_MODE", "QUERY_TIMEOUT_SECONDS",
            "INSERT_TIMEOUT_SECONDS", "QUERY_EXTRA_PARAMS", "ENABLE_INSERT", "ENABLE_DELETE", "KB_DESCRIPTION",
            "MCP_HOST", "MCP_PORT", "MCP_AUTH_TOKEN"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Every test starts from the code defaults."""
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LIGHTRAG_API_KEY", TEST_KEY)      # required; tests that need another key set their own


@pytest.fixture
def fake_lightrag(monkeypatch):
    """fake_lightrag(handler): handler(httpx.Request) -> httpx.Response; returns the list of requests seen."""
    from app import lightrag

    def install(handler):
        seen = []

        def record(request):
            seen.append(request)
            return handler(request)

        monkeypatch.setattr(lightrag, "transport", httpx.MockTransport(record))
        return seen

    return install


@pytest.fixture
def load_server(monkeypatch):
    """load_server(**env): (re)import app.server with these environment variables."""
    def load(**env):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        import app.server
        return importlib.reload(app.server)

    return load
