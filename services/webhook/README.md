# LEASH local rail and signed ASA adapter

`POST /local/authorize` runs real deterministic policy and atomic Valkey consume,
original-decision caching and event append. It requires the distinct merchant
`WEBHOOK_CHARGE_TOKEN` and exact checkout/hash/binding fields. It never creates
independent authority. Complete frozen grants are installed privately by the API
with WEBHOOK_INTERNAL_TOKEN through /internal/execution/grants after the API commits verified owned scope. Old PUT/internal/grants returns410; descriptor/amount-only examples are obsolete. Execution lease/epoch/original authorization-event binding is mandatory.

`POST /lithic/asa` requires configured valid HMAC (no unsigned bootstrap mode).
It validates explicit USD/integer amounts and provider identity. **Purchase
readiness is false until trusted checkout correlation exists**, even with a
correct same-merchant/amount card. Unit tests and a configured key are not live
Lithic approval evidence. Source provider helpers reject production/custom URLs.

## Run locally

From this directory, install locked dependencies and start on port 8005:

```bash
uv sync --locked
# Supply VALKEY_URL, distinct WEBHOOK_INTERNAL_TOKEN / WEBHOOK_CHARGE_TOKEN.
# API_URL and distinct RAIL_EVENT_TOKEN enable durable audit delivery.
uv run uvicorn main:app --reload --port 8005
```

Valkey is mandatory by default. `ALLOW_MEMORY_RAIL=1` is an explicit isolated
unit/development adapter, never LKE. Deployment declares persistent AOF/PVC;
actual mounted persistence/CNI/HTTPS and image imports remain unverified.

Human stop calls private `/internal/killswitch` with `{user_id,on:true}`. It
atomically latches that owner and revokes unused grants while preserving original
committed authorizations. Card-state control allows PAUSED/CLOSED only, validates
actual provider card identity/state and reports unknown failures. The API records
owned CLOSED intent before calling it; no transaction reversal is claimed.

## Audit delivery

Authorization commits include immutable sanitized context in `leash:rail-events`.
A fenced background relay posts the original decision to API `/internal/activity`
using **RAIL_EVENT_TOKEN**, outside the critical path. 201/409 acknowledge delivery;
outages/auth configuration errors keep it pending. 422/ownerless legacy records
retain quarantine markers and stream data for operator repair. Replay tombstones
and stream have no automatic expiry: define monitored safe retention before scale.
Memory mode has no durable background relay and is labeled accordingly.

## ASA operations and public boundary

Only exact `https://<TLS_HOST>/rail/lithic/asa` should be public. No wildcard
rail control proxy or public internal API route exists in updated source. Actual
TLS/routing rollout is Cameron's task. Enrollment requires an exact configured
HTTPS `LITHIC_ASA_RESPONDER_URL`, API control bearer and sandbox credentials.
Retrieve the program HMAC secret separately and keep it in the rail Secret.
Never print it. Provider enrollment outcome may be unknown: inspect before retry.
HTTP `/internal/lithic/simulate` returns 503 because arbitrary provider simulation is not an authorized purchase operation; the sandbox wrapper is retained for that handoff.
No provider enrollment, simulation or card pause was run by these tests.

## Interfaces, tests and owner handoffs

See [the current handoff](../../api/full-app-handoff.md) for complete
request fields, credential receivers, HTTP semantics and outstanding merchant /
API / Graph responsibilities. Do not seed arbitrary fixture grants as production
verification or copy grant bindings into an uncorrelated provider request.

```bash
uv run python -m unittest discover -s tests -v
# Real atomic tests are gated to isolated localhost:56379/15 by design:
LEASH_TEST_VALKEY_URL=redis://127.0.0.1:56379/15 uv run python -m unittest discover -s tests -v
```

The 57-test suite passed with the isolated real Redis engine. Without its gate,
real Redis tests skip. ASA signatures/card controls are local unit/HTTP mocks;
actual Valkey8 restart durability and live sandbox integration are still unverified.
The root YAML runner executes 16 pure rail-stage cases only; it is not full merchant
or Graph E2E evidence.

Private `/internal/execution/lease`, `/internal/execution/grants`, `/internal/execution/stop` and original-event readback validate generation/rail epoch. Run Stop/account Kill serialize with atomic consumption; original identical delivery after Stop retains the prior response. State loss rejects old execution instead of rehydrating spending blindly. Actual local Redis tests include stop-between-read-and-commit, lease expiry/reissue refusal, one-success quota and epoch loss; current cloud Valkey8/PVC/HMAC/latency remains unverified.
