# Leash MCP service

Owner: Aditya. Deployment `mcp-leash`, port 8002, MCP at `/mcp` (official SDK 2.x, Streamable HTTP, stateless, JSON responses). `GET /health` and `GET /healthz` are open.

Payment tools for any agent: `propose_mandate`, `list_mandates`, `request_payment`, `check_status`. Each is a thin pass-through to one api route. The caller's bearer is forwarded unchanged and the api decides what it allows. No tool can confirm a mandate, approve a payment, raise a limit, or touch the kill switch. Money is strict integer cents.

Shopping tools are a separate service with separate credentials: `services/mcp-store`. This service never holds store secrets.

## Run

```
cd services/mcp-leash
uv sync
uv run uvicorn main:app --port 8002
```

| Variable | Used for |
|---|---|
| `API_URL` | Where the tools send requests (`http://api:8000` on LKE) |
| `MCP_ALLOWED_HOSTS` | Host headers accepted (default `localhost:*,127.0.0.1:*,mcp-leash:*`) |

## Test

```
uv run pytest
```
