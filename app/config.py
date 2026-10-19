"""Settings from environment (.env). The API key is never returned to a caller."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

# retrieval modes of LightRAG's POST /query ("bypass" skips retrieval, so it is left out by default)
KNOWN_MODES = ("mix", "hybrid", "local", "global", "naive", "bypass")
# request fields the tool always sets itself; QUERY_EXTRA_PARAMS may not replace them
_RESERVED_QUERY_PARAMS = {"query", "mode", "stream"}
# the dummy values shipped in .env.example (change-me, xxxx…) - never a real key
_PLACEHOLDER_KEY = re.compile(r"x{6,}|change-?me|your[-_ ]?(api[-_ ]?)?key", re.I)


def key_state(key: str) -> str:
    """"empty", "placeholder" (still the value copied from .env.example) or "set"."""
    if not key:
        return "empty"
    return "placeholder" if _PLACEHOLDER_KEY.search(key) else "set"


def _f(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _modes() -> tuple[list[str], str]:
    """QUERY_MODES (the choices offered to the agent) and DEFAULT_MODE (used when it picks none)."""
    modes = [m.strip().lower() for m in os.getenv("QUERY_MODES", "mix,hybrid,local,global,naive").split(",")
             if m.strip()]
    unknown = [m for m in modes if m not in KNOWN_MODES]
    if not modes or unknown:
        raise ValueError(f"QUERY_MODES must list modes from {KNOWN_MODES}, got {unknown or 'nothing'}")
    default = os.getenv("DEFAULT_MODE", "hybrid").strip().lower() or "hybrid"
    if default not in modes:
        raise ValueError(f"DEFAULT_MODE {default!r} is not one of QUERY_MODES {modes}")
    return modes, default


def _extra_params() -> dict:
    """QUERY_EXTRA_PARAMS: a JSON object merged into every /query request, for LightRAG options this
    tool does not model itself (top_k, chunk_top_k, response_type, user_prompt, enable_rerank...)."""
    raw = os.getenv("QUERY_EXTRA_PARAMS", "").strip()
    if not raw:
        return {}
    extra = json.loads(raw)
    if not isinstance(extra, dict):
        raise ValueError("QUERY_EXTRA_PARAMS must be a JSON object, e.g. {\"top_k\": 40}")
    clash = _RESERVED_QUERY_PARAMS & extra.keys()
    if clash:
        raise ValueError(f"QUERY_EXTRA_PARAMS may not set {sorted(clash)} - use QUERY_MODES / DEFAULT_MODE")
    return extra


@dataclass(frozen=True)
class Settings:
    lightrag_url: str
    lightrag_api_key: str = field(repr=False)
    query_modes: list[str]
    default_mode: str
    query_timeout: float
    insert_timeout: float
    query_extra_params: dict
    enable_insert: bool
    kb_description: str
    host: str
    port: int
    auth_token: str = field(repr=False)

    @staticmethod
    def from_env() -> "Settings":
        modes, default = _modes()
        return Settings(
            lightrag_url=os.getenv("LIGHTRAG_URL", "http://lightrag:9621").strip().rstrip("/"),
            lightrag_api_key=os.getenv("LIGHTRAG_API_KEY", "").strip(),
            query_modes=modes,
            default_mode=default,
            query_timeout=_f("QUERY_TIMEOUT_SECONDS", "120"),
            insert_timeout=_f("INSERT_TIMEOUT_SECONDS", "60"),
            query_extra_params=_extra_params(),
            enable_insert=_bool("ENABLE_INSERT", "true"),
            kb_description=os.getenv("KB_DESCRIPTION", "").strip(),
            host=os.getenv("MCP_HOST", "0.0.0.0"),
            port=int(_f("MCP_PORT", "8700")),
            auth_token=os.getenv("MCP_AUTH_TOKEN", "").strip(),
        )
