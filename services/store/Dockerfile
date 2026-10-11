# Build from the repo root so shared/leash_shared is available:
#   docker build -f services/store/Dockerfile .
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/shared"

COPY services/store/pyproject.toml services/store/uv.lock services/store/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/store/catalog.py \
     services/store/pages.py \
     services/store/execution_bridge.py \
     services/store/main.py \
     ./
COPY shared/leash_shared /shared/leash_shared

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
