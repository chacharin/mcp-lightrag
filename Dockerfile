# mcp-lightrag - MCP server (streamable HTTP) for a LightRAG knowledge base
FROM python:3.12-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app

# uv is mounted only for this step, so the 42 MB binary never ends up in the image
COPY pyproject.toml uv.lock ./
RUN --mount=from=ghcr.io/astral-sh/uv:0.13.1,source=/uv,target=/bin/uv \
    uv sync --frozen --no-dev --no-install-project

COPY app/ ./app/
# /app/usage holds the usage log (a docker volume in docker-compose.yml)
RUN useradd --system --uid 10001 appuser && mkdir -p /app/usage && chown appuser /app/usage
USER appuser
EXPOSE 8700
CMD ["/app/.venv/bin/python", "-m", "app.server"]
