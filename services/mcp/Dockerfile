# Build from the repo root so the shared package can be copied in once it exists:
#   docker build -f services/mcp/Dockerfile .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies before copying source so code edits don't bust the cache.
COPY services/mcp/pyproject.toml services/mcp/uv.lock services/mcp/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/mcp/ ./

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8002
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
