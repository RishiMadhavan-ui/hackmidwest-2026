# Volt Supply Co. — simulated merchant

The canonical catalog and checkout records are separate from attackable listing
HTML. CHG-65W (`chg-65w`) is a USB-C 65W laptop charger; SUB-CARE-MO (`voltcare`)
is a monthly subscription. Both use VOLT SUPPLY CO, MCC 5732, 2999 cents and USD.
The evil toggle changes listing text only, including JSON-LD and an HTML comment.

**Payment completion is disabled and returns 503.** A caller's payment/card ID
cannot establish spending authority. No Lithic call or completed/paid projection
is produced. The former direct simulation call was removed during the authorized
alignment fixes because checkout/grant correlation and durable payment operations
do not exist yet. No provider credential belongs in this pod.

## Runtime and routes

Private service: `http://store:8000` on LKE; local port 8004. The web server exposes
only `GET /store/products/{id}` and reads `STORE_ORIGIN` at runtime. Checkouts have
no public browser proxy. Relative product links work through either origin.

| Method | Route | Current behavior |
|---|---|---|
| GET | `/health[z]` | Liveness; reports process-memory checkout persistence and unavailable completion |
| GET | `/readyz` | 503 without a store credential of at least 32 characters |
| GET | `/products/{id}` | Public HTML listing; `?evil=1` or `STORE_EVIL_MODE=1` selects poison |
| POST | `/api/checkouts` | Authenticated catalog-backed checkout from `{sku, quantity}` or `{product_id, quantity}` |
| GET | `/api/checkouts/{id}` | Authenticated canonical record read |
| POST | `/api/checkouts/{id}/complete` | Authenticated 503; no payment side effect |

All `/api/*` calls require `Authorization: Bearer $STORE_API_TOKEN`. Missing or
short server configuration fails closed; invalid/missing bearer returns 401.
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
