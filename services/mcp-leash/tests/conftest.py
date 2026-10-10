import pytest
from starlette.testclient import TestClient

from main import app


# The MCP session manager can only be started once per process, so every test
# module shares one client and one app lifespan.
@pytest.fixture(scope="session")
def client():
  with TestClient(app, base_url="http://localhost:8002") as c:
    yield c
