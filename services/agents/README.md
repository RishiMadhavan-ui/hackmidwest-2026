# Leash agents service

Owner: Aditya. Port 8001.

**Graph integrated and locally tested.** Actual bounded SDK Graph uses both MCP servers and API-verified human launches/leases/private run credentials. Real HTTP/SQL/Redis acceptance blocks the subscription, quarantines and buys a clean alternative under unchanged authority. Model choices were scripted; live inference/injection/deployment remains a separate gate. See [current handoff](../../api/full-app-handoff.md) and [results](../../docs/FULL_APP_TEST_RESULTS.md).

- `shopper/`: the demo shopper, a real Strands agent that is **gullible on purpose**. Don't add prompt-injection defenses to it; Leash's protection lives in the api, the store, and the rail. All its tools come from two separate MCP services: `services/mcp-store` (`browse`, `create_checkout`, `complete_checkout`) and `services/mcp-leash` (mandates and payments).
- `provenance/`: before/after tool hooks that emit sanitized trace events, plus a source record for every page the shopper reads, built from the store MCP's evidence (sha256, hidden text, suspicious phrases, redacted snapshot). Raw HTML never enters this service. Events reach the api through a durable outbox.
- `guardian/`: advisory investigation. It recommends `block` or `review`, or reports `no_findings`; it never approves a payment.

## Run

`shared/` isn't an installable package yet, so put it on the path:

```
cd services/agents
uv sync
PYTHONPATH=../../shared uv run uvicorn main:app --port 8001
```

In PowerShell, set `$env:PYTHONPATH="../../shared"` first. To keep settings in a file, put them in `services/agents/.env` (gitignored) and use `uv run --env-file .env ...`.

The legacy operator CLI additionally takes `--mandate`,
`--run-id` and `--launch-id` from a fresh authenticated human launch, and optional
`--start-url`. Do not invent identifiers or reuse an old launch after Stop.

## On LKE

Deployment `agents`, reached in-cluster at `http://agents:8000` (container port 8000, ClusterIP only). The image builds from the repo root because it copies in `shared/leash_shared`:

```
docker build -f services/agents/Dockerfile .
```

`scripts/deploy_lke.sh` does this. The two MCP services are separate deployments: the Leash MCP at `http://mcp-leash:8002/mcp` (`services/mcp-leash`) and the store MCP at `http://mcp-store:8003/mcp` (`services/mcp-store`). Settings come from the `app-env` secret (the team `.env`), with `API_URL`, `MCP_LEASH_URL` and `MCP_STORE_URL` set in `k8s/agents.yaml`.

## Routes

`GET /health` and `GET /healthz` are open. Everything else needs `Authorization: Bearer $AGENTS_SERVICE_TOKEN`; with no token configured those routes refuse every call (503). Keep the service off the public ingress too, but that alone isn't authentication.

- `POST /runs` with `{task, mandate_id, run_id, launch_id, start_url?, agent_mode?, sku?, claim_sku?}` queues the supplied run with paired `agent_id`/private `agent_credential` dispatched by API (never browser). Missing launch identifiers return 409; accepting the queue is not evidence that the execution backend accepted the launch.
- `GET /runs/{run_id}` returns status, whether the run registered with the api, redacted output, and trace events.
- `POST /guardian/evaluate` with `{mandate, checkout?, proposal?, provenance?, trace?}` returns advisory findings. It can take up to 20 seconds when the model runs, so keep it off the payment's critical path.

`agent_mode`:

- `"live"` (default): the real model shops.
- `"scripted"`: a **labeled fixture**. The shopper's choices are scripted (check out `sku`, tell Leash it's buying `claim_sku`), but every tool call is real: store pages, the store's checkout, and the Leash api through MCP. The run and every trace event carry `agent_mode: "scripted"`, and the run is labeled "Simulated compromised agent (scripted fixture)". Never present it as a live model falling for the injection.

The same fixture selector from the CLI: `--scripted-sku SUB-CARE-MO --claim-sku CHG-65W`.
The Graph records the selected SKU as an agent claim; no claimed SKU substitutes
for the API's checkout evidence. A scripted Lab run supplies `recovery_sku=CHG-65W-SAFE`; model choices remain labeled fixtures while all tools and financial decisions are real.

## Run registration and trace delivery

The human launch API must register and bind the run to its owner, mandate and
mode before dispatch. The Graph claims that exact run through the implemented private
execution API; it cannot autonomously register a replacement with a static token.
Production requires `API_URL`. There is no local-only production launch. Legacy
registration remains only for injected test runners.

Normal human/UI launches supply a private exact-run credential and account-owned agent ID; no global token changes owner. Historical CLI tokens remain mode-separated/bound to their original human. There is no scripted/live credential fallback or permission to execute a scripted run under a live mandate.

Trace events are redacted/fsynced to persistent TRACE_SPOOL_DIR. Private UI/Lab workers use the `delegated` lane and AGENTS_SERVICE_TOKEN to `/internal/agent-events`; API validates registered run/agent/mode before durable provenance/workflow intake. This lane can deliver after worker expiry/restarts and cannot approve money. Historical static lanes retain `/provenance`/`/workflow-events`. Transient failures retry; permanent rejected events remain inspectable. `/runs/{id}` convenience registry is bounded/recent; canonical history and SSE live in API PostgreSQL.

## Environment

| Variable | Used for |
|---|---|
| `INFERENCE_BASE_URL`, `INFERENCE_API_KEY`, `MODEL_ID` | Akamai inference through `make_model()`. The workshop names `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `CHAT_MODEL` also work, as a matched pair |
| `AGENTS_SERVICE_TOKEN` | Required bearer for `/runs` and `/guardian/evaluate` |
| `AGENT_TOKEN_SHOPPER` | Live runs only: bearer for the Leash MCP, run registration, and trace intake (bound to live mode) |
| `AGENT_TOKEN_SHOPPER_SCRIPTED` | Scripted runs only: the same uses, as a separate credential bound to scripted mode |
| `SHOPPER_AGENT_ID`, `SHOPPER_SCRIPTED_AGENT_ID` | Agent ids each credential is bound to (defaults `agt_shopper`, `agt_shopper_scripted`) |
| `API_URL` | Required execution lease/checkpoint API and trace intake |
| `MCP_LEASH_URL` | Leash MCP service (default `http://localhost:8002/mcp`; `MCP_URL` also accepted) |
| `MCP_STORE_URL` | Store MCP service (default `http://localhost:8003/mcp`) |
| `STORE_MCP_TOKEN` | Bearer for the store MCP; never the Leash token |
| `TRACE_SPOOL_DIR` | Trace outbox (default `./trace-spool`; `/app/trace-spool` in the image). Mount a volume to survive pod restarts |

## Test

```
uv run pytest -m "not live_inference"
```

- `tests/test_workflow.py` exercises the actual SDK Graph with fixture ports. Runtime, control and workflow-event tests cover actual Strands model hooks, clean recovery context, cancellation, strict lease validation and restartable event delivery. Mock API tests do not prove distributed fencing.
- `tests/test_wiring_local.py` retains the historical single-agent HTTP fixture with both real MCP services and stub API/store servers. Its canned decisions do not prove current Graph or payment acceptance.
- `tests/test_shopper_loop.py` drives the real Strands event loop with a **scripted fixture model**. It proves the hooks, redaction, and correlation; it is not a live agent run.
- The two live inference tests in `tests/test_llm.py` run only when an inference endpoint is configured. Every other test has inference, api, and storage settings cleared, even if your shell has them.
