# Current alignment fixes and remaining handoffs

This implementation follow-up on main integrates Cameron's activity/local rail
(`674ef75`) and ASA adapter (`a9e8cba`), preserves Rishi's fixes (`09ee628`) and
adds the tested integration corrections described below. Rishi authorized these
narrow cross-lane fixes; ownership and frozen R01 models/events are unchanged.
Source changes have not been deployed and no shared database/provider was changed.

## What now works locally

- Signup creates an identity and audit event in one SQL transaction. It makes no
  provider calls, grants no spending authority and does not require Lithic. Old
  optional `spend_limit_cents` remains compatible but cannot authorize spending.
- `checkout_verifier.verify_checkout()` enforces the 15 frozen checks, including
  full 3999-cent total, category/attributes, quantity, recurrence, merchant,
  shipping, current confirmation and authenticated evidence predicates. It is
  pure policy; trusted retrieval and product payment routes are still absent.
- `POST /provenance` requires the bound agent and registered run/mode. It stores
  sanitized frozen before/after/source inputs before returning 201. Same original
  event returns 409; altered collision/invalid fields 422; unknown/foreign run 404;
  oversized input 413; database outage 503. Maximum input is 128 KiB. Late evidence
  may arrive after revocation; it cannot create authority. Existing rejected
  agent spool records are not automatically reingested or relabeled.
- Human `GET /activity` and `/activity/stream` replay persisted owned events;
  `after` or `Last-Event-ID` resumes without starting work. SQL event append is
  commit-ordered. The Next `/backend/activity/stream` proxy forwards the body
  directly, with Bearer in headers. Session expiry is rechecked while streaming.
- Strict local rail uses immutable complete grants, exact checkout/hash/binding,
  amount/currency/merchant/MCC, server-clock expiry, current authority and a
  one-success-per-mandate-version cap. Lua commits consume, original response and
  rail stream together. Duplicates retain their original decision even after stop;
  altered duplicates cannot become new spending. Consumed grants cannot be reseeded.
- Rail events survive API delivery outages in `leash:rail-events`. A fenced worker
  retries event-only API ingestion outside the hot path. Stable duplicates return
  409. Validation-rejected/ownerless legacy entries retain quarantine markers and
  original stream data. No automatic TTL removes replay tombstones or this stream;
  retention/monitoring remain an operations task. This is a single Valkey instance
  protocol, not a tested Redis Cluster deployment.
- Human stop commits SQL authority revocation, cancellation and owned card PAUSE
  intent before external calls. Atomic rail stop invalidates unused grants.
  Provider control is confirmed only for the right card and observed PAUSED/CLOSED;
  timeout stays unknown and retries the same non-spending operation. Prior
  authorization is not reversed. No live Lithic call was made by these tests.

## Callable control interfaces

Human Bearer:

```http
POST /killswitch
Content-Type: application/json

{"on":true}
```

Response has `status: stopped | pending_enforcement`, `mandates_revoked`,
`rail: {status: enforced | pending, unused_grants_revoked?}`,
`provider_card_controls: {status: not_required | enforced | pending, total, confirmed}`,
`run_cancellation: requested` and `previous_authorizations_reversed: false`.
`GET /killswitch` returns `on`, `rail_enforced`, `provider_controls_enforced`.
Repeated stops retry pending enforcement; they do not resume old authority.

Bound agent Bearer:

```http
GET /agent-runs/run_EXAMPLE/control
```

Response: `run_id`, `cancel_requested`, `authority_current`. A foreign run is 404.
**Aditya must poll before side effects and Graph recovery; workers do not do this
yet.** The durable requested cancellation is not proof the model/thread has stopped.

Trusted API control Bearer (`WEBHOOK_INTERNAL_TOKEN`), private rail:

- `PUT /internal/grants`: the **complete frozen AuthorizationGrant**, not the old
  descriptor/amount-only payload. Only ISSUED, already-issued, unexpired grants with
  lifetime <=1800 seconds install. Source predicates must be established by the
  real API verification flow before production use; test seeding is a fixture.
- `POST /internal/killswitch`: `{"user_id":"usr_EXAMPLE","on":true}`.
- `POST /internal/lithic/card-state`: `{"card_token":"...","state":"PAUSED"}`;
  PAUSED/CLOSED only, never OPEN. Provider failure/uncertain acknowledgment is 502.
- `POST /internal/lithic/asa/enroll`: exact configured HTTPS
  `LITHIC_ASA_RESPONDER_URL`. Unknown result requires provider configuration
  inspection before retry. Enrollment does not prove checkout correlation.
- `POST /internal/lithic/simulate`: 503 until durable payment-operation integrity
  exists. The internal wrapper remains available for Cameron's operation handoff.

Merchant charge Bearer (`WEBHOOK_CHARGE_TOKEN`), private rail:

```json
{
  "event_id":"provider_event_EXAMPLE",
  "request_type":"AUTHORIZATION",
  "instrument_token":"ins_EXAMPLE",
  "descriptor":"VOLT SUPPLY CO",
  "mcc":"5732",
  "amount_cents":2999,
  "currency":"USD",
  "checkout_id":"chk_EXAMPLE",
  "checkout_hash":"<64 hexadecimal characters>",
  "merchant_binding_id":"binding_EXAMPLE"
}
```

Send to `POST /local/authorize`. No caller clock, float/bool money or numeric MCC.
These fields must come from Cameron's protected immutable merchant binding; an
agent-supplied copy is not proof. A state-store failure is 503, never an approval.
Use the same event identity for uncertain delivery; do not purchase again.

Rail event-only Bearer (`RAIL_EVENT_TOKEN`), private API:

`POST /internal/activity` accepts only `authorization.decided`, a stable top-level
`event_id`, existing consistent owner and strict decision data. Data includes
`event_id`, `result`, `reason`, `rail`, `decision_source`, `provider`, integer
`amount_cents`, `currency: USD`, descriptor, string MCC and UTC `decided_at`.
201 means stored, 409 means the original is stored, altered collision is 422.
The grant-control credential cannot publish here; events cannot confirm mandates.
Use the durable relay; do not add a second best-effort authoritative event path.

## Configuration and deployment (Cameron)

Keep these credentials distinct, at least 32 characters, server-side:

| Setting | Receivers / purpose |
|---|---|
| WEBHOOK_INTERNAL_TOKEN | API + rail; grant/stop/card controls |
| WEBHOOK_CHARGE_TOKEN | Protected merchant + rail; local charge only |
| RAIL_EVENT_TOKEN | Rail + API; authorization history publisher only |
| LITHIC_ASA_SECRET | Rail only; mandatory provider HMAC |
| LITHIC_API_KEY / LITHIC_ENVIRONMENT | Trusted API legacy reads + rail provider helpers; sandbox only |
| LITHIC_ASA_RESPONDER_URL | Rail; explicitly configured HTTPS enrollment target |
| OBJ_BUCKET | API validates snapshot scope; Store MCP uses OBJ_* storage credentials |

Explicit Secret allowlists replace broad `envFrom`. Agent/MCP pods receive no
database/JWT/signing/Lithic authority keys. API and webhook images build from root
with their own Dockerfiles; webhook copies ASA and relay modules plus shared.
Valkey declares AOF `appendfsync always`, 5 Gi PVC and Recreate rollout. Financial
NetworkPolicy allows only rail→Valkey and trusted API/store/web→rail. Verify CNI
support, actual mounts, TLS, images and Secret scopes; YAML is not deployed proof.

Public MCP proxies default off. Only exact `/rail/lithic/asa` proxies to the rail;
there is no wildcard exposing internal routes. The web also returns 404 for `/backend/internal/*`; publishers must use the private API origin. ASA rejects missing/invalid key,
unsigned headers, unsupported currencies/amount ambiguity and oversized bodies.
**ASA purchase readiness is false:** provider metadata cannot prove the exact
checkout/SKU; all approvals are blocked until trusted correlation exists. Actual
enrollment, signed sandbox requests and live provider card controls remain unverified.
See [Lithic HMAC](https://docs.lithic.com/docs/events-api) and
[ASA request schema](https://docs.lithic.com/reference/cardauthorizationapprovalrequestwebhook).

Migrations 0005/0006 add workflow stop and durable card controls. Startup uses
checksummed migrations. Scripts and migrations now retain LF across OSes; no
historical SQL logical content was changed. If an existing Windows database used
CRLF checksums, inspect/resolve that migration-history mismatch before operating it;
never silently alter applied checksums. No shared migration was run in this task.

## Exact next owner actions

1. **Cameron / C02:** supply authenticated canonical checkout GET/freeze/bind/charge,
   same-merchant/2999/USD products and a safe alternative. Enforce exact checkout
   association when actually charging, mandatory store auth and owner/session scope.
   The merged simulated store now has mandatory authenticated create/read and same-price canonical SKU/recurrence facts, but checkouts are process memory. Completion is disabled (503): no ownership/freeze/binding/payment operation exists. Preserve aliases CHG-65W/SUB-CARE-MO; no provider keys belong in the store pod.
2. **Rishi / R03–R04/R11:** connect trusted retrieval to existing policy; persist
   attempts/verification/payment operations before side effects, protected binding
   activation, once-only delivery and reconciliation. Connect individual mandate
   replace/revoke to rail state before issuing real grants. Do not infer trusted
   evidence from a valid model or accept agent authentication predicates.
3. **Aditya / A11–A13 + Rishi/R12:** real bounded Strands Graph, typed backend
   decisions, fresh recovery context/exclusions under original mandate, cooperative
   control polling, leases/fencing and complete genuine lifecycle events. Recovery
   stops on unknown payment/hard decline/authorization. Agree additive contracts
   through the frozen-contract process; live Akamai/injection remains unproven.
4. **Rishi / R07–R10:** human purchase confirmation and six product views from real
   persisted states; current profile/stop/feed is not Mission Control or Attack Lab.
5. **Cameron + all:** deploy/verify existing LKE, Valkey restart/AOF and policy
   enforcement, stable auth/TLS/short-lived credentials, live acceptance/rehearsal.
   Choose the labeled local simulator until Lithic correlation/configuration/proof
   is complete. No complete three-minute demo is claimed by this handoff.

## Test evidence and limits

- API: 107 tests pass with real disposable PostgreSQL (25 SQL tests), including
  the opt-in stack smoke described below.
- Stack smoke: real local API/Redis rail/store/Next standalone, seeded backend fixture
  grant, human stop acknowledgment, real rail→API delivery and persisted SSE through
  Next. Simulated storefront/private-auth/blocked-charge routing is tested; no model/provider call/full purchase demo.
- Rail: **45 tests pass**, including 14 real Redis tests; replay/concurrency/server-clock expiry,
  stop races, two-grant purchase scope, wrong stream type, delivery outage and crash
  replay. Redis 6 test engine, not live deployed Valkey8.
- Agents: 131 passed, 2 live inference tests deselected; actual SDK subprocess MCP
  tests use substitute API/store/model. Both MCP suites previously passed (33/40).
- Store: **15 tests pass** for canonical products, poison toggle, mandatory auth, validation redaction and disabled unverified charge. Source checkout ownership/durable freeze and protected completion remain pending.
- Web lint/build pass; six live E2E scenarios are skipped. No browser interaction,
  Docker image build, cluster apply, provider enrollment or live sandbox proof.

See [the audit](../docs/LEASH_ALIGNMENT_AUDIT.md) for the complete 100-requirement
matrix, security gaps, exact final counts and original baseline evidence.
