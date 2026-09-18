"""Unit tests for scripts/check_api_compat.py's comparison logic.

Imports the script as a module (it lives outside src/mcp_lightrag, so
sys.path is extended the same way the script extends it for its own
`from mcp_lightrag.client import ENDPOINTS` import).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from mcp_lightrag.client import ENDPOINTS

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "scripts" / "check_api_compat.py"
)
_spec = importlib.util.spec_from_file_location("check_api_compat", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
check_api_compat = importlib.util.module_from_spec(_spec)
sys.modules["check_api_compat"] = check_api_compat
_spec.loader.exec_module(check_api_compat)


def _schema_for(entries: list[tuple[str, str]]) -> dict:
    paths: dict[str, dict] = {}
    for method, path in entries:
        paths.setdefault(path, {})[method.lower()] = {}
    return {"paths": paths}


def test_find_missing_endpoints_none_missing_when_schema_has_every_endpoint() -> None:
    schema = _schema_for([(method, path) for method, path, _ in ENDPOINTS])

    missing = check_api_compat.find_missing_endpoints(schema)

    assert missing == []


def test_find_missing_endpoints_reports_a_removed_endpoint() -> None:
    entries = [(method, path) for method, path, _ in ENDPOINTS if path != "/query/data"]
    schema = _schema_for(entries)

    missing = check_api_compat.find_missing_endpoints(schema)

    assert len(missing) == 1
    assert "POST /query/data" in missing[0]
    assert "query_data" in missing[0]


def test_find_missing_endpoints_normalizes_differently_named_path_params() -> None:
    """/documents/track_status/{track_id} in ENDPOINTS must still match a
    schema that names the same parameter position differently, e.g. {id}
    -- only the position in the path matters, not the parameter's name.
    """
    entries = [
        (method, path.replace("{track_id}", "{id}").replace("{doc_id}", "{id}"))
        for method, path, _ in ENDPOINTS
    ]
    schema = _schema_for(entries)

    missing = check_api_compat.find_missing_endpoints(schema)

    assert missing == []


def test_main_returns_nonzero_and_prints_missing_endpoints(tmp_path, capsys) -> None:
    entries = [(method, path) for method, path, _ in ENDPOINTS if path != "/health"]
    schema_path = tmp_path / "openapi.json"
    schema_path.write_text(json.dumps(_schema_for(entries)))

    exit_code = check_api_compat.main(["check_api_compat.py", str(schema_path)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "GET /health" in captured.out


def test_main_returns_zero_when_everything_present(tmp_path, capsys) -> None:
    entries = [(method, path) for method, path, _ in ENDPOINTS]
    schema_path = tmp_path / "openapi.json"
    schema_path.write_text(json.dumps(_schema_for(entries)))

    exit_code = check_api_compat.main(["check_api_compat.py", str(schema_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert f"all {len(ENDPOINTS)} endpoints present" in captured.out
