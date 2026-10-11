# LEASH payment rail (`services/webhook`)

Labeled **local payment rail simulator** plus Valkey grant store. Lithic ASA will share `decide.py` / `handler.authorize` later.

## Run locally

```bash
# Optional Valkey (omit VALKEY_URL to use in-memory store for a single process)
docker run --rm -p 6379:6379 valkey/valkey:8-alpine

export VALKEY_URL=redis://127.0.0.1:6379/0
export WEBHOOK_INTERNAL_TOKEN=$(openssl rand -hex 32)
uv run uvicorn main:app --reload --port 8005
```

Seed a grant, then authorize:

```bash
curl -s -X PUT http://127.0.0.1:8005/internal/grants \
  -H "Authorization: Bearer $WEBHOOK_INTERNAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"grant_id":"grt_1","mandate_id":"mnd_1","mandate_version":1,"instrument_token":"ins_1","descriptor":"VOLT SUPPLY CO","mcc":"5732","authorized_amount_cents":2999,"currency":"USD","expires_at":"2026-10-11T00:00:00Z"}'

curl -s -X POST http://127.0.0.1:8005/local/authorize \
  -H "Authorization: Bearer $WEBHOOK_INTERNAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"event_id":"evt_1","instrument_token":"ins_1","descriptor":"VOLT SUPPLY CO","mcc":"5732","amount_cents":2999,"currency":"USD"}'
```

## Tests

```bash
uv run python -m unittest discover -s tests -v
# From repo root (rail fixtures):
../.venv/bin/python -m unittest tests.test_decision_cases -v   # if run from services/webhook with path hacks
# Prefer:
cd ../.. && services/webhook/.venv/bin/python -m unittest tests.test_decision_cases -v
```
