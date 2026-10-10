"""Leash MCP server.

A thin, stateless adapter: each tool forwards to exactly one api route with the
caller's bearer token, unchanged. The api decides whether the token is valid
and what the agent may do. Nothing here can approve a mandate or payment, raise
a limit, or touch the kill switch; those routes need a human's token.
"""

import contextvars
import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse

# The caller's raw "Bearer ..." header for the current request. Set by
# BearerAuthMiddleware, read by every tool.
bearer_header: contextvars.ContextVar[str] = contextvars.ContextVar("bearer_header")

# POST /payments waits up to 20 s on the guardian, so give the api headroom.
API_TIMEOUT_SECONDS = 30.0

INSTRUCTIONS = """\
Leash is a payment firewall. You never get the user's real card. To spend money:
1. Call list_mandates to find an active mandate that covers the purchase. If none
   fits, call propose_mandate and tell the user to approve it on their phone.
   You cannot approve it yourself.
2. Call request_payment with the exact cart. If approved, you get a single-use
   card locked to that merchant and amount, shown once. If it needs the user,
   poll check_status. If denied, read the reasons and stop.
All money is integer cents: $180.00 is 18000.
"""

# mcp 2.x renamed FastMCP to MCPServer and moved stateless_http/json_response
# from the constructor onto streamable_http_app().
mcp = MCPServer("Leash", instructions=INSTRUCTIONS)


# TODO: switch to leash_shared.models.Merchant and CartItem once models.py lands.
class Merchant(BaseModel):
  name: str = Field(description="Merchant name as shown on the site, e.g. 'Crossroads Hotel'")
  descriptor: str = Field(
    description="Name that appears on the card network, e.g. 'CROSSROADS HOTEL KC'"
  )
  mcc: str = Field(description="4-digit merchant category code as a string, e.g. '7011'")
  url: str = Field(description="URL of the page where you're checking out")


class CartItem(BaseModel):
  name: str = Field(description="Item name exactly as the merchant lists it")
  quantity: int = Field(ge=1)
  unit_cents: int = Field(ge=0, description="Price per unit in integer cents. $158.00 is 15800.")


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
    return {"status": "error", "reason": "Leash api timed out. Try check_status or retry later."}
  except httpx.HTTPError:
    return {"status": "error", "reason": "Leash api is unreachable. Retry later."}

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
  max_cents: int,
  location: str | None = None,
  valid_until: str | None = None,
) -> dict[str, Any]:
  """Ask the user for permission to spend money on one kind of purchase.

  This only proposes. The mandate stays "proposed" until a human approves it on
  their phone, and you cannot approve it yourself. Tell the user to check their
  phone, then call list_mandates until it shows as active.

  Args:
    description: The user's request in plain words, e.g. "hotel in Kansas City
      on Saturday, max $180".
    category: Purchase category, e.g. "lodging".
    max_cents: Spending cap in integer cents. $180.00 is 18000. Never a float.
    location: Optional place the purchase is for, e.g. "Kansas City, MO".
    valid_until: Optional ISO 8601 UTC expiry, e.g. "2026-10-11T23:59:00Z".

  Returns the proposed mandate, including its id and status "proposed".
  """
  body = {
    "description": description,
    "category": category,
    "max_cents": max_cents,
    "location": location,
    "valid_until": valid_until,
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

  Each mandate says what you may buy (category, location, merchant allowlist),
  the most you may spend (max_cents, integer cents: 18000 is $180.00), and when
  it expires. Pick the mandate that matches the purchase before calling
  request_payment. Read-only.

  Returns {"items": [mandate, ...]}.
  """
  return await _call_api("GET", "/mandates", params={"status": "active"})


@mcp.tool(
  annotations=ToolAnnotations(
    title="Request a single-use card for a cart",
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
  ),
)
async def request_payment(
  mandate_id: str,
  merchant: Merchant,
  items: list[CartItem],
  total_cents: int,
  run_id: str | None = None,
) -> dict[str, Any]:
  """Ask Leash to pay for an exact cart under an active mandate.

  Leash checks the cart against the mandate and the pages you read. The result
  has one of three statuses:
  - "approved": includes a single-use virtual card (number, expiry, CVV) locked
    to this merchant and at most total_cents. It is shown only once, so use it
    right away at this merchant's checkout. It will be declined anywhere else.
  - "pending_user": the user has to approve it on their phone. Poll
    check_status with the payment id. The card appears there once, after they
    approve.
  - "denied": includes plain-English reasons. Do not retry the same cart.

  Args:
    mandate_id: The id of the active mandate that covers this purchase.
    merchant: Who you're paying: name, card-network descriptor, MCC, checkout URL.
    items: Every line item, with unit prices in integer cents.
    total_cents: The final total in integer cents, including taxes and fees.
      $165.00 is 16500.
    run_id: Optional id of your current agent run, so Leash can see which pages
      you read.
  """
  body = {
    "mandate_id": mandate_id,
    "cart": {
      "merchant": merchant.model_dump(),
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

  Use this to poll a "pending_user" payment. When the user approves, the result
  includes the single-use card details once; later calls show only the last four
  digits. Status is one of pending_guardian, pending_user, approved, denied,
  expired, or used. Read-only.

  Args:
    payment_id: The payment id from request_payment, e.g. "pay_...".
  """
  return await _call_api("GET", f"/payments/{payment_id}")


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_: Request) -> JSONResponse:
  return JSONResponse({"status": "ok", "service": "mcp"})


class BearerAuthMiddleware:
  """Require a bearer token and stash it for the tools to forward.

  Only checks that a token is present. The api is the one that validates it, so
  this server never needs to know any secrets.
  """

  OPEN_PATHS = frozenset({"/healthz"})

  def __init__(self, app):
    self.app = app

  async def __call__(self, scope, receive, send):
    if scope["type"] != "http" or scope["path"] in self.OPEN_PATHS:
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
  raw = os.environ.get("MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*,mcp:*")
  return [h.strip() for h in raw.split(",") if h.strip()]


app = BearerAuthMiddleware(
  mcp.streamable_http_app(
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
      enable_dns_rebinding_protection=True,
      allowed_hosts=_allowed_hosts(),
    ),
  )
)
