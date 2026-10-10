# Build from the repo root so the shared package can be copied in once it exists:
#   docker build -f services/agents/Dockerfile .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies before copying source so code edits don't bust the cache.
COPY services/agents/pyproject.toml services/agents/uv.lock services/agents/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/agents/ ./
# shared/ has no package metadata yet (C01), so copy the package next to the
# app where Python finds it. TODO: install it as a package once C01 lands.
COPY shared/leash_shared/ ./leash_shared/

ENV PATH="/app/.venv/bin:$PATH" \n  TRACE_SPOOL_DIR=/app/trace-spool
EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
