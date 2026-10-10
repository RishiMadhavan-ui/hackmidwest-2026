# Build from the repo root: the agents also need shared/leash_shared.
#   docker build -f services/agents/Dockerfile .
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    TRACE_SPOOL_DIR=/app/trace-spool

COPY services/agents/pyproject.toml services/agents/uv.lock services/agents/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/agents/ ./
COPY shared/leash_shared/ ./leash_shared/

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
