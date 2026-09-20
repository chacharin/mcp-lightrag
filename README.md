# mcp-lightrag

An MCP server that bridges an AI agent (built and tested against Nous Research's Hermes Agent) to a [LightRAG](https://github.com/HKUDS/LightRAG) knowledge-graph server over its HTTP API.

Written from scratch to replace an older community wrapper that had two structural bugs against current LightRAG versions: it sent the API key as `Authorization: Bearer <key>` instead of the `X-API-Key` header LightRAG actually checks (so every authenticated call silently failed with 401), and it swallowed non-200/422 errors into a fake `"status": "success"` response — so an agent asking "how many documents are there" would be told "0" instead of being told the connection failed. This server raises a real, readable error on every failure instead, and its 33 tools are matched against LightRAG's current OpenAPI schema (see `scripts/check_api_compat.py`).

Tested against LightRAG **v1.5.7** (API `0344`).

## Installation

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

Run directly from GitHub without cloning:

```bash
uvx --from git+https://github.com/<GITHUB_USER>/mcp-lightrag@v0.1.0 mcp-lightrag --help
```

Or clone and run locally:

```bash
git clone https://github.com/<GITHUB_USER>/mcp-lightrag.git
cd mcp-lightrag
uv sync
uv run mcp-lightrag --help
```

## Configuration

Every setting can be passed as a CLI flag or an environment variable (flag wins if both are given). Copy `.env.example` to `.env` and fill in real values, or set these directly:

| Env var | CLI flag | Default | Meaning |
|---|---|---|---|
| `LIGHTRAG_URL` | `--url` | `http://localhost:9621` | LightRAG's base URL. Use `http://lightrag:9621` when running inside the same Docker network as the LightRAG container. |
| `LIGHTRAG_API_KEY` | `--api-key` | (empty) | Sent as the `X-API-Key` header. |
| `LIGHTRAG_USERNAME` / `LIGHTRAG_PASSWORD` | — | (empty) | Used when LightRAG has `AUTH_ACCOUNTS` enabled: calls `POST /login` for a JWT and re-logs in automatically on a 401. |
| `LIGHTRAG_TIMEOUT` | `--timeout` | `30` | Default request timeout, in seconds. |
| `LIGHTRAG_QUERY_TIMEOUT` | `--query-timeout` | `180` | Timeout for `/query` and `/query/data` (these can run an LLM call). |
| `LIGHTRAG_UPLOAD_TIMEOUT` | `--upload-timeout` | `300` | Timeout for file uploads. |
| `LIGHTRAG_VERIFY_SSL` | `--verify-ssl` / `--no-verify-ssl` | `true` | Verify LightRAG's TLS certificate. |
| `MCP_SERVER_NAME` | `--server-name` | `lightrag` | Name this server reports to MCP clients. |
| `MCP_TRANSPORT` | `--transport` | `stdio` | `stdio` or `streamable-http`. |
| `LOG_LEVEL` | `--log-level` | `INFO` | Logging verbosity. Always written to stderr, never stdout, so it never corrupts the stdio JSON-RPC stream. |
| `MCP_CLASSIFICATION_LABEL` | — | (empty) | Tags every tool's result with this classification (e.g. `secret`) when this process is one profile's MCP server for one LightRAG classification tier -- see [Phase 7](#phase-7-classification-tiers). |
| `MCP_AUDIT_LOG` | — | (empty; stderr) | Path to a JSON-lines audit log of every tool call. Leave empty to write the same lines to stderr instead. |

## Using with Hermes Agent

In the Hermes profile's `config.yaml`:

```yaml
mcp_servers:
  lightrag:
    command: "uvx"
    args: ["--from", "git+https://github.com/<GITHUB_USER>/mcp-lightrag@v0.1.0", "mcp-lightrag"]
    env:
      LIGHTRAG_URL: "http://lightrag:9621"
      LIGHTRAG_API_KEY: "${LIGHTRAG_API_KEY}"
    timeout: 300          # max time per tool call (Hermes default is 300)
    connect_timeout: 120  # first run has to download and build the package (~29s observed)
```

Add `LIGHTRAG_API_KEY=<key>` to the profile's `.env` (same value as the LightRAG instance's own `.env`), then restart the Hermes container and verify with `hermes mcp test lightrag` — expect `✓ Connected` and `Tools discovered: 33`.

If the repo is private, build a wheel instead (`uv build`), copy `dist/mcp_lightrag-*-py3-none-any.whl` somewhere the Hermes container can read, and point `--from` at that path — this avoids needing a GitHub token inside the container.

To upgrade later: push a new tag (e.g. `v0.1.1`), update `@v0.1.0` in `config.yaml` to match, and restart the container (add `--refresh` before `--from` once if `uv`'s cache holds onto the old tag).

## Tools

33 tools total, grouped by risk. Every tool whose description starts with **DESTRUCTIVE** permanently changes or deletes data and cannot be undone.

**Query (2)** — `query`, `query_data`

**Documents, read-only (7)** — `list_documents`, `get_document_status_counts`, `get_pipeline_status`, `get_track_status`, `get_supported_file_types`, `get_scan_status`, `list_source_conflicts`

**Documents, add/modify (6)** — `insert_text`, `insert_texts`, `upload_file`, `upload_directory`, `scan_documents`, `reprocess_failed_documents`

**Documents, destructive/pipeline control (5)** — `delete_documents` ⚠️, `clear_all_documents` ⚠️, `force_reset_recovery` ⚠️, `cancel_pipeline`, `repair_source_conflict` ⚠️

**Knowledge graph, read-only (5)** — `get_graph_labels`, `get_popular_labels`, `search_labels`, `get_knowledge_graph`, `check_entity_exists`

**Knowledge graph, add/modify (5)** — `create_entity`, `edit_entity`, `create_relation`, `edit_relation`, `merge_entities` ⚠️

**Knowledge graph, destructive (2)** — `delete_entity` ⚠️, `delete_relation` ⚠️

**System (1)** — `health` (checks both that LightRAG is reachable *and* that the configured credentials actually work, by also calling an authenticated endpoint — `GET /health` alone is a public liveness probe that returns 200 even with a missing or wrong API key)

## Phase 7: classification tiers

Running several instances of this server, each pointed at its own LightRAG
container and tagged with `MCP_CLASSIFICATION_LABEL`, is how multiple
Hermes profiles at different classification levels get access to different
knowledge bases -- see `plan.md` section 7 for the full architecture
(Discord role -> Hermes profile -> mcp-lightrag process -> LightRAG
instance, each layer with its own scoped credentials). This server never
trusts a classification level the calling agent sends as a tool parameter;
the only sources of truth are which LightRAG instance a given process is
configured to talk to, and the label that process itself is configured
with.

When `MCP_CLASSIFICATION_LABEL` is set:

- every tool's result gains a `"classification"` field with that value
- the server's `instructions` (sent to the client at connect time) note the
  classification level

Every tool call is always logged as one JSON line -- to `MCP_AUDIT_LOG` if
set, otherwise to stderr alongside the regular application log -- recording
the timestamp, tool name, classification, `success`/`error` status, and a
SHA-256 hash of the call's parameters. The parameters and the tool's result
content are never written to this log, so a classified query or document
never ends up sitting in a log file; the hash exists only to let two audit
lines be recognised as the same call.

## Development

```bash
uv sync --all-extras
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest tests/unit          # mocked, no server needed
```

Integration tests need a real, disposable LightRAG instance (never point this at a real knowledge base — the test suite ends by clearing every document the target instance holds):

```bash
LIGHTRAG_URL=http://localhost:9622 uv run pytest tests/integration -m integration -v
```

After updating a LightRAG image, check this project's endpoint list is still compatible with its live OpenAPI schema:

```bash
curl -H "X-API-Key: <key>" http://localhost:9621/openapi.json -o openapi.live.json
uv run python scripts/check_api_compat.py openapi.live.json
```

## License

MIT — see [LICENSE](LICENSE).
