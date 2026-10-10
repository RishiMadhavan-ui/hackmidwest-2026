# Leash MCP service

Owner: Aditya. Port 8002. Two MCP servers (official SDK 2.x, Streamable HTTP, stateless, JSON responses) in one service, with separate credentials. `GET /health` and `GET /healthz` are open.

## Leash MCP: `/mcp`

Payment tools for any agent: `propose_mandate`, `list_mandates`, `request_payment`, `check_status`. Each is a thin pass-through to one api route. The caller's bearer is forwarded unchanged and the api decides what it allows. No tool can confirm a mandate, approve a payment, raise a limit, or touch the kill switch. Money is strict integer cents.

## Store MCP: `/store/mcp`

Shopping tools at the Volt Supply store: `browse`, `create_checkout`, `complete_checkout`.

- Callers need `Authorization: Bearer $STORE_MCP_TOKEN`; with no token configured it refuses every call. It never sees or forwards the Leash token, and it calls the store with its own credential (`STORE_API_TOKEN`).
- `browse` only reaches the store at `STORE_URL` (or the public addresses in `STORE_PUBLIC_URLS`, which map onto it). Other hosts, non-HTTP schemes, and redirects off the store are refused, so it can't be used to probe services inside the cluster.
- Raw HTML stays here. Each page is hashed, inspected for hidden instruction-like text, redacted, and snapshotted to Object Storage under `runs/{run_id}/{sha256}.html`. The agent gets the page text (hidden parts included; the demo shopper is gullible on purpose) plus an evidence record: url, sha256, findings, excerpt, snapshot metadata.
- Everything it returns is agent-observed evidence. The Leash api fetches canonical checkout facts from the store itself.

`evidence/redact.py` is a copy of `services/agents/provenance/redact.py`; a test fails if they drift.

## Run

```
cd services/mcp
uv sync
uv run uvicorn main:app --port 8002
```

## Environment

| Variable | Used for |
|---|---|
| `API_URL` | Where the Leash tools send requests |
| `MCP_ALLOWED_HOSTS` | Host headers accepted (default `localhost:*,127.0.0.1:*,mcp:*`) |
| `STORE_URL` | The store's address (required for the store tools) |
| `STORE_PUBLIC_URLS` | Optional comma-separated public store addresses that map onto `STORE_URL` |
| `STORE_MCP_TOKEN` | Required bearer for `/store/mcp` |
| `STORE_API_TOKEN` | Optional credential sent to the store, pending the scheme agreed with Cameron |
| `OBJ_ENDPOINT`, `OBJ_BUCKET`, `OBJ_ACCESS_KEY`, `OBJ_SECRET_KEY` | Redacted page snapshots (same names as the Akamai workshop starter) |

## Test

```
uv run pytest
```
