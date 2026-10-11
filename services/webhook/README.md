# LEASH payment rail (`services/webhook`)

Labeled rails over one Valkey-backed `authorize()` path:

- **Local payment rail simulator** — `POST /local/authorize` (Bearer `WEBHOOK_INTERNAL_TOKEN`)
- **Lithic sandbox ASA** — `POST /lithic/asa` (public; optional HMAC via `LITHIC_ASA_SECRET`)

Neither route mints grants. Missing/invalid grants decline (fail closed).

## Run locally

```bash
docker run --rm -p 6379:6379 valkey/valkey:8-alpine

export VALKEY_URL=redis://127.0.0.1:6379/0
export WEBHOOK_INTERNAL_TOKEN=$(openssl rand -hex 32)
export API_URL=http://127.0.0.1:8000   # for post-decision activity notify
# optional: LITHIC_API_KEY / LITHIC_ASA_SECRET
uv run uvicorn main:app --reload --port 8005
```

## Public ASA URL (LKE)

After web rewrite deploy:

```text
http://<NODEBALANCER_IP>/rail/lithic/asa
```

Enroll (sandbox):

```bash
curl -s -X POST http://127.0.0.1:8005/internal/lithic/asa/enroll \
  -H "Authorization: Bearer $WEBHOOK_INTERNAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url":"http://<NODEBALANCER_IP>/rail/lithic/asa"}'
```

Simulate an auth (routes through enrolled ASA):

```bash
curl -s -X POST http://127.0.0.1:8005/internal/lithic/simulate \
  -H "Authorization: Bearer $WEBHOOK_INTERNAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"card_token":"<token>","amount_cents":2999,"descriptor":"VOLT SUPPLY CO","mcc":"5732"}'
```

## Grant seeding (Rishi / operators)

```bash
curl -s -X PUT http://127.0.0.1:8005/internal/grants \
  -H "Authorization: Bearer $WEBHOOK_INTERNAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"grant_id":"grt_1","mandate_id":"mnd_1","mandate_version":1,"instrument_token":"ins_1","descriptor":"VOLT SUPPLY CO","mcc":"5732","authorized_amount_cents":2999,"currency":"USD","expires_at":"2026-10-11T00:00:00Z","user_id":"usr_demo"}'
```

## Tests

```bash
uv run python -m unittest discover -s tests -v
```
