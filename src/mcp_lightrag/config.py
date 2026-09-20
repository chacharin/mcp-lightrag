"""Runtime settings for mcp-lightrag.

Every field here can be set by environment variable (see plan.md section 3
and .env.example) or overridden by the matching CLI flag in cli.py. A CLI
flag always wins over the environment when both are given; unset flags fall
through to whatever Settings resolves from the environment on its own.
"""

from __future__ import annotations

import argparse
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    lightrag_url: str = Field(
        default="http://localhost:9621", validation_alias="LIGHTRAG_URL"
    )
    lightrag_api_key: str = Field(default="", validation_alias="LIGHTRAG_API_KEY")
    lightrag_username: str = Field(default="", validation_alias="LIGHTRAG_USERNAME")
    lightrag_password: str = Field(default="", validation_alias="LIGHTRAG_PASSWORD")

    timeout: float = Field(default=30.0, validation_alias="LIGHTRAG_TIMEOUT")
    query_timeout: float = Field(
        default=180.0, validation_alias="LIGHTRAG_QUERY_TIMEOUT"
    )
    upload_timeout: float = Field(
        default=300.0, validation_alias="LIGHTRAG_UPLOAD_TIMEOUT"
    )

    verify_ssl: bool = Field(default=True, validation_alias="LIGHTRAG_VERIFY_SSL")

    server_name: str = Field(default="lightrag", validation_alias="MCP_SERVER_NAME")
    transport: Literal["stdio", "streamable-http"] = Field(
        default="stdio", validation_alias="MCP_TRANSPORT"
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", validation_alias="LOG_LEVEL"
    )

    # Phase 7 (plan.md section 7.3.2): classification-tier labelling and
    # audit logging. Both are plain env-var settings only -- plan.md does
    # not call for CLI flags for these two, unlike every field above.
    mcp_classification_label: str = Field(
        default="", validation_alias="MCP_CLASSIFICATION_LABEL"
    )
    mcp_audit_log: str = Field(default="", validation_alias="MCP_AUDIT_LOG")

    @field_validator("lightrag_url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"LIGHTRAG_URL must be an absolute http(s) URL, got {v!r}")
        return v.rstrip("/")

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> Settings:
        """Build Settings from parsed CLI args layered over the environment.

        Only args explicitly given on the command line (i.e. not None --
        every flag in cli.py defaults to None) override the environment;
        every other field is resolved by BaseSettings from its env var as
        usual.
        """
        arg_to_field = {
            "url": "lightrag_url",
            "api_key": "lightrag_api_key",
            "timeout": "timeout",
            "query_timeout": "query_timeout",
            "upload_timeout": "upload_timeout",
            "verify_ssl": "verify_ssl",
            "server_name": "server_name",
            "transport": "transport",
            "log_level": "log_level",
        }
        overrides = {
            field_name: getattr(args, arg_name)
            for arg_name, field_name in arg_to_field.items()
            if getattr(args, arg_name, None) is not None
        }
        return cls(**overrides)
