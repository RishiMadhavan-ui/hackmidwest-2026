# Rishi / Aditya / Cameron interface alignment

Inspected `origin/aditya-mcp` at `aa5d8d3` on October 10. Rishi's unfrozen R01
candidate conforms to the pushed serializers, hooks, and advisory guardian,
which are newer than the earlier messages. The captured fixture records three
actual MCP bodies, four guardian outputs, and three hook/source events generated
with fixture inputs; no live SDK run, network or model is claimed. These payloads
and security regressions pass in the 48-test API contract suite.

This is on `rishi/r01-shared-contracts` / draft PR #1, pending joint freeze. Rishi's
API still exposes only `/health`. No Cameron remote branch is visible. Aditya's
services exist on his branch; they have not been merged or executed as a full stack
here. Keep implementation, schema compatibility, and live acceptance separate.

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

## Owner actions before integration

| Owner | Concrete remaining action |
|---|---|
| Aditya | Authenticate `/runs`, `GET /runs/{id}`, and `/guardian/evaluate`; bind caller/run/mandate ownership. Cluster-only exposure remains required but does not authenticate callers. |
| Aditya | Extend MCP `propose_mandate` to forward the ready semantic constraints/flags, and consume shared validators so float/bool cents cannot be coerced by duplicate models. |
| Aditya | Redact before Object Storage `put_object`, not just before trace/log sinks. Current hooks pass raw HTML to `upload_snapshot`. Record stored-content hash separately if redaction changes it. |
| Aditya | Fix PAN redaction to preserve SHA-256/opaque IDs. Reproduced: `a` + 16 digits + 47 `b`s becomes `a[CARD ****3456]...`, corrupting a valid source hash before intake. |
| Rishi + Aditya | Register/authorize run ownership and live/scripted mode in the API before dispatching traces; add retry/recovery for the current best-effort HttpSink so API outages/restarts cannot permanently lose required traces. |
| Cameron | C01 shared packaging/runtime and internal network/config. Current snapshot code uses `OBJ_ENDPOINT`, `OBJ_BUCKET`, `OBJ_ACCESS_KEY`, `OBJ_SECRET_KEY`; configure these exact names plus service auth without sharing secret values. |
| Cameron + Rishi | Agree authenticated canonical retrieval, session/owner assignment, revision/expiry, protected grant/instrument binding and atomic Valkey protocol. CheckoutSnapshot binds session ID; product billing interval is preserved/hash-bound. |

Aditya has already replaced the hotel YAML with charger/subscription cases and
added scripted/live e2e scaffolding. Its independent expectations remain intact;
draft field mappings and signed/owned record setup still need integration. Fixture
tests and canned wiring servers do not prove a deployed secure payment flow.

Adi's store routes are acceptable proposals: `POST /api/checkouts {sku,quantity}`
and `POST /api/checkouts/{id}/complete {payment_id,card?}`. His `_store_post` currently
sends no auth header. Cameron and Aditya must agree a scoped caller/session credential
and forward it without weakening the protected charge boundary. Rishi assigns the
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
