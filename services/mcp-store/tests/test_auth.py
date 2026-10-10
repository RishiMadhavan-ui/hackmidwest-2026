import pytest
from starlette.testclient import TestClient

from main import app

MCP_HEADERS = {
  "accept": "application/json, text/event-stream",
  "content-type": "application/json",
  "authorization": "Bearer agent-token-123",
}


@pytest.fixture(scope="module")
def client():
  with TestClient(app, base_url="http://localhost:8003") as c:
    yield c


def rpc(client, method, params=None, headers=MCP_HEADERS):
  return client.post(
    "/mcp",
    headers=headers,
    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
  )


def test_mcp_requires_bearer(client):
  res = rpc(
    client,
    "tools/list",
    headers={
      "accept": "application/json, text/event-stream",
      "content-type": "application/json",
    },
  )
  assert res.status_code == 401


def test_tool_list_empty_with_bearer(client):
  res = rpc(client, "tools/list")
  assert res.status_code == 200
  tools = res.json()["result"]["tools"]
  assert tools == []
