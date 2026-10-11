# Store MCP service

Owner: Aditya. Deployment `mcp-store`, port 8003, MCP at `/mcp` (official SDK 2.x, Streamable HTTP, stateless, JSON responses). `GET /health` and `GET /healthz` are open. The store itself (catalog, checkout, protected charge) is Cameron's; this is the agent-facing door to it.

Tools: `browse`, `create_checkout`, `complete_checkout`.

- Callers need `Authorization: Bearer $STORE_MCP_TOKEN`; with no token configured it refuses every call. It never sees or forwards the Leash token, and it calls the store with its own credential (`STORE_API_TOKEN`). Payment tools live in the separate `services/mcp-leash`.
- `browse` only reaches the store at `STORE_URL` (or the public addresses in `STORE_PUBLIC_URLS`, which map onto it). Other hosts, non-HTTP schemes, and redirects off the store are refused, so it can't be used to probe services inside the cluster.
- Raw HTML stays here. Each page is hashed, inspected for hidden instruction-like text, redacted, and snapshotted to Object Storage under `runs/{run_id}/{sha256}.html`. The agent gets the page text (hidden parts included; the demo shopper is gullible on purpose) plus an evidence record: url, sha256, findings, excerpt, snapshot metadata.
- Everything it returns is agent-observed evidence. The Leash API must fetch canonical checkout facts itself; that retrieval/payment pipeline remains pending. The merged simulated store supports authenticated create/read, while completion returns 503 until protected binding/payment operations exist.

`evidence/redact.py` is a copy of `services/agents/provenance/redact.py`; a test fails if they drift.

## Run

```
cd services/mcp-store
uv sync
uv run uvicorn main:app --port 8003
```

| Variable | Used for |
|---|---|
| `STORE_URL` | Required controlled store address; LKE `http://store:8000`, local `http://127.0.0.1:8004` |
| `STORE_PUBLIC_URLS` | Optional comma-separated public store addresses that map onto `STORE_URL` |
| `STORE_MCP_TOKEN` | Required bearer for callers |
| `STORE_API_TOKEN` | Required private merchant credential (>=32 characters), distinct from the MCP bearer |
| `MCP_ALLOWED_HOSTS` | Host headers accepted (default `localhost:*,127.0.0.1:*,mcp-store:*`) |
| `OBJ_ENDPOINT`, `OBJ_BUCKET`, `OBJ_ACCESS_KEY`, `OBJ_SECRET_KEY` | Redacted page snapshots (same names as the Akamai workshop starter) |

## Test

```
uv run pytest
```
