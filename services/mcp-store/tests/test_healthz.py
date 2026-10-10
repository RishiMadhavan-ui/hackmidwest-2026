import pytest
from starlette.testclient import TestClient

from main import app


@pytest.mark.parametrize("path", ["/health", "/healthz"])
def test_health(path):
  res = TestClient(app).get(path)
  assert res.status_code == 200
  body = res.json()
  assert body["status"] == "ok"
  assert body["service"] == "mcp-store"
