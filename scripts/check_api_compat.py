#!/usr/bin/env python3
"""Check every (method, path) this project uses against a live LightRAG
server's OpenAPI schema (plan.md Phase 4.3).

client.py's ENDPOINTS registry is the single place that lists every
endpoint mcp-lightrag calls -- including "_login", this client's own use
of POST /login for the optional JWT flow. This script reads that registry
and checks each (method, path) pair still exists in the schema; run it
after every LightRAG image update so an endpoint LightRAG removed or
renamed is caught here instead of as a runtime tool failure.

Usage:
    uv run python scripts/check_api_compat.py openapi.json

Fetch the schema from a running LightRAG instance first, e.g.:
    curl.exe -H "X-API-Key: <key>" http://localhost:9621/openapi.json -o openapi.live.json

Exit code 0 means every endpoint is present; non-zero (with the missing
endpoints listed) otherwise.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Runs as a standalone script (uv run python scripts/...), not as an
# installed package entry point, so src/ is added to the import path here
# rather than relying on mcp-lightrag being installed.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mcp_lightrag.client import ENDPOINTS

_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_PATH_PARAM_RE = re.compile(r"\{[^{}]+\}")


def _normalize(path: str) -> str:
    """Collapse every path-parameter name to `{}` so `/foo/{track_id}` in
    ENDPOINTS matches `/foo/{id}` in the schema (or any other name a
    future LightRAG version might use for the same parameter position).
    """
    return _PATH_PARAM_RE.sub("{}", path)


def find_missing_endpoints(schema: dict) -> list[str]:
    """Return one "METHOD path (tool: name)" line per ENDPOINTS entry that
    schema's `paths` object does not declare.
    """
    schema_paths = schema.get("paths", {})
    declared = {
        (method.upper(), _normalize(path))
        for path, methods in schema_paths.items()
        for method in methods
        if method.upper() in _HTTP_METHODS
    }

    missing = []
    for method, path, tool_name in ENDPOINTS:
        if (method.upper(), _normalize(path)) not in declared:
            missing.append(f"{method} {path} (tool: {tool_name})")
    return missing


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"Usage: {argv[0]} <openapi.json>", file=sys.stderr)
        return 2

    schema_path = Path(argv[1])
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    missing = find_missing_endpoints(schema)
    if missing:
        print(
            f"check_api_compat: {len(missing)} of {len(ENDPOINTS)} endpoint(s) missing from {schema_path}:"
        )
        for line in missing:
            print(f"  - {line}")
        return 1

    print(f"check_api_compat: all {len(ENDPOINTS)} endpoints present in {schema_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
