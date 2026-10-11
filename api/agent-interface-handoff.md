# Rishi / Aditya / Cameron interface alignment

Inspected `origin/main` at `1818a43` and `origin/aditya-mcp` at `2e6f940` on
October 10. Main contains Cameron's PRs #2/#3/#5 and Aditya's PR #4. Rishi incorporated
this main, resolving the AGENTS.md conflict while preserving both lanes. The refreshed `aditya-2e6f940-wire.json` capture
contains three actual MCP bodies, run registration, seven guardian outputs, and
five hook/source events generated with fixture inputs. HTTP, S3 and models are
substituted; this is not live inference or real Object Storage. All 52 API contract
tests pass. `capture_peer_wire.py` makes the refresh reproducible.

Rishi authorized PR #1 as the accepted R01 baseline after compatibility review.
Cameron's PR #5 adds JWT auth and a PostgreSQL users table; its code is preserved.
Leash purchase routes, store, webhook, Valkey, shared packaging and Compose remain
pending. The earlier public health-only deployment check is historical; this merge
does not deploy or prove an authenticated payment flow.

## Rishi's accepted wire contracts

### Payments

`POST /payments` uses `PaymentProposal`, matching MCP serialization:

```json
{
  "mandate_id":"mnd_demo",
  "checkout_id":"checkout_demo",
  "proposal":{
    "merchant_name":"Volt Supply Co.",
    "items":[{"name":"USB-C charger","sku":"CHG-65W","quantity":1,"unit_cents":2999}],
    "total_cents":2999
  },
  "run_id":"run_demo"
}
```

SKU, merchant name, proposal, and input run ID can be absent/null where the MCP
allows them. This supplies no authority: R04 must resolve an authenticated owned
run/purchase context before storing or issuing a grant, or return a plain error.
The proposal is comparison evidence. Even contradictory claimed totals are retained;
the backend verifies actual canonical checkout facts through Cameron's configured
protected connection. Never invent trusted descriptor/MCC/category from these claims.

Responses have top-level `id` and `status`, as Aditya's shopper/polling expects:

```json
{"id":"pay_demo","status":"blocked","reasons":["Subscriptions are not authorized"]}
```

Primary statuses: `approved`, `pending_user`, `blocked`, `denied`; polling can also
show `pending_guardian`, `expired`, `used`. `approved` means an issued verified
grant, not a completed charge. `PaymentResponse` requires grant/verification refs
for approval; optional `payment_result` reflects only an actual rail outcome.
R04 handles once-only card delivery separately from stored/event records. API errors
use FastAPI `{"detail":"plain string"}`; future validation handlers must use that
format too. The route implementation is pending, not supplied by R01.

### Mandate drafts

`MandateProposal` matches the existing MCP's `description`, `category`, `max_cents`,
`location`, optional/null `valid_until`. R02 supplies a bounded expiry when omitted
and displays it for explicit human confirmation. Confirmed Mandate always requires
expiry; omitted expiry never becomes unlimited permission.

Canonical semantic names now match the guardian's actual lookups:

```json
{
  "description":"Buy a USB-C laptop charger for under $40. No subscriptions.",
  "category":"laptop_charger",
  "max_cents":3999,
  "valid_until":"2026-10-11T12:00:00Z",
  "product_constraints":[{"name":"connector","operator":"equals","value":"USB-C"}],
  "max_quantity":1,
  "maximum_purchases":1,
  "allow_subscription":false,
  "allow_recurring":false
}
```

The first R01 spellings `maximum_quantity`, `allow_subscriptions`, and
`allow_recurring_payments` remain input aliases; output/signing/hash payloads use
`max_quantity`, `allow_subscription`, `allow_recurring` only. Supplying conflicting
old/new spellings fails. `maximum_purchases` explicitly means the authorized cap;
the draft YAML's `purchase_count` needs fixture mapping, not a mutable counter in
signed authority. `description` preserves the original text; Aditya already reads
it as a fallback to `original_instruction`. Human confirmation/signature/ownership
fields remain forbidden in agent draft input. Explicit USB-C constraints cannot be
silently dropped; defaults forbid subscriptions/recurrence and permit one unit/purchase.

Aditya's current MCP now forwards these semantic fields and uses strict integer
cents/quantity and strict boolean flags. Strings are compared case-insensitively
by his advisory guardian; numeric minimum/maximum currently use nonnegative integers.
The R03 verifier must execute agreed attribute checks independently: a wrong
connector blocks, an absent/unknown connector cannot pass. Shared schema validation
is not this verifier. Its `ProductConstraint` also rejects malformed numeric/string
operator values; peer validators should be replaced with it after packaging/freeze.

### Guardian evaluation and findings

Aditya's current route accepts `{mandate, checkout?, proposal?, provenance:[], trace:[]}`;
`cart` is a legacy alias for `proposal`. `GuardianEvaluationRequest` follows this.
The API sends its trusted snapshot and current confirmed mandate after hard checks,
not the shopper's creation response as proof. Source/trace lists contain flat payloads
with their `type` restored from the audit envelope; do not send nested AuditEvent
envelopes directly to code that expects top-level source/trace fields.

The actual guardian v2 response is advisory and includes `review`, unlike the message:

```json
{
  "recommendation":"review",
  "authority":"advisory",
  "reasons":["Investigation model unavailable; a person should review this attempt."],
  "explanation":null,
  "checks":[],
  "suspicious_sources":[],
  "checkout_id":"checkout_demo",
  "model":{"status":"unavailable","error":"RuntimeError","provider":"akamai-inference","model_id":"hackathon-chat"}
}
```

`Verdict` / `GuardianFindings` accepts `block | review | no_findings`, check
severity/evidence, source phrases/event IDs, explanation, checkout ID, and typed
model status/error/provider/citations/constraints. Model can also be null. Skipping
the model currently returns `{"status":"skipped"}`. There is no approval value.
`review` is compatible and cannot bypass evidence or failed deterministic checks.
`no_findings` also supplies no permission; verification and grant gates stay separate.

### Provenance and traces

Keep `POST /provenance` with the agent bearer. Both input kinds share `event_id`,
`run_id`, `agent_id`, `agent_mode: live | scripted`, and `timestamp`:

- `agent.tool.before` / `agent.tool.after`: tool name/use ID, sanitized JSON
  arguments, source reference, reported trust classification, proposed action,
  optional result summary/policy decision/duration, tool `status` and `error`.
- `provenance.source`: URL, SHA-256, tool-use ID, HTTP status, `fetched_at`, reported
  trust, hidden detection/reasons/phrases, hidden suspicious phrases, excerpt, snapshot.

Reported trust labels are preserved (`leash_api`, `merchant_response_via_agent`,
`untrusted_web_content`, `untrusted_tool_output`). They remain claims, not backend
authority. `agent_report_event()` requires authenticated user/agent and registered
run/mode context, preserves the event ID and live/scripted label, re-redacts, and marks
reports non-authoritative. Only backend payment events alter transaction state.
R06 deduplicates by authenticated subject/origin plus ID, detects altered duplicates,
and persists before acknowledgment. Agent IDs cannot poison backend-event deduplication.

Snapshot metadata matches the pushed code: `{storage:"none",reason}` or
`{storage:"object_storage",bucket,key}`. No HTML/body fields are accepted.
Object references must match the configured bucket and `runs/{run_id}/{sha256}.html`;
foreign run/bucket references fail. Unavailable snapshots retain their honest label.
Optional `stored_sha256` supports separate integrity for a redacted stored snapshot;
the original source SHA-256 remains separate evidence.

## Run registration and intake acknowledgment

R01 accepts Aditya's proposed `POST /agent-runs` with the agent bearer:

```json
{"id":"run_demo","mandate_id":"mnd_demo","agent_mode":"scripted","model":"scripted-shopper","provider":"fixture"}
```

`AgentRunRegistration` forbids agent-chosen user/agent identity, version/hash, and
status. R02 resolves the authenticated owner/current confirmed mandate and persists
`AgentRun` with server-derived identity, version/hash and creation time. Reply 2xx
only after commit, echoing the exact ID and mode; refuse unauthorized/invalid runs
with `{"detail":"plain string"}`. Registration precedes tools and provenance.
Model/provider remain reported metadata; mode must match the API's authorized run
dispatch. A client cannot relabel a scripted run by registering it again.

R06 follows the outbox's status handling:

- 2xx: durable SQL commit completed (not merely queued).
- 409: the same authenticated subject/origin/event ID and normalized content
  were already committed. Only an identical retry gets this result.
- Altered duplicate: 422, permanently rejected; preserve the original and record
  the collision. Do not return 409, which the outbox treats as safely delivered.
- 400/401/403/404/413/422: permanently rejected; plain-string detail.
- Outages: 5xx; transient throttling/timeouts: 429/408, retried.

These are contract choices for later route work, not implemented API endpoints.

## Owner actions before integration

| Owner | Concrete remaining action |
|---|---|
| Rishi | R02 implements registered ownership/mandate/mode persistence; R06 intake acknowledgment remains pending; guardian calls now require `AGENTS_SERVICE_TOKEN`. Aditya's registration and retry/spooling code is present. |
| Aditya | Fix the restart test's scheduling assumption; wait for a delivery attempt and synchronize old worker shutdown instead of requiring an attempt within 0.3 seconds. Consider joining on `OutboxSink.stop()`. Require the mode echo rather than accepting null in registration responses. |
| Aditya | After C01, consume the accepted shared validators, including numeric/string constraint validation. Store MCP and the live-first demo are merged; merge the latest separate live/scripted credential changes and validate against R02. |
| Cameron | Mount persistent storage at `/app/trace-spool`. `k8s/agents.yaml` has no volumes/mounts, so image-local spooling does not survive pod replacement. Supply exact OBJ names, configured STORE_URL/token, service tokens and documented MCP hosts. |
| Cameron + Rishi | C01 installable shared package/runtime; R02 API image includes all API modules, shared sources and migrations using root context; Cameron must update the current `api/`-context deployment command before deploying it. Rishi owns the API Dockerfile; Cameron owns the matching deploy build context. Change these together before product API deployment. |
| Cameron + Rishi | Agree authenticated canonical retrieval, session/owner assignment, revision/expiry, protected grant/instrument binding and atomic Valkey protocol. CheckoutSnapshot binds session ID; product billing interval is preserved/hash-bound. |

Aditya has already replaced the hotel YAML with charger/subscription cases and
added scripted/live e2e scaffolding. Its independent expectations remain intact;
draft field mappings and signed/owned record setup still need integration. Fixture
tests and canned wiring servers do not prove a deployed secure payment flow.

Adi's store routes are acceptable proposals: `POST /api/checkouts {sku,quantity}`
and `POST /api/checkouts/{id}/complete {payment_id,card?}`. His `_store_post` currently
now forwards `STORE_API_TOKEN` only to its configured checkout API, never browse.
That static bearer is interim authentication, not scoped session ownership. Cameron
and Aditya must agree a scoped caller/session credential and forward it without
weakening the protected charge boundary. Rishi assigns the
payment/purchase-attempt ID, adds the authorized context to its persisted snapshot,
and registers the exact frozen checkout/grant/instrument association. Completion
loads that protected binding and rejects another session or checkout; supplied card
data/payment ID never replaces it. Canonical retrieval is a separate authenticated
server interface. Actual authorization is not settlement, regardless of a fixture's
`paid` wording.

Use Aditya's draft catalog: `CHG-65W` / `laptop_charger` and `SUB-CARE-MO` /
`protection_plan`, both 2999 cents at `mer_volt_supply` / `VOLT SUPPLY CO` / MCC
`"5732"` / USD, pending Cameron's catalog implementation. Injection changes listing
text, not canonical facts. No edits were made in Aditya's or Cameron's lanes.

## Historical R01 verification and current integration

The following counts describe the earlier R01 review, not the current rerun.
The R02 merge refresh captures `9edadab`'s serializers/guardian/source hooks in
`api/tests/fixtures/aditya-9edadab-wire.json`; HTTP, S3 and model calls are substituted.
Contract tests use that fixture; the older capture remains historical evidence.

- R01: 52 tests passed, refreshed peer captures passed; selected correctness lint
  (E4/E7/E9/F), documentation links/fences and whitespace checked separately.
- MCP: 33 tests passed with its committed lockfile.
- Agents: 126 passed, one failed, two live inference tests deselected with its
  committed lockfile. Real MCP subprocess wiring against stub API/store passed;
  those canned decisions do not prove payment enforcement.
- The failed restart test also failed in isolation. First mocked HTTP attempt
  measured 0.563 seconds versus its 0.3-second flush window. A diagnostic waiting
  for the attempt and joining the old worker recovered both pending events.
  This explains the historical local failure; Aditya's merged worker-stop and restart-test fixes are now present. This earlier result is not a rerun of those fixes.
- Six deployed-stack tests skipped because live E2E was not enabled; no real
  inference, merchant/rail enforcement, ASA or settlement was exercised.
- Kubernetes YAML/selectors/service and probe ports/exposure match; deployment
  scripts pass Bash syntax. Docker daemon is unavailable and Compose absent, so
  fresh image builds or complete boot were not validated here.
- Web lint and Next.js production build passed with the merged configuration.
  This validates the frontend build, not an authenticated purchase flow.

The MCP decision is resolved: Leash financial tools use `services/mcp-leash/`
and shopping tools use `services/mcp-store/`, each at `/mcp` on its own deployment.
Both are owned by Aditya; Cameron owns the merchant and deployment. Store MCP
restricts browsing, handles inspection/redacted snapshots, and returns source
evidence to hooks. The API independently retrieves trusted checkout facts.
The demo is live-first; no real live injection evidence is claimed here.

### R01 merge decision — October 10

Rishi authorized the initial compatible R01 baseline; separate approval messages
from all three teammates are not claimed. Future shared-contract changes retain
the dedicated PR/all-three coordination rule. R02 preserves Cameron's UUID auth
and implements the explicit LEASH identity mapping. The R01 integration also
preserved the cancellation-aware no-token auth restoration in `web/src/lib/auth.tsx`.

## R02 API implementation update

The mandate and `/agent-runs` contracts above are implemented in R02.
[The R02 handoff](r02-handoff.md) is the current route/provisioning guide: assigned
agent bearer, server-derived owner/version/hash, one operator-selected live/scripted
mode, durable commit before 201 and identical retry echo. Mandates now have proposal,
read/list, exact human approval, replacement/revocation and owner history routes.
Cameron must update the API build context and provision the intended human/agent
binding. R06 `/provenance` remains pending; a successful registration does not yet
mean traces or payment requests can be accepted. No teammate-owned code was edited.
