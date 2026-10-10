"""Store tools send the store credential; browse never sends any credential."""

import json

import respx

from shopper.tools import browse, create_checkout

STORE = "http://store.test"


class _Ctx:
  def __init__(self):
    self.invocation_state = {}
    self.tool_use = {"toolUseId": "t1"}


def test_checkout_sends_store_token_only_to_the_store(monkeypatch):
  monkeypatch.setenv("STORE_URL", STORE)
  monkeypatch.setenv("STORE_API_TOKEN", "store-secret")
  with respx.mock() as mock:
    checkout = mock.post(f"{STORE}/api/checkouts").respond(201, json={"checkout_id": "chk_1"})
    page = mock.get(f"{STORE}/products/chg-65w").respond(200, text="<p>charger</p>")
    out = json.loads(create_checkout(sku="CHG-65W", quantity=1))
    browse._tool_func(url=f"{STORE}/products/chg-65w", tool_context=_Ctx())
  assert out["checkout_id"] == "chk_1"
  assert checkout.calls.last.request.headers["authorization"] == "Bearer store-secret"
  assert "authorization" not in page.calls.last.request.headers


def test_no_store_token_sends_no_header(monkeypatch):
  monkeypatch.setenv("STORE_URL", STORE)
  with respx.mock() as mock:
    checkout = mock.post(f"{STORE}/api/checkouts").respond(201, json={"checkout_id": "chk_1"})
    create_checkout(sku="CHG-65W")
  assert "authorization" not in checkout.calls.last.request.headers


def test_store_errors_come_back_as_plain_results(monkeypatch):
  monkeypatch.setenv("STORE_URL", STORE)
  with respx.mock() as mock:
    mock.post(f"{STORE}/api/checkouts").respond(404, json={"detail": "Unknown SKU"})
    out = json.loads(create_checkout(sku="NOPE"))
  assert out == {"status": "error", "reason": "Unknown SKU", "http_status": 404}
