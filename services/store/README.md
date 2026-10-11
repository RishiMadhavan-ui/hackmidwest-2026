# Volt Supply Co. — simulated merchant

Owner Cameron. Canonical catalog is separate from untrusted listing HTML. CHG-65W/chg-65w, clean CHG-65W-SAFE/chg-65w-clean and SUB-CARE-MO/voltcare share VOLT SUPPLY CO/MCC5732/USD2999cents. Only subscription recurrence/product category differs. Public `evil` selection and legacy unrestricted preview return403; STORE_EVIL_MODE cannot enable them. Enabled allowlisted Lab runs receive scoped injected listing through regular Store MCP browsing.

Expanded catalog preserves Cameron's HUB-7P, EAR-ANC, SSD-1TB, SUB-CLOUD-MO and SUB-SHIELD-MO products. `/catalog` lists every canonical product; the clean charger remains first for recovery. Listing HTML is untrusted and does not authorize any product. Store pages label the actual Local Payment Rail Simulator; no Lithic purchase approval is enabled.

With `LEASH_EXECUTION_ENABLED=1`, create/freeze/projection/completion delegate to private API-owned PostgreSQL records through execution_bridge.py and distinct MERCHANT_BACKEND_TOKEN. Checkout owner/run/generation/revision/hash/expiry are derived from a validated scope; they cannot be replaced by model facts. API independently retrieves the configured authenticated projection. Protected complete uses current mcp-store scope + STORE_CHARGE_TOKEN and only the original stable exact checkout/payment/authorization event; unknown results stay reconciling, never retry with another event. Actual local SDK Graph/MCP/API/SQL/Redis acceptance is in [test results](../../docs/FULL_APP_TEST_RESULTS.md).

| Route | Boundary |
|---|---|
| `/health`, `/healthz` | Liveness and truthful selected persistence/completion mode |
| `/readyz` | Requires configured distinct store API/charge credentials; runtime connections still fail closed |
| `/catalog`, `/products/{id}` | Clean catalog/listing; poison only via enabled isolated run scope; public selectors denied |
| `POST /api/checkouts` | STORE_API_TOKEN and current scope; immutable canonical catalog, no caller SKU/price authority override |
| `GET /api/checkouts/{id}` | Scoped execution mode requires distinct backend merchant reader; fixed projection from API SQL |
| `POST /api/checkouts/{id}/complete` | STORE_CHARGE_TOKEN plus exact current execution scope; original durable payment/charge association |
| Legacy own/freeze/bind | Authenticated compatibility primitives; cannot substitute for current API scope/projection/rail grant |

Legacy disabled-execution adapter has process-memory checkouts and is not the selected durable path. No provider credentials belong in this pod. Use API_URL, `LEASH_EXECUTION_ENABLED=1`, STORE_API_TOKEN/STORE_CHARGE_TOKEN/MERCHANT_BACKEND_TOKEN, WEBHOOK_URL/WEBHOOK_CHARGE_TOKEN server-side; each secret distinct≥32chars. Private LKE store:8000; local port8004. Web only proxies safe product listing GET, no public checkout mutation.

From this directory: `uv sync --frozen`, `uv run uvicorn main:app --port 8004`, `uv run pytest -q`. Current 30 tests + 17 subtests pass; actual full-chain acceptance separate. No deployed service/shared DB/provider was mutated. [Current handoff](../../api/full-app-handoff.md) documents rollout/migrations/trust limits; [coverage](../../docs/LEASH_SECURITY_COVERAGE.md) lists unexecuted substitution/restart/provider cases.
