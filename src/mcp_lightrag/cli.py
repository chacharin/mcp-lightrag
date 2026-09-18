"""Command-line entry point for mcp-lightrag.

This module owns argument parsing and logging setup only. Settings resolution,
the LightRAG HTTP client, and the MCP server itself live in config.py,
client.py, and server.py, and are imported lazily from ``main()`` so that
``mcp-lightrag --help`` and ``--version`` stay cheap and side-effect-free.

IMPORTANT: logging must be configured to write to stderr, and must happen
before anything else is imported. When this process is launched over stdio
(the transport Hermes uses), stdout is reserved for JSON-RPC traffic only --
anything else written there corrupts the protocol stream.
"""

from __future__ import annotations

import argparse
import logging
import sys

from mcp_lightrag import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-lightrag",
        description=(
            "MCP server bridging an AI agent (e.g. Nous Hermes Agent) to a "
            "LightRAG knowledge-graph server over its HTTP API."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--url",
        dest="url",
        default=None,
        metavar="URL",
        help=(
            "Base URL of the LightRAG server (env: LIGHTRAG_URL, "
            "default: http://localhost:9621). Use http://lightrag:9621 when "
            "running inside the Hermes container on the same Docker network."
        ),
    )
    parser.add_argument(
        "--api-key",
        dest="api_key",
        default=None,
        metavar="KEY",
        help="LightRAG API key, sent as the X-API-Key header (env: LIGHTRAG_API_KEY).",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Default request timeout in seconds (env: LIGHTRAG_TIMEOUT, default: 30).",
    )
    parser.add_argument(
        "--query-timeout",
        dest="query_timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Timeout for /query and /query/data, which can run an LLM call "
            "(env: LIGHTRAG_QUERY_TIMEOUT, default: 180)."
        ),
    )
    parser.add_argument(
        "--upload-timeout",
        dest="upload_timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Timeout for file uploads (env: LIGHTRAG_UPLOAD_TIMEOUT, default: 300).",
    )
    verify_group = parser.add_mutually_exclusive_group()
    verify_group.add_argument(
        "--verify-ssl",
        dest="verify_ssl",
        action="store_true",
        default=None,
        help="Verify the LightRAG server's TLS certificate (env: LIGHTRAG_VERIFY_SSL, default: true).",
    )
    verify_group.add_argument(
        "--no-verify-ssl",
        dest="verify_ssl",
        action="store_false",
        help="Skip TLS certificate verification.",
    )
    parser.add_argument(
        "--server-name",
        dest="server_name",
        default=None,
        metavar="NAME",
        help=(
            "Name this MCP server reports to clients (env: MCP_SERVER_NAME, "
            "default: lightrag). Used to run several instances against "
            "different LightRAG classification tiers -- see plan.md Phase 7."
        ),
    )
    parser.add_argument(
        "--transport",
        dest="transport",
        choices=["stdio", "streamable-http"],
        default=None,
        help="MCP transport to use (env: MCP_TRANSPORT, default: stdio).",
    )
    parser.add_argument(
        "--log-level",
        dest="log_level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="Logging verbosity, always written to stderr (env: LOG_LEVEL, default: INFO).",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    # Logging must be set up, to stderr, before any other project module is
    # imported -- see the module docstring.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )

    parser = _build_parser()
    args = parser.parse_args(argv)

    # Imported here rather than at module load time so `mcp-lightrag --help`
    # and `--version` stay cheap and side-effect-free.
    from mcp_lightrag.server import run_server

    run_server(args)


if __name__ == "__main__":
    main()
