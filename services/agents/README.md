# Leash agents service

Owner: Aditya. Port 8001.

- `shopper/`: the demo shopper, a real Strands agent that is **gullible on purpose**. Don't add prompt-injection defenses to it; Leash's protection lives in the api, the store, and the rail.
- `provenance/`: before/after tool hooks that emit sanitized trace events, plus a source record for every page the shopper reads (sha256, hidden text, suspicious phrases, snapshot).
- `guardian/`: advisory investigation. It recommends `block` or reports `no_findings`; it never approves a payment.

## Run

`shared/` isn't an installable package yet, so put it on the path:

```
cd services/agents
uv sync
PYTHONPATH=../../shared uv run uvicorn main:app --port 8001
PYTHONPATH=../../shared uv run python -m shopper "Buy a USB-C laptop charger for under \$40. No subscriptions." --mandate mnd_... --start-url http://localhost:8004/products/chg-65w
```

In PowerShell, set `$env:PYTHONPATH="../../shared"` first.

Routes: `GET /healthz`, `POST /runs`, `GET /runs/{run_id}` (status, redacted output, trace events), `POST /guardian/evaluate`. The routes have no auth yet, so keep this service internal to the cluster.

`POST /runs` takes `{task, mandate_id?, start_url?, agent_mode?, sku?, claim_sku?}`:

- `agent_mode: "live"` (default): the real model shops.
- `agent_mode: "scripted"`: a **labeled fixture**. The shopper's choices are scripted (check out `sku`, tell Leash it's buying `claim_sku`), but every tool call is real: store pages, the store's checkout, and the Leash api through MCP. The run and every trace event carry `agent_mode: "scripted"`, and the run is labeled "Simulated compromised agent (scripted fixture)". Never present it as a live model falling for the injection.

The same thing from the CLI: `--scripted-sku SUB-CARE-MO --claim-sku CHG-65W`.

## Environment

| Variable | Used for |
|---|---|
| `INFERENCE_BASE_URL`, `INFERENCE_API_KEY`, `MODEL_ID` | Akamai inference through `make_model()` |
| `MCP_URL` | Leash tools for the shopper (default `http://localhost:8002/mcp`) |
| `AGENT_TOKEN_SHOPPER` | Shopper's bearer for MCP and trace intake |
| `API_URL` | Trace intake (`POST /provenance`); without it, traces only go to logs |
| `STORE_URL` | Store checkout API (default `http://localhost:8004`) |
| `OBJ_ENDPOINT`, `OBJ_BUCKET`, `OBJ_ACCESS_KEY`, `OBJ_SECRET_KEY` | Page snapshots; placeholder names until the workshop names are confirmed |

## Test

```
uv run pytest
```

`tests/test_wiring_local.py` starts the real MCP server as a subprocess with stub api/store servers and runs the scripted shopper over HTTP; the stubs' decisions are canned. Loop tests in `tests/test_shopper_loop.py` drive the real Strands event loop with a **scripted fixture model**. They prove the hooks, redaction, and correlation; they are not a live agent run. The two live inference tests in `tests/test_llm.py` skip unless `INFERENCE_API_KEY` and `INFERENCE_BASE_URL` are set.
