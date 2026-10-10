"""The agents service's own routes need the service token; /healthz doesn't."""

import pytest
from fastapi.testclient import TestClient

from main import app

ROUTES = [
  ("post", "/runs", {"task": "Buy a charger"}),
  ("get", "/runs/run_missing", None),
  ("post", "/guardian/evaluate", {"mandate": {}}),
]


@pytest.fixture
def client():
  return TestClient(app)


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_refuses_everything_when_no_token_is_configured(client, method, path, body):
  res = client.request(method, path, json=body, headers={"Authorization": "Bearer anything"})
  assert res.status_code == 503


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
@pytest.mark.parametrize("auth", [None, "Bearer wrong", "svc-token", "Basic c3ZjLXRva2Vu"])
def test_rejects_missing_or_wrong_token(client, monkeypatch, method, path, body, auth):
  monkeypatch.setenv("AGENTS_SERVICE_TOKEN", "svc-token")
  headers = {"Authorization": auth} if auth else {}
  res = client.request(method, path, json=body, headers=headers)
  assert res.status_code == 401
  assert res.headers["www-authenticate"] == "Bearer"


def test_accepts_the_service_token(client, monkeypatch):
  monkeypatch.setenv("AGENTS_SERVICE_TOKEN", "svc-token")
  res = client.get("/runs/run_missing", headers={"Authorization": "Bearer svc-token"})
  assert res.status_code == 404


def test_agent_token_is_not_a_service_token(client, monkeypatch):
  monkeypatch.setenv("AGENTS_SERVICE_TOKEN", "svc-token")
  monkeypatch.setenv("AGENT_TOKEN_SHOPPER", "agent-token")
  res = client.get("/runs/run_missing", headers={"Authorization": "Bearer agent-token"})
  assert res.status_code == 401


def test_healthz_is_open(client):
  assert client.get("/healthz").status_code == 200
