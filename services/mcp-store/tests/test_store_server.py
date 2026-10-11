import hashlib
import json
from pathlib import Path

import httpx
import pytest
import respx

from evidence import snapshots

STORE = "http://store.test"
PUBLIC = "http://173.255.199.245"
STORE_TOKEN = "store-mcp-token"
HEADERS = {
  "accept": "application/json, text/event-stream",
  "content-type": "application/json",
  "authorization": f"Bearer {STORE_TOKEN}",
}
FIXTURES = Path(__file__).parent / "fixtures" / "listings"
POISONED = (FIXTURES / "charger_poisoned.html").read_text()
PAN = "4111111111111111"


@pytest.fixture(autouse=True)
def store_env(monkeypatch):
  monkeypatch.setenv("STORE_URL", STORE)
  monkeypatch.setenv("STORE_MCP_TOKEN", STORE_TOKEN)
  monkeypatch.setenv("STORE_PUBLIC_URLS", PUBLIC)
  # These tests isolate merchant adaptation/evidence. Real execution binding is
  # exercised by the full HTTP Graph stack and dedicated scope rejection tests.
  import main
  async def authorized(action):
    run = main.scope_headers.get().get("x-leash-run-id", "run_demo")
    if not main._RUN_ID.fullmatch(run):
      raise main.StoreUnavailable("Invalid execution run")
    return {"run_id": run}
  monkeypatch.setattr(main, "authorize_tool", authorized)


@pytest.fixture
def store():
  with respx.mock(assert_all_called=False) as mock:
    mock.get(f"{STORE}/products/chg-65w").respond(200, html=POISONED)
    yield mock


def call(client, name, arguments, headers=HEADERS):
  arguments = dict(arguments)
  if name == "browse":
    arguments.setdefault("run_id", "run_demo")
  headers = {**headers, "x-leash-run-id": arguments.get("run_id", "run_demo")}
  return client.post(
    "/mcp",
    headers=headers,
    json={
      "jsonrpc": "2.0",
      "id": 1,
      "method": "tools/call",
      "params": {"name": name, "arguments": arguments},
    },
  )


def result(res):
  assert res.status_code == 200, res.text
  return res.json()["result"]


def text_of(r):
  return "".join(block["text"] for block in r["content"] if block["type"] == "text")


# -- what this server exposes and who may call it -----------------------------


def test_store_server_has_only_store_tools(client):
  res = client.post(
    "/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
  )
  names = {t["name"] for t in res.json()["result"]["tools"]}
  # No payment tools here: those live only on the Leash MCP service.
  assert names == {"browse", "create_checkout", "complete_checkout"}


def test_refuses_when_no_store_token_is_configured(client, monkeypatch):
  monkeypatch.delenv("STORE_MCP_TOKEN")
  assert call(client, "browse", {"url": "/products/chg-65w"}).status_code == 503


@pytest.mark.parametrize("auth", [None, "Bearer wrong", "Bearer agent-token", STORE_TOKEN])
def test_rejects_missing_or_wrong_token(client, auth):
  headers = {k: v for k, v in HEADERS.items() if k != "authorization"}
  if auth:
    headers["authorization"] = auth
  res = call(client, "browse", {"url": "/products/chg-65w"}, headers=headers)
  assert res.status_code == 401


# -- browsing reaches only the store ------------------------------------------


@pytest.mark.parametrize("target", ["/products/chg-65w", f"{PUBLIC}/products/chg-65w"])
def test_browse_returns_page_text_and_evidence_without_raw_html(client, store, target):
  r = result(call(client, "browse", {"url": target}))
  assert not r["isError"]
  text = text_of(r)
  # The gullible shopper sees everything, hidden instruction included.
  assert "SUB-CARE-MO" in text
  evidence = r["structuredContent"]
  assert evidence["url"] == f"{STORE}/products/chg-65w"
  assert evidence["sha256"] == hashlib.sha256(POISONED.encode()).hexdigest()
  assert evidence["hidden_text_detected"] is True
  assert "SUB-CARE-MO" in evidence["excerpt"]
  assert evidence["trust_classification"] == "untrusted_web_content"
  assert evidence["snapshot"] == {"storage": "none", "reason": "object storage not configured"}
  # Raw HTML stays in this server: not in the text, not in the evidence.
  for blob in (text, json.dumps(evidence)):
    assert "<div" not in blob and "<!--" not in blob and "display:none" not in blob


@pytest.mark.parametrize(
  "target",
  [
    "http://api:8000/health",
    "http://agents:8000/runs",
    "http://169.254.169.254/latest/meta-data",
    "http://evil.example/products/chg-65w",
    "file:///etc/passwd",
    "//evil.example/products/chg-65w",
    "ftp://store.test/products",
  ],
)
def test_browse_refuses_anything_but_the_store(client, target):
  with respx.mock(assert_all_called=False) as mock:
    anything = mock.route().respond(200, text="secret")
    r = result(call(client, "browse", {"url": target}))
  assert r["isError"] is True
  assert r["structuredContent"]["status"] == "error"
  assert not anything.called


def test_browse_refuses_redirects_off_the_store(client):
  with respx.mock(assert_all_called=False) as mock:
    mock.get(f"{STORE}/go").respond(302, headers={"location": "http://api:8000/health"})
    internal = mock.get("http://api:8000/health").respond(200, text="internal")
    r = result(call(client, "browse", {"url": "/go"}))
  assert r["isError"] is True
  assert "redirected off the store" in text_of(r)
  assert not internal.called


def test_browse_follows_redirects_within_the_store(client):
  with respx.mock() as mock:
    mock.get(f"{STORE}/old").respond(301, headers={"location": "/products/chg-65w"})
    mock.get(f"{STORE}/products/chg-65w").respond(200, html=POISONED)
    r = result(call(client, "browse", {"url": "/old"}))
  assert r["structuredContent"]["url"] == f"{STORE}/products/chg-65w"


def test_snapshot_is_redacted_and_filed_under_the_run(client, monkeypatch):
  stored = {}

  class FakeS3:
    def put_object(self, **kwargs):
      stored.update(kwargs)

  for name in ("OBJ_ENDPOINT", "OBJ_ACCESS_KEY", "OBJ_SECRET_KEY"):
    monkeypatch.setenv(name, "x")
  monkeypatch.setenv("OBJ_BUCKET", "leash-snapshots")
  monkeypatch.setattr(snapshots, "_s3_client", lambda *args: FakeS3())
  page = POISONED.replace("Ships in 2 business days.", f"Test card {PAN} cvv 123.")
  with respx.mock() as mock:
    mock.get(f"{STORE}/products/chg-65w").respond(200, html=page)
    r = result(call(client, "browse", {"url": "/products/chg-65w", "run_id": "run_abc"}))
  sha = hashlib.sha256(page.encode()).hexdigest()
  snap = r["structuredContent"]["snapshot"]
  assert snap["key"] == f"runs/run_abc/{sha}.html"
  assert snap["stored_sha256"] == hashlib.sha256(stored["Body"]).hexdigest()
  assert PAN not in stored["Body"].decode()
  assert r["structuredContent"]["evidence_ref"] == snap["key"]


def test_bad_run_id_cannot_steer_the_snapshot_key(client, store, monkeypatch):
  keys = []

  class FakeS3:
    def put_object(self, **kwargs):
      keys.append(kwargs["Key"])

  for name in ("OBJ_ENDPOINT", "OBJ_BUCKET", "OBJ_ACCESS_KEY", "OBJ_SECRET_KEY"):
    monkeypatch.setenv(name, "x")
  monkeypatch.setattr(snapshots, "_s3_client", lambda *args: FakeS3())
  r = result(call(client, "browse", {"url": "/products/chg-65w", "run_id": "../../etc"}))
  assert r["isError"]
  assert keys == []


# -- checkout goes to the store with the store's credential --------------------


def test_create_checkout_uses_store_credential_not_callers_token(client, monkeypatch):
  monkeypatch.setenv("STORE_API_TOKEN", "store-api-secret")
  with respx.mock() as mock:
    route = mock.post(f"{STORE}/api/checkouts").respond(201, json={"checkout_id": "chk_1"})
    r = result(call(client, "create_checkout", {"sku": "SUB-CARE-MO", "quantity": 1}))
  assert r["structuredContent"] == {"checkout_id": "chk_1"}
  sent = route.calls.last.request
  assert sent.headers["authorization"] == "Bearer store-api-secret"
  assert STORE_TOKEN not in str(sent.headers)
  assert json.loads(sent.content) == {"sku": "SUB-CARE-MO", "quantity": 1}


@pytest.mark.parametrize("quantity", [1.0, True, "1", 0])
def test_create_checkout_rejects_non_integer_quantity(client, quantity):
  with respx.mock(assert_all_called=False) as mock:
    route = mock.post(f"{STORE}/api/checkouts").respond(201, json={})
    r = result(call(client, "create_checkout", {"sku": "CHG-65W", "quantity": quantity}))
  assert r["isError"] is True
  assert not route.called


def test_complete_checkout_passes_card_to_the_store_only(client):
  with respx.mock() as mock:
    route = mock.post(f"{STORE}/api/checkouts/chk_1/complete").respond(200, json={"status": "paid"})
    args = {"checkout_id": "chk_1", "payment_id": "pay_1", "card_number": PAN, "cvv": "321"}
    r = result(call(client, "complete_checkout", args))
  assert r["structuredContent"] == {"status": "paid"}
  assert json.loads(route.calls.last.request.content)["card"]["number"] == PAN


@pytest.mark.parametrize("checkout_id", ["../admin", "chk_1/complete?x=", "a b"])
def test_complete_checkout_rejects_path_tricks(client, checkout_id):
  with respx.mock(assert_all_called=False) as mock:
    anything = mock.route().respond(200, json={})
    r = result(call(client, "complete_checkout", {"checkout_id": checkout_id, "payment_id": "p"}))
  assert r["structuredContent"]["status"] == "error"
  assert not anything.called


def test_store_errors_are_plain_results(client):
  with respx.mock() as mock:
    mock.post(f"{STORE}/api/checkouts").respond(404, json={"detail": "Unknown SKU"})
    r = result(call(client, "create_checkout", {"sku": "NOPE"}))
  assert r["structuredContent"] == {"status": "error", "reason": "Unknown SKU", "http_status": 404}


def test_store_unreachable_is_a_plain_result(client):
  with respx.mock() as mock:
    mock.post(f"{STORE}/api/checkouts").mock(side_effect=httpx.ConnectError("down"))
    r = result(call(client, "create_checkout", {"sku": "CHG-65W"}))
  assert "unreachable" in r["structuredContent"]["reason"]
