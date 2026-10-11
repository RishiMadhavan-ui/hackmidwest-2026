# LEASH store — Volt Supply Co. (simulated merchant)

Canonical catalog and checkout truth for the demo. Listing HTML may include an
evil-mode injection; `POST /api/checkouts` always reflects the real SKU.

**Label:** simulated merchant + Lithic sandbox only — no real customer funds.

## Deploy (LKE)

Same pattern as api / webhook: image from `services/store/Dockerfile`, manifest
`k8s/store.yaml`, applied by `scripts/deploy_lke.sh`.

| Reachability | URL |
|---|---|
| In-cluster (mcp-store, api) | `http://store:8000` |
| Public (NodeBalancer via web rewrite) | `http://<NB>/store/...` |

Example: `http://<NB>/store/products/chg-65w` · `http://<NB>/store/healthz`

## Routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Liveness |
| `GET` | `/products/{id}` | Server-rendered HTML (`chg-65w`, `voltcare`; aliases `CHG-65W`, `SUB-CARE-MO`) |
| `POST` | `/api/checkouts` | Create checkout from catalog (`product_id` or `sku`) |
| `GET` | `/api/checkouts/{id}` | Trusted read for API verification |
| `POST` | `/api/checkouts/{id}/complete` | Lithic sandbox `simulate/authorize` for that checkout |

Evil listing: `STORE_EVIL_MODE=1` in app-env and/or `?evil=1` on the product route.

## Run locally

```bash
cd services/store
uv sync
STORE_EVIL_MODE=0 uv run uvicorn main:app --reload --port 8004
```

## Complete / Lithic

`/complete` calls `leash_shared.lithic.simulate_authorization` with the
checkout's exact `total_cents`, descriptor `VOLT SUPPLY CO`, and MCC `5732`
(same MCC for both SKUs so rail merchant controls cannot tell them apart).

Requires `card_token` (Lithic instrument). PAN/CVV from mcp-store are accepted
on the wire but never logged or persisted and cannot drive simulate alone.

## Env

| Variable | Purpose |
|---|---|
| `STORE_EVIL_MODE` | `1` to inject JSON-LD + comment on charger page |
| `STORE_API_TOKEN` | Optional bearer for `/api/*` (mcp-store sends this) |
| `LITHIC_API_KEY` | Required for `/complete` sandbox simulate |
| `LITHIC_ENVIRONMENT` | `sandbox` (default) |
