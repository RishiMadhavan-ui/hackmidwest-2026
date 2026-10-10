import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.mark.parametrize("path", ["/health", "/healthz"])
def test_health(path):
  # No auth header: probes from Kubernetes must get through.
  res = TestClient(app).get(path)
  assert res.status_code == 200
  assert res.json()["status"] == "ok"
