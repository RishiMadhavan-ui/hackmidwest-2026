"""Direct tool callers cannot bypass the API-owned execution boundary."""

import httpx
import pytest
import respx

import main


@pytest.fixture
def anyio_backend():
  return "asyncio"


@pytest.fixture
def execution(monkeypatch):
  monkeypatch.setenv("API_URL", "http://api.test")
  marker = main.scope_headers.set({"x-leash-execution-token": "opaque-test-scope",
                                  "x-leash-run-id": "run_test"})
  yield
  main.scope_headers.reset(marker)


@pytest.mark.anyio
async def test_missing_scope_never_contacts_api_or_merchant(monkeypatch):
  monkeypatch.setenv("API_URL", "http://api.test")
  marker = main.scope_headers.set({})
  try:
    with respx.mock as network:
      with pytest.raises(main.StoreUnavailable, match="run-scoped"):
        await main.authorize_tool("create_checkout")
      assert not network.calls
  finally:
    main.scope_headers.reset(marker)


@pytest.mark.anyio
@pytest.mark.parametrize("status", [401, 403, 409, 503])
async def test_rejected_expired_or_unavailable_scope_never_reaches_store(execution, status):
  with respx.mock as network:
    scope = network.post("http://api.test/execution/authorize").respond(status, json={"detail": "Denied"})
    result = await main._store_post("/api/checkouts", {"sku": "CHG-65W", "quantity": 1})
    assert result["status"] == "error"
    assert scope.call_count == len(network.calls) == 1


@pytest.mark.anyio
async def test_scope_outage_fails_closed(execution):
  with respx.mock as network:
    network.post("http://api.test/execution/authorize").mock(side_effect=httpx.ConnectError("offline"))
    with pytest.raises(main.StoreUnavailable, match="failed closed"):
      await main.authorize_tool("browse")


@pytest.mark.anyio
async def test_each_call_requests_store_audience_and_actual_action(execution):
  import json
  with respx.mock as network:
    scope = network.post("http://api.test/execution/authorize").respond(200, json={"run_id": "run_test"})
    assert await main.authorize_tool("complete_checkout") == {"run_id": "run_test"}
    request = scope.calls[0].request
    assert json.loads(request.content) == {"audience": "mcp-store", "action": "complete_checkout"}
    assert request.headers["x-leash-run-id"] == "run_test"
    assert "authorization" not in request.headers
