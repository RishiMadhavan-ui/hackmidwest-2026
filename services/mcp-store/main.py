"""Store MCP server.

Same Streamable HTTP + bearer shape as mcp-leash. Catalog/checkout tools land
here later and will forward to the controlled merchant (STORE_URL). No tools
are registered yet.
"""

import contextvars
import os

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

# Stashed for future tools that forward the caller's bearer to the store API.
bearer_header: contextvars.ContextVar[str] = contextvars.ContextVar("bearer_header")

INSTRUCTIONS = """\
Store MCP for the controlled merchant catalog and checkout.
Tools are not available yet. Use the merchant HTTP API directly until store
MCP tools are registered.
"""

mcp = MCPServer("Store", instructions=INSTRUCTIONS)

# Future tools will forward to STORE_URL (default http://127.0.0.1:8004).


# /health matches the api and the LKE probes; /healthz is the AGENTS.md name.
@mcp.custom_route("/health", methods=["GET"])
@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_: Request) -> JSONResponse:
  return JSONResponse({"status": "ok", "service": "mcp-store"})


class BearerAuthMiddleware:
  """Require a bearer token and stash it for tools to forward later.

  Only checks that a token is present. Downstream services validate it.
  """

  OPEN_PATHS = frozenset({"/health", "/healthz"})

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
  raw = os.environ.get("MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*,mcp-store:*")
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
