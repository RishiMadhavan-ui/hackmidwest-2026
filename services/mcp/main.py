import os

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

# mcp 2.x renamed FastMCP to MCPServer and moved stateless_http/json_response
# from the constructor onto streamable_http_app().
mcp = MCPServer("Leash")


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_: Request) -> JSONResponse:
  return JSONResponse({"status": "ok", "service": "mcp"})


def _allowed_hosts() -> list[str]:
  # DNS-rebinding protection rejects any Host header not listed here. Once
  # deployed, the public hostname must be added or every request fails.
  raw = os.environ.get("MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*,mcp:*")
  return [h.strip() for h in raw.split(",") if h.strip()]


app = mcp.streamable_http_app(
  stateless_http=True,
  json_response=True,
  transport_security=TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=_allowed_hosts(),
  ),
)
