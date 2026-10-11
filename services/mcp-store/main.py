"""Store MCP server (Deployment mcp-store, port 8003, path /mcp).

Shop at the controlled merchant, for any agent. Its own service, separate from
the Leash MCP server (services/mcp-leash) on purpose. Leash's server carries the
agent's payment credential to the Leash api; this one carries a store-scoped
credential to the merchant, and never sees or forwards the Leash token.

Browsing only reaches the configured store. A page can't send it anywhere
else: other hosts are refused, and so are redirects off the store, so a
manipulated agent can't use it to probe services inside the cluster.

Raw HTML never leaves this server. Each page is hashed, inspected for hidden
instruction-like text, redacted, and snapshotted here. The agent gets the page
text (all of it, hidden parts included: the demo shopper is gullible on
purpose) plus an evidence record. Everything this server returns is
agent-observed evidence, never checkout truth: the Leash api fetches the
canonical checkout from the store itself.
"""

import hmac
import os
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field, StrictInt
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from evidence.html_text import extract
from evidence.inspect import inspect_page
from evidence.snapshots import upload_snapshot

HTTP_TIMEOUT = 10.0
MAX_PAGE_BYTES = 2_000_000
MAX_PAGE_CHARS = 12_000
MAX_REDIRECTS = 3
_RUN_ID = re.compile(r"^run_[A-Za-z0-9_-]+$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

# TODO(C02/H05): confirm these with Cameron's store. Proposed routes:
#   POST {STORE_URL}/api/checkouts               {"sku", "quantity"} -> checkout
#   POST {STORE_URL}/api/checkouts/{id}/complete {"payment_id", "card"?} -> result
CHECKOUTS_PATH = "/api/checkouts"

Quantity = Annotated[StrictInt, Field(ge=1)]

INSTRUCTIONS = """\
The Volt Supply Co. store (a simulated merchant). Browse its pages, start a
checkout for a SKU to get a checkout_id, and complete the checkout once your
payment service has approved payment for that exact checkout_id.
"""

store = MCPServer("Volt Supply Store", instructions=INSTRUCTIONS)


class StoreUnavailable(Exception):
  pass


def _origin(url: httpx.URL) -> tuple[str, str, int | None]:
  return (url.scheme, url.host, url.port)


def _store_url() -> httpx.URL:
  raw = os.environ.get("STORE_URL")
  if not raw:
    raise StoreUnavailable("store is not configured (STORE_URL)")
  return httpx.URL(raw.rstrip("/"))


def _allowed_origins(store_url: httpx.URL) -> set[tuple[str, str, int | None]]:
  # The store's public address can appear in pages and start URLs; those map
  # to the same store. Nothing else is reachable.
  origins = {_origin(store_url)}
  for raw in os.environ.get("STORE_PUBLIC_URLS", "").split(","):
    if raw.strip():
      origins.add(_origin(httpx.URL(raw.strip())))
  return origins


def resolve_store_target(target: str) -> httpx.URL:
  """Map a path or a store URL onto the internal store address, or refuse."""
  store_url = _store_url()
  requested = httpx.URL(target)
  # Only a bare path counts as relative. "file:...", "//other-host/..." and
  # the like all have a scheme or a host and go through the checks below.
  if not requested.scheme and not requested.host:
    path = target if target.startswith("/") else f"/{target}"
    return store_url.join(path)
  if requested.scheme not in ("http", "https"):
    raise StoreUnavailable("only http(s) store pages can be browsed")
  if _origin(requested) not in _allowed_origins(store_url):
    raise StoreUnavailable(f"this tool only browses the store, not {requested.host}")
  return store_url.copy_with(path=requested.path, query=requested.query or None)


async def fetch_store_page(target: str) -> tuple[httpx.URL, int, str]:
  url = resolve_store_target(target)
  store_origin = _origin(_store_url())
  async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False) as client:
    for _ in range(MAX_REDIRECTS + 1):
      try:
        res = await client.get(url)
      except httpx.HTTPError as exc:
        raise StoreUnavailable(f"store unreachable ({type(exc).__name__})") from exc
      if res.is_redirect:
        nxt = url.join(res.headers.get("location", ""))
        # A redirect is just another target: same store or nothing.
        if _origin(nxt) != store_origin:
          raise StoreUnavailable("the store redirected off the store; not following")
        url = nxt
        continue
      body = res.content[:MAX_PAGE_BYTES].decode(res.encoding or "utf-8", errors="replace")
      return url, res.status_code, body
  raise StoreUnavailable("too many redirects")


def _store_headers() -> dict[str, str]:
  # Browse/create use the store API credential. Never forward the caller bearer.
  token = os.environ.get("STORE_API_TOKEN")
  return {"Authorization": f"Bearer {token}"} if token else {}


def _store_charge_headers() -> dict[str, str]:
  # Complete requires the distinct charge credential (same as the API bind path).
  token = os.environ.get("STORE_CHARGE_TOKEN")
  return {"Authorization": f"Bearer {token}"} if token else {}


def _error(reason: str, **extra: Any) -> dict[str, Any]:
  return {"status": "error", "reason": reason, **extra}


async def _store_post(
  path: str, body: dict[str, Any], *, headers: dict[str, str] | None = None
) -> dict[str, Any]:
  try:
    store_url = _store_url()
  except StoreUnavailable as exc:
    return _error(str(exc))
  try:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False) as client:
      res = await client.post(
        str(store_url) + path, json=body, headers=headers or _store_headers()
      )
  except httpx.HTTPError as exc:
    return _error(f"store unreachable ({type(exc).__name__})")
  try:
    payload = res.json()
  except ValueError:
    payload = {"body": res.text[:500]}
  if res.is_error:
    detail = payload.get("detail") if isinstance(payload, dict) else None
    return _error(detail or f"store returned HTTP {res.status_code}", http_status=res.status_code)
  return payload if isinstance(payload, dict) else {"items": payload}


@store.tool(
  annotations=ToolAnnotations(title="Read a store page", read_only_hint=True, open_world_hint=False)
)
async def browse(url: str, run_id: str | None = None) -> CallToolResult:
  """Open a page at the Volt Supply store and return its text.

  Args:
    url: A store path like "/products/chg-65w", or a full store URL. Pages on
      other sites can't be opened with this tool.
    run_id: Optional id of your current agent run, to file the page snapshot.
  """
  try:
    final_url, status, html = await fetch_store_page(url)
  except StoreUnavailable as exc:
    return CallToolResult(
      content=[TextContent(type="text", text=f"Could not open {url}: {exc}")],
      structured_content=_error(str(exc)),
      is_error=True,
    )

  page = inspect_page(html)
  run = run_id if run_id and _RUN_ID.match(run_id) else "unattributed"
  snapshot = upload_snapshot(run, page["sha256"], html)
  evidence = {
    "url": str(final_url),
    "http_status": status,
    "fetched_at": datetime.now(UTC).isoformat(),
    "trust_classification": "untrusted_web_content",
    "evidence_ref": snapshot.get("key") or f"sha256:{page['sha256']}",
    "snapshot": snapshot,
    **page,
  }
  text = extract(html).all_text()
  return CallToolResult(
    content=[
      TextContent(type="text", text=f"URL: {final_url}\nHTTP {status}\n\n{text[:MAX_PAGE_CHARS]}")
    ],
    structured_content=evidence,
  )


@store.tool(
  annotations=ToolAnnotations(
    title="Start a checkout", read_only_hint=False, destructive_hint=False, open_world_hint=False
  )
)
async def create_checkout(sku: str, quantity: Quantity = 1) -> dict[str, Any]:
  """Start a checkout at the store for one product.

  Returns the store's checkout, including a checkout_id. Give that
  checkout_id to your payment service so it can verify the order with the
  store before anything is paid.

  Args:
    sku: The product SKU exactly as the store lists it, e.g. "CHG-65W".
    quantity: How many units. Usually 1.
  """
  return await _store_post(CHECKOUTS_PATH, {"sku": sku, "quantity": quantity})


@store.tool(
  annotations=ToolAnnotations(
    title="Pay for a checkout", read_only_hint=False, destructive_hint=False, open_world_hint=False
  )
)
async def complete_checkout(
  checkout_id: str,
  payment_id: str,
  card_number: str | None = None,
  exp_month: int | None = None,
  exp_year: int | None = None,
  cvv: str | None = None,
) -> dict[str, Any]:
  """Pay for a checkout after your payment service approved it.

  The store charges only the exact checkout that payment was approved for.

  Args:
    checkout_id: The checkout_id from create_checkout.
    payment_id: The payment id your payment service returned.
    card_number: Single-use card number, if one was issued.
    exp_month: Card expiry month, if a card was issued.
    exp_year: Card expiry year, if a card was issued.
    cvv: Card security code, if a card was issued.
  """
  # The id becomes part of the URL path; don't let it point at another route.
  if not _SAFE_ID.match(checkout_id):
    return _error("checkout_id has unexpected characters")
  body: dict[str, Any] = {"payment_id": payment_id}
  if card_number:
    body["card"] = {"number": card_number, "exp_month": exp_month, "exp_year": exp_year, "cvv": cvv}
  return await _store_post(
    f"{CHECKOUTS_PATH}/{checkout_id}/complete",
    body,
    headers=_store_charge_headers(),
  )


class StoreAuthMiddleware:
  """Require STORE_MCP_TOKEN. Fails closed: no token configured, no access.

  Unlike the Leash endpoint, this server holds a store credential of its own,
  so it checks callers itself instead of passing their token along.
  """

  def __init__(self, app):
    self.app = app

  async def __call__(self, scope, receive, send):
    if scope["type"] != "http":
      await self.app(scope, receive, send)
      return
    expected = os.environ.get("STORE_MCP_TOKEN")
    if not expected:
      res = JSONResponse(
        {"status": "error", "reason": "store MCP token is not configured"}, status_code=503
      )
      await res(scope, receive, send)
      return
    auth = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip(), expected):
      res = JSONResponse(
        {"status": "error", "reason": "missing or invalid store MCP token"},
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
      )
      await res(scope, receive, send)
      return
    await self.app(scope, receive, send)


async def health(_: Request) -> JSONResponse:
  # /health matches the api and the LKE probes; /healthz is the AGENTS.md name.
  return JSONResponse({"status": "ok", "service": "mcp-store"})


def _allowed_hosts() -> list[str]:
  # DNS-rebinding protection rejects any Host header not listed here.
  raw = os.environ.get("MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*,mcp-store:*")
  return [h.strip() for h in raw.split(",") if h.strip()]


store_app = store.streamable_http_app(
  streamable_http_path="/mcp",
  stateless_http=True,
  json_response=True,
  transport_security=TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=_allowed_hosts(),
  ),
)


@asynccontextmanager
async def lifespan(_: Starlette):
  # The routed MCP sub-app doesn't run its own lifespan, so start it here.
  async with store.session_manager.run():
    yield


app = Starlette(
  routes=[
    Route("/health", health),
    Route("/healthz", health),
    Route("/mcp", StoreAuthMiddleware(store_app)),
  ],
  lifespan=lifespan,
)
