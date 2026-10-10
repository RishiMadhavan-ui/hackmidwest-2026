import json

import httpx
import pytest
import respx
from starlette.testclient import TestClient

from main import app

API = "http://api.test"
TOKEN = "Bearer agent-token-123"
MCP_HEADERS = {
  "accept": "application/json, text/event-stream",
  "content-type": "application/json",
  "authorization": TOKEN,
}

MERCHANT = {
  "name": "Crossroads Hotel",
  "descriptor": "CROSSROADS HOTEL KC",
  "mcc": "7011",
  "url": "http://store.test/hotels/crossroads",
}
ITEMS = [{"name": "King room, Sat Oct 10", "quantity": 1, "unit_cents": 15800}]


@pytest.fixture(autouse=True)
def api_url(monkeypatch):
  monkeypatch.setenv("API_URL", API)


# The MCP session manager can only be started once per process, so every test
# shares one client (and one app lifespan).
@pytest.fixture(scope="module")
def client():
  with TestClient(app, base_url="http://localhost:8002") as c:
    yield c


@pytest.fixture
def api():
  with respx.mock(base_url=API, assert_all_called=False) as mock:
    yield mock


def rpc(client, method, params=None, headers=MCP_HEADERS):
  return client.post(
    "/mcp",
    headers=headers,
    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
  )


def call_tool(client, name, arguments):
  res = rpc(client, "tools/call", {"name": name, "arguments": arguments})
  assert res.status_code == 200
  result = res.json()["result"]
  assert not result["isError"], result
  return result["structuredContent"]


def test_tool_discovery(client):
  tools = {t["name"]: t for t in rpc(client, "tools/list").json()["result"]["tools"]}
  assert set(tools) == {"propose_mandate", "list_mandates", "request_payment", "check_status"}
  assert tools["list_mandates"]["annotations"]["readOnlyHint"] is True
  assert tools["check_status"]["annotations"]["readOnlyHint"] is True
  assert tools["propose_mandate"]["annotations"]["readOnlyHint"] is False
  assert tools["request_payment"]["annotations"]["readOnlyHint"] is False
  # Descriptions are what outside agents read, so the key rules must be in them.
  assert "phone" in tools["propose_mandate"]["description"]
  assert "18000" in tools["propose_mandate"]["description"]
  for status in ("approved", "pending_user", "denied"):
    assert status in tools["request_payment"]["description"]


def test_no_tool_can_approve_or_toggle_killswitch(client):
  names = [t["name"] for t in rpc(client, "tools/list").json()["result"]["tools"]]
  for banned in ("approve", "revoke", "kill", "limit", "deny"):
    assert not any(banned in n for n in names)


def test_propose_mandate(client, api):
  route = api.post("/mandates/propose").respond(
    201, json={"id": "mnd_1", "status": "proposed", "max_cents": 18000}
  )
  out = call_tool(
    client,
    "propose_mandate",
    {"description": "hotel in KC Saturday, max $180", "category": "lodging", "max_cents": 18000},
  )
  assert out == {"id": "mnd_1", "status": "proposed", "max_cents": 18000}
  sent = json.loads(route.calls.last.request.content)
  assert sent == {
    "description": "hotel in KC Saturday, max $180",
    "category": "lodging",
    "max_cents": 18000,
    "location": None,
    "valid_until": None,
  }


def test_propose_mandate_rejects_float_cents(client, api):
  res = rpc(
    client,
    "tools/call",
    {
      "name": "propose_mandate",
      "arguments": {"description": "hotel", "category": "lodging", "max_cents": 180.5},
    },
  )
  assert res.json()["result"]["isError"] is True
  assert not api.calls


def test_list_mandates(client, api):
  route = api.get("/mandates", params={"status": "active"}).respond(
    200, json=[{"id": "mnd_1", "status": "active"}]
  )
  out = call_tool(client, "list_mandates", {})
  assert out == {"items": [{"id": "mnd_1", "status": "active"}]}
  assert route.called


def test_request_payment(client, api):
  approved = {"id": "pay_1", "status": "approved", "card": {"last4": "4242"}}
  route = api.post("/payments").respond(201, json=approved)
  out = call_tool(
    client,
    "request_payment",
    {
      "mandate_id": "mnd_1",
      "merchant": MERCHANT,
      "items": ITEMS,
      "total_cents": 15800,
      "run_id": "run_1",
    },
  )
  assert out == approved
  sent = json.loads(route.calls.last.request.content)
  assert sent == {
    "mandate_id": "mnd_1",
    "cart": {"merchant": MERCHANT, "items": ITEMS, "total_cents": 15800},
    "run_id": "run_1",
  }


def test_check_status(client, api):
  route = api.get("/payments/pay_1").respond(200, json={"id": "pay_1", "status": "pending_user"})
  out = call_tool(client, "check_status", {"payment_id": "pay_1"})
  assert out["status"] == "pending_user"
  assert route.called


def test_api_error_becomes_plain_result(client, api):
  api.post("/payments").respond(409, json={"detail": "Mandate is not active"})
  out = call_tool(
    client,
    "request_payment",
    {"mandate_id": "mnd_1", "merchant": MERCHANT, "items": ITEMS, "total_cents": 15800},
  )
  assert out == {"status": "error", "http_status": 409, "reason": "Mandate is not active"}


def test_api_unreachable_becomes_plain_result(client, api):
  api.get("/payments/pay_1").mock(side_effect=httpx.ConnectError("refused"))
  out = call_tool(client, "check_status", {"payment_id": "pay_1"})
  assert out["status"] == "error"
  assert "unreachable" in out["reason"]


def test_bearer_forwarded_unchanged(client, api):
  route = api.get("/mandates").respond(200, json=[])
  call_tool(client, "list_mandates", {})
  assert route.calls.last.request.headers["authorization"] == TOKEN


@pytest.mark.parametrize("auth", [None, "", "Bearer ", "Basic dXNlcjpwYXNz", "agent-token-123"])
def test_missing_or_malformed_bearer_rejected(client, api, auth):
  headers = {k: v for k, v in MCP_HEADERS.items() if k != "authorization"}
  if auth is not None:
    headers["authorization"] = auth
  res = rpc(client, "tools/list", headers=headers)
  assert res.status_code == 401
  assert res.headers["www-authenticate"] == "Bearer"
  assert not api.calls


def test_healthz_needs_no_token(client):
  assert client.get("/healthz").status_code == 200


def test_unknown_host_rejected(client):
  res = client.post(
    "/mcp", headers={**MCP_HEADERS, "host": "evil.example"}, json={"jsonrpc": "2.0"}
  )
  assert res.status_code == 421
