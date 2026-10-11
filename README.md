# LEASH

The firewall between what you tell your AI to buy and what it actually tries to purchase.

Human-confirmed intent → bounded Strands Graph/MCP shopping → independently verified merchant facts → deterministic one-use financial authority → genuine persisted audit/SSE. The signature 2999-cent subscription and legitimate charger share merchant/currency/amount; only verified product identity/recurrence distinguishes them.

Read [AGENTS.md](AGENTS.md), [spec](docs/LEASH_SPEC.md), [build plan](Leash-build-plan.md), [current handoff](api/full-app-handoff.md) and [test results](docs/FULL_APP_TEST_RESULTS.md). Existing custom JWT and Akamai Kubernetes are retained. Current source implements the actual Local Payment Rail Simulator path, with local real SDK Graph/HTTP/SQL/Redis evidence and scripted model choices. Live Akamai injection, current rollout and complete Lithic purchase path are not claimed.

## Local runtime

Use Python3.12+/uv and pnpm10/Node, PostgreSQL and Valkey/Redis. Copy `.env.example` to ignored `.env`, configure DB/JWT/Ed25519 signing and distinct server credentials, inference, service URLs and `LEASH_EXECUTION_ENABLED=1`. Load environment server-side; never commit or put server secrets in NEXT_PUBLIC variables. Each service's locked environment is separate. Shared sources are copied in images; local agents use PYTHONPATH=../../shared (PowerShell `$env:PYTHONPATH="../../shared"`).

| Directory | Start in that directory |
|---|---|
| api | uv sync --frozen; uv run uvicorn main:app --port 8000 |
| services/agents | uv sync --frozen; uv run uvicorn main:app --port 8001 |
| services/mcp-leash | uv sync --frozen; uv run uvicorn main:app --port 8002 |
| services/mcp-store | uv sync --frozen; uv run uvicorn main:app --port 8003 |
| services/store | uv sync --frozen; uv run uvicorn main:app --port 8004 |
| services/webhook | uv sync --frozen; uv run uvicorn main:app --port 8005 |
| web | pnpm install --frozen-lockfile; pnpm dev (NEXT_PUBLIC_API_URL=/backend, API_ORIGIN=http://127.0.0.1:8000) |

Each startup command runs in its own terminal with intended environment. Backend startup verifies/applies checksummed forward migrations. No Compose deployment is required; existing LKE/root-context image deployment is selected. Cameron's `scripts/deploy_lke.sh` builds/applies that topology; deployment changes shared state and must be run by its operator.

## Safety and demo

Review generated terms then explicitly confirm. Run Stop affects one purchase; Emergency Kill affects the account. Neither reverses committed authorization. Unknown outcomes trigger original-event readback and block new purchases. Signup/login/interpretation grants no spending authority. Local authorizations are never settlement or live-money transactions.

Attack Lab defaults off. Only current authenticated allowlisted operators may enable fixed scenarios in separate demo namespaces. Every destination enforces scope; public poison/query/preview and arbitrary provider/reset/replay operations are denied. HTTPS/localhost supports full protected Lab view; HTTP demo operators use authorized Mission Control controls. [Current three-minute demo](docs/demo-script.md) labels live-model and scripted fallback distinctly.

## Validation

[Full test results and commands](docs/FULL_APP_TEST_RESULTS.md) cover actual local SQL/Redis/Graph, service tests, web build/lint and route guards. [Security coverage](docs/LEASH_SECURITY_COVERAGE.md) maps all 137 original + 10 Lab cases with exact limits/gaps; they are not 147 passing tests. Hosted opt-in tests require an isolated allowlisted account, never a shared production DB. No unrestricted Lithic ASA approval is enabled until trusted checkout correlation and provider lifecycle are implemented and verified.
