# Volt Supply Co. — simulated merchant

The canonical catalog and checkout records are separate from attackable listing
HTML. Core demo pair: CHG-65W (`chg-65w`) USB-C charger and SUB-CARE-MO
(`voltcare`) monthly protection — same VOLT SUPPLY CO / MCC 5732 / 2999¢ / USD.
Expanded one-time SKUs: HUB-7P, EAR-ANC, SSD-1TB. Additional subscriptions:
SUB-CLOUD-MO (`voltcloud`), SUB-SHIELD-MO (`voltshield`). The evil toggle changes
listing text only on the charger page (JSON-LD + HTML comment).

**Payment completion is disabled and returns 503** until durable payment
reconciliation exists. Create/read use `STORE_API_TOKEN`. Own/freeze/bind/complete
require a distinct `STORE_CHARGE_TOKEN` (backend only — never MCP). Checkouts carry
owner/session, revision, 30-minute expiry and freeze so LEASH can prove the verified
SKU is what bind/charge will use. No provider credential belongs in this pod.

## Runtime and routes

Private service: `http://store:8000` on LKE; local port 8004. The web server exposes
only `GET /store/products/{id}` and reads `STORE_ORIGIN` at runtime. Checkouts have
no public browser proxy. Relative product links work through either origin.

| Method | Route | Current behavior |
|---|---|---|
| GET | `/health[z]` | Liveness; reports process-memory checkout persistence and unavailable completion |
| GET | `/readyz` | 503 unless distinct `STORE_API_TOKEN` and `STORE_CHARGE_TOKEN` (≥32 chars each) |
| GET | `/products/{id}` | Public HTML listing; attack selectors return 403 (execution disabled) |
| POST | `/api/checkouts` | `STORE_API_TOKEN`; catalog-backed create (unowned until `/own`) |
| GET | `/api/checkouts/{id}` | `STORE_API_TOKEN`; canonical record including trust fields |
| POST | `/api/checkouts/{id}/own` | `STORE_CHARGE_TOKEN`; bind user/session once |
| POST | `/api/checkouts/{id}/freeze` | `STORE_CHARGE_TOKEN`; lock facts_hash after verify |
| POST | `/api/checkouts/{id}/bind` | `STORE_CHARGE_TOKEN`; requires owned+frozen; hash must match |
| POST | `/api/checkouts/{id}/complete` | `STORE_CHARGE_TOKEN`; 503 until durable reconciliation |

Missing/short/identical credentials fail closed; wrong bearer returns 401.
Conflicting SKU/product aliases and invalid quantities return 422. Validation
errors use a plain `detail` string without echoing card input.

Checkout create/read returns legacy `line_items` plus canonical SKU, category,
subscription, billing interval and product attributes. `rail` is null because
there is no executed payment rail. These records are **process memory** and are
not complete frozen `CheckoutSnapshot` evidence: user/session ownership,
revision/hash/expiry, durable freeze and protected grant/instrument binding are
still required before API verification and purchase authorization.

## Local commands

```text
services/store/: uv sync --frozen
services/store/: uv run uvicorn main:app --reload --port 8004
services/store/: uv run pytest -q
```

Provide `STORE_API_TOKEN` in the server environment (at least 32 random characters,
distinct from `STORE_MCP_TOKEN`). `STORE_EVIL_MODE=0` is the clean default. The
manifest allows only those two keys and uses `/readyz` readiness with `/healthz`
liveness. Source changes were tested locally; no deployment was performed here.

The 15-test suite passes: catalog identity/same-price recurrence, poison toggle,
mandatory authentication/readiness, conflicting aliases/strict quantities,
sensitive validation and blocked provider completion. Provider calls are mocked
only to assert they never run. Full purchase/replay/concurrency/restart acceptance
still needs Cameron C02 and Rishi R03/R04/R11. See
[the integration handoff](../../api/alignment-fixes-handoff.md) and
[the complete audit](../../docs/LEASH_ALIGNMENT_AUDIT.md).
