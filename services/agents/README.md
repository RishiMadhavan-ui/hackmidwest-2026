# Leash agents service

Owner: Aditya. Port 8001.

- `shopper/`: the demo shopper, a real Strands agent that is **gullible on purpose**. Don't add prompt-injection defenses to it; Leash's protection lives in the api, the store, and the rail.
- `provenance/`: before/after tool hooks that emit sanitized trace events, plus a source record for every page the shopper reads (sha256, hidden text, suspicious phrases, redacted snapshot). Events reach the api through a durable outbox.
- `guardian/`: advisory investigation. It recommends `block` or `review`, or reports `no_findings`; it never approves a payment.

## Run

`shared/` isn't an installable package yet, so put it on the path:

```
cd services/agents
uv sync
PYTHONPATH=../../shared uv run uvicorn main:app --port 8001
PYTHONPATH=../../shared uv run python -m shopper "Buy a USB-C laptop charger for under \$40. No subscriptions." --mandate mnd_... --start-url http://localhost:8004/products/chg-65w
```

In PowerShell, set `$env:PYTHONPATH="../../shared"` first. To keep settings in a file, put them in `services/agents/.env` (gitignored) and use `uv run --env-file .env ...`.

## On LKE

Deployment `agents`, reached in-cluster at `http://agents:8000` (container port 8000, ClusterIP only). The image builds from the repo root because it copies in `shared/leash_shared`:

```
docker build -f services/agents/Dockerfile .
```

`scripts/deploy_lke.sh` does this, and also deploys the MCP server as `mcp` at `http://mcp:8002/mcp`. Settings come from the `app-env` secret (the team `.env`), with `API_URL` and `MCP_URL` set in `k8s/agents.yaml`.

## Routes

`GET /health` and `GET /healthz` are open. Everything else needs `Authorization: Bearer $AGENTS_SERVICE_TOKEN`; with no token configured those routes refuse every call (503). Keep the service off the public ingress too, but that alone isn't authentication.

- `POST /runs` with `{task, mandate_id, start_url?, agent_mode?, sku?, claim_sku?}` returns `run_id`.
- `GET /runs/{run_id}` returns status, whether the run registered with the api, redacted output, and trace events.
- `POST /guardian/evaluate` with `{mandate, checkout?, proposal?, provenance?, trace?}` returns advisory findings. It can take up to 20 seconds when the model runs, so keep it off the payment's critical path.

`agent_mode`:

- `"live"` (default): the real model shops.
- `"scripted"`: a **labeled fixture**. The shopper's choices are scripted (check out `sku`, tell Leash it's buying `claim_sku`), but every tool call is real: store pages, the store's checkout, and the Leash api through MCP. The run and every trace event carry `agent_mode: "scripted"`, and the run is labeled "Simulated compromised agent (scripted fixture)". Never present it as a live model falling for the injection.

The same from the CLI: `--scripted-sku SUB-CARE-MO --claim-sku CHG-65W`.

## Run registration and trace delivery

When `API_URL` and `AGENT_TOKEN_SHOPPER` are set, every run registers with the api (`POST /agent-runs` with the agent token) before it emits a single trace event. The api binds the run to the agent's user, the mandate, and the live/scripted label. If registration fails, the run fails and nothing is traced.

Trace events are redacted, written to `TRACE_SPOOL_DIR`, and delivered to `POST /provenance` in order by a background worker. It retries through api outages, sets aside events the api permanently rejects (`rejected/`), and on restart delivers anything still spooled. The api deduplicates by `event_id`, so retries are safe. Without `API_URL`, the service runs local-only: no registration, traces go to logs.

## Environment

| Variable | Used for |
|---|---|
| `INFERENCE_BASE_URL`, `INFERENCE_API_KEY`, `MODEL_ID` | Akamai inference through `make_model()`. The workshop names `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `CHAT_MODEL` also work, as a matched pair |
| `AGENTS_SERVICE_TOKEN` | Required bearer for `/runs` and `/guardian/evaluate` |
| `AGENT_TOKEN_SHOPPER` | Shopper's bearer for MCP, run registration, and trace intake |
| `API_URL` | Run registration and trace intake; without it, local-only mode |
| `MCP_URL` | Leash tools for the shopper (default `http://localhost:8002/mcp`) |
| `STORE_URL` | Store checkout API (default `http://localhost:8004`) |
| `STORE_API_TOKEN` | Optional bearer for the store's checkout API only, pending the scheme agreed with Cameron |
| `TRACE_SPOOL_DIR` | Trace outbox (default `./trace-spool`; `/app/trace-spool` in the image). Mount a volume to survive pod restarts |
| `OBJ_ENDPOINT`, `OBJ_BUCKET`, `OBJ_ACCESS_KEY`, `OBJ_SECRET_KEY` | Redacted page snapshots (same names as the Akamai workshop starter) |

## Test

```
uv run pytest
```

- `tests/test_wiring_local.py` starts the real MCP server as a subprocess with stub api/store servers and runs the scripted shopper over HTTP. The stubs' decisions are canned.
- `tests/test_shopper_loop.py` drives the real Strands event loop with a **scripted fixture model**. It proves the hooks, redaction, and correlation; it is not a live agent run.
- The two live inference tests in `tests/test_llm.py` run only when an inference endpoint is configured. Every other test has inference, api, and storage settings cleared, even if your shell has them.
