# Build from repository root:
#   docker build -f services/webhook/Dockerfile .
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY services/webhook/pyproject.toml services/webhook/uv.lock services/webhook/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/webhook/*.py ./
COPY shared ./shared
ENV PYTHONPATH=/app/shared

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
