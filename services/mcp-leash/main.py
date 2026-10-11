"""Leash MCP server (Deployment mcp-leash, port 8002, path /mcp).

Payment tools only; shopping lives in the separate store MCP service
(services/mcp-store). A thin, stateless adapter: each tool forwards to exactly
one api route with the caller's bearer token, unchanged. The api decides whether the token is valid
and what the agent may do. Nothing here can approve a mandate or payment, raise
a limit, or touch the kill switch; those routes need a human's token.
"""

import contextvars
import os
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, StrictBool, StrictInt, StrictStr
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

# The caller's raw "Bearer ..." header for the current request. Set by
# BearerAuthMiddleware, read by every tool.
bearer_header: contextvars.ContextVar[str] = contextvars.ContextVar("bearer_header")

# POST /payments fetches and verifies the checkout with the merchant before it
# answers, so give the api headroom.
API_TIMEOUT_SECONDS = 30.0

INSTRUCTIONS = """\
Leash is a payment firewall. You never get the user's real card. To spend money:
1. Call list_mandates to find an active mandate that covers the purchase. If none
   fits, call propose_mandate and tell the user to confirm it. You cannot
   confirm it yourself.
2. Start a checkout at the merchant and get its checkout_id.
3. Call request_payment with that checkout_id. Leash fetches the real checkout
   from the merchant and checks it against what the user confirmed. If it
   passes, you get payment credentials for that exact checkout only.
   If it needs the user, poll check_status. If blocked, read the reasons and stop.
All money is integer cents: $29.99 is 2999.
"""

# mcp 2.x renamed FastMCP to MCPServer and moved stateless_http/json_response
# from the constructor onto streamable_http_app().
mcp = MCPServer("Leash", instructions=INSTRUCTIONS)


# Money and counts are strict integers, matching leash_shared.models: lax
# pydantic ints would quietly turn 40.0 into 40 and true into 1.
# TODO: import Cents/Quantity/ProductConstraint from leash_shared.models once
# R01 is frozen and the shared package is installable (C01).
Cents = Annotated[StrictInt, Field(ge=0)]
Quantity = Annotated[StrictInt, Field(ge=1)]


class ProductConstraint(BaseModel):
  name: str = Field(description='Product attribute, e.g. "connector"')
  operator: Literal["equals", "contains", "minimum", "maximum"] = "equals"
  value: StrictStr | StrictInt | StrictBool = Field(
    description='Required value, e.g. "USB-C". minimum/maximum take integers.'
  )


# TODO: switch to the agreed proposal-cart model in leash_shared.models (R01).
# This is the agent's own description of the purchase. Leash treats it as
# evidence to compare against the merchant's checkout, never as proof.
class ProposedItem(BaseModel):
  name: str = Field(description="Item name as you understand it, e.g. 'VoltPro 65W USB-C charger'")
  sku: str | None = Field(default=None, description="The store's SKU, if you know it")
  quantity: Quantity
  unit_cents: Cents = Field(description="Price per unit in integer cents. $29.99 is 2999.")


def _api_url() -> str:
  return os.environ.get("API_URL", "http://localhost:8000").rstrip("/")


async def _call_api(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
  """Forward one request to the api and turn any failure into a plain result.

  Agents can act on {"status": "error", "reason": ...}; a raised exception just
  looks like a broken tool to them.
  """
  headers = {"Authorization": bearer_header.get("")}
  try:
    async with httpx.AsyncClient(base_url=_api_url(), timeout=API_TIMEOUT_SECONDS) as client:
      res = await client.request(method, path, headers=headers, **kwargs)
  except httpx.TimeoutException:
    return {"status": "error", "reason": "Leash api timed out; outcome unknown. Do not retry purchases or request new credentials. Reconcile the same operation before proceeding."}
  except httpx.HTTPError:
    return {"status": "error", "reason": "Leash api is unreachable; outcome unknown. Do not retry financial operations until reconciled."}

  try:
    body = res.json()
  except ValueError:
    body = None

  if res.is_success:
    # Lists come back as {"items": [...]} so every tool returns an object.
    return body if isinstance(body, dict) else {"items": body}

  detail = body.get("detail") if isinstance(body, dict) else None
  reason = detail if isinstance(detail, str) else f"Leash api returned HTTP {res.status_code}"
  return {"status": "error", "http_status": res.status_code, "reason": reason}


@mcp.tool(
  annotations=ToolAnnotations(
    title="Propose a spending mandate",
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
  ),
)
async def propose_mandate(
  description: str,
  category: str,
  max_cents: Cents,
  location: str | None = None,
  valid_until: str | None = None,
  product_constraints: list[ProductConstraint] | None = None,
  max_quantity: Quantity = 1,
  maximum_purchases: Quantity = 1,
  allow_subscription: StrictBool = False,
  allow_recurring: StrictBool = False,
) -> dict[str, Any]:
  """Ask the user for permission to spend money on one kind of purchase.

  This only proposes. The mandate grants nothing until the user reviews and
  confirms it in Leash, and you cannot confirm it yourself. Tell the user to
  check Leash, then call list_mandates until it shows as active.

  Capture every requirement the user stated and never loosen one. The defaults
  are the strict reading: one unit, one purchase, no subscriptions, no
  recurring charges. Leash shows all of it to the user before they confirm.

  Args:
    description: The user's request word for word, e.g. "Buy a USB-C laptop
      charger for under $40. No subscriptions."
    category: Product category, e.g. "laptop_charger".
    max_cents: Spending cap in integer cents. "Under $40" is 3999. Never a float.
    location: Optional place the purchase is for, e.g. "Kansas City, MO".
    valid_until: Optional ISO 8601 UTC expiry, e.g. "2026-10-11T23:59:00Z".
    product_constraints: Specific product requirements, e.g.
      [{"name": "connector", "operator": "equals", "value": "USB-C"}].
    max_quantity: Most units allowed in one purchase. Default 1.
    maximum_purchases: Most separate purchases allowed. "Buy a charger" is 1.
    allow_subscription: Only true if the user asked for a subscription.
    allow_recurring: Only true if the user accepted recurring charges.

  Returns the proposed mandate, including its id and status "proposed".
  """
  body = {
    "description": description,
    "category": category,
    "max_cents": max_cents,
    "location": location,
    "valid_until": valid_until,
    "product_constraints": [c.model_dump() for c in product_constraints or []],
    "max_quantity": max_quantity,
    "maximum_purchases": maximum_purchases,
    "allow_subscription": allow_subscription,
    "allow_recurring": allow_recurring,
  }
  return await _call_api("POST", "/mandates/propose", json=body)


@mcp.tool(
  annotations=ToolAnnotations(
    title="List active mandates",
    read_only_hint=True,
    open_world_hint=False,
  ),
)
async def list_mandates() -> dict[str, Any]:
  """List the mandates the user has approved and that are active right now.

  Each mandate says what you may buy (category and other constraints, like no
  subscriptions), the most you may spend (max_cents, integer cents: 3999 is
  $39.99), and when it expires. Pick the mandate that matches the purchase before calling
  request_payment. Read-only.

  Returns {"items": [mandate, ...]}.
  """
  return await _call_api("GET", "/mandates", params={"status": "active"})


@mcp.tool(
  annotations=ToolAnnotations(
    title="Request payment for a merchant checkout",
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
  ),
)
async def request_payment(
  mandate_id: str,
  checkout_id: str,
  items: list[ProposedItem],
  total_cents: Cents,
  merchant_name: str | None = None,
  run_id: str | None = None,
) -> dict[str, Any]:
  """Ask Leash to pay for a checkout you started at the merchant.

  Leash does not take your word for what's in the checkout. It fetches the
  checkout from the merchant using checkout_id and checks the real items,
  total, currency, and any subscription or recurring charge against what the
  user confirmed. Your items and total are compared against it as evidence.

  The result says one of:
  - approved: payment credentials that work only for this exact checkout,
    shown once. Use them right away to complete this checkout.
  - pending_user: the user has to review it. Poll check_status with the id.
  - blocked or denied: includes plain-English reasons. Do not retry the same
    checkout.

  Args:
    mandate_id: The id of the active mandate that covers this purchase.
    checkout_id: The merchant's checkout id from starting the checkout.
    items: What you believe you are buying, with unit prices in integer cents.
    total_cents: The total you expect to pay in integer cents. $29.99 is 2999.
    merchant_name: The store's name, e.g. "Volt Supply Co.".
    run_id: Optional id of your current agent run, so Leash can see which
      pages you read.
  """
  body = {
    "mandate_id": mandate_id,
    "checkout_id": checkout_id,
    "proposal": {
      "merchant_name": merchant_name,
      "items": [item.model_dump() for item in items],
      "total_cents": total_cents,
    },
    "run_id": run_id,
  }
  return await _call_api("POST", "/payments", json=body)


@mcp.tool(
  annotations=ToolAnnotations(
    title="Check a payment request",
    read_only_hint=True,
    open_world_hint=False,
  ),
)
async def check_status(payment_id: str) -> dict[str, Any]:
  """Check a payment request you made with request_payment.

  Use this to poll a "pending_user" payment. If the user approves, the result
  includes the payment credentials once; later calls show only the last four
  digits of any card. Read-only.

  Args:
    payment_id: The payment id from request_payment, e.g. "pay_...".
  """
  return await _call_api("GET", f"/payments/{payment_id}")


async def health(_: Request) -> JSONResponse:
  # /health matches the api and the LKE probes; /healthz is the AGENTS.md name.
  return JSONResponse({"status": "ok", "service": "mcp-leash"})


class BearerAuthMiddleware:
  """Require a bearer token and stash it for the Leash tools to forward.

  Only checks that a token is present. The api is the one that validates it, so
  this server never needs to know any secrets.
  """

  def __init__(self, app):
    self.app = app

  async def __call__(self, scope, receive, send):
    if scope["type"] != "http":
      await self.app(scope, receive, send)
      return

    headers = dict(scope["headers"])
    auth = headers.get(b"authorization", b"").decode("latin-1")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
      res = JSONResponse(
        {"status": "error", "reason": "Missing bearer token"},
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
      )
      await res(scope, receive, send)
      return

    reset = bearer_header.set(auth)
    try:
      await self.app(scope, receive, send)
    finally:
      bearer_header.reset(reset)


def _allowed_hosts() -> list[str]:
  # DNS-rebinding protection rejects any Host header not listed here. Once
  # deployed, the public hostname must be added or every request fails.
  raw = os.environ.get("MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*,mcp-leash:*")
  return [h.strip() for h in raw.split(",") if h.strip()]


leash_app = mcp.streamable_http_app(
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
  async with mcp.session_manager.run():
    yield


app = Starlette(
  routes=[
    Route("/health", health),
    Route("/healthz", health),
    Route("/mcp", BearerAuthMiddleware(leash_app)),
  ],
  lifespan=lifespan,
)
