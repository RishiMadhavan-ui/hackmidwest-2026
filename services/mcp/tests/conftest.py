import pytest
from starlette.testclient import TestClient

from main import app

# Store MCP settings must never leak in from the developer's shell.
_ENV = ["STORE_URL", "STORE_PUBLIC_URLS", "STORE_MCP_TOKEN", "STORE_API_TOKEN",
        "OBJ_ENDPOINT", "OBJ_BUCKET", "OBJ_ACCESS_KEY", "OBJ_SECRET_KEY"]  # fmt: skip


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
  for name in _ENV:
    monkeypatch.delenv(name, raising=False)


# Each MCP session manager can only be started once per process, so every test
# module shares one client and one app lifespan.
@pytest.fixture(scope="session")
def client():
  with TestClient(app, base_url="http://localhost:8002") as c:
    yield c
