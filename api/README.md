# LEASH backend and R01 contract handoff

The backend still exposes only `GET /health`. R01 adds shared Python contracts,
canonical hashing, and sanitized event publishing; it does not implement purchase
routes, signing, database writes, a verifier, or a payment rail.

Run the contract suite from the repository root using Python 3.12+ with Pydantic v2:

```powershell
.\api\.venv\Scripts\python.exe -m unittest discover -s api/tests -v
```

No Redis server, provider credentials, inference, or pytest installation is needed.
The async tests use the normal Windows event loop, which needs local loopback.
The existing API runs from `api/` with `python -m uvicorn main:app --port 8000`.
Compose boot remains pending Cameron's configuration.

## Imports and ownership

Rishi owns `shared/leash_shared/models.py`, `events.py`, and these tests.
Cameron owns shared package metadata, its package marker, and runtime installation.
Until C01 lands, put the repository's `shared/` directory on `PYTHONPATH`; the tests
do this themselves. All services import the same source, without copying models:

```python
from leash_shared.models import Mandate, CheckoutSnapshot, cart_hash
from leash_shared.events import AuditEvent, publish
```

These are the initial R01 review candidate on `rishi/r01-shared-contracts`.
Cameron and Aditya review the concrete fields before all three freeze them. Future
frozen-contract changes follow AGENTS.md's dedicated PR rule.

## Records and authority boundaries

| Records | Purpose |
|---|---|
| `PurchaseMandate` / alias `Mandate` | Original instruction, semantic constraints, quantity/purchase limits, merchant identities, validity, immutable version/hash, confirmation/signature association |
| `MandateProposal` | Agent-facing draft, including semantic flags/constraints; no ownership, status, confirmation, or signature fields |
| `AgentPurchaseProposal`, `PaymentProposal` | Adi's `proposal` comparison claims plus checkout/run/mandate references; never independent checkout proof |
| `CartProposal`, `Cart` | Earlier structured merchant/cart evidence and unchanged legacy hash helper; not the new payment input |
| `CanonicalProduct`, `ProductListing`, `CheckoutSnapshot` | Separate canonical catalog, untrusted listing, and complete itemized checkout facts/source |
| `CheckoutVerification` | Deterministic check results bound to user, purchase attempt, mandate version/hash, and checkout ID/hash |
| `AuthorizationGrant`, `PreApproval` | Exact verified amount/currency, instrument, merchant binding, expiry, and grant identity/status |
| `AuthorizationAttempt`, `PaymentDecision`, `AuthorizationDecision` | Normalized request and actual outcome, rail, reason, latency, and evidence references |
| `AgentRun`, `AgentTraceEvent`, `ProvenanceEvent`, `SecurityIncident` | Execution and source evidence linked to authority and security decisions |
| `Verdict` / alias `GuardianFindings` | Advisory `block`, `review`, or `no_findings`; checks/evidence and structured nullable model metadata; never approves |
| `PaymentResponse` | Top-level `id` and `status`; grant approval and actual authorization remain separate |

Amounts and quantities use strict integers, flags use strict booleans, MCCs are
four-digit strings, and timestamps must be timezone-aware and normalize to UTC.
Only USD and the labeled local/sandbox rails are supported. Unknown fields fail
validation. Authority models are frozen and nested collections use tuples.
Service code must validate at trust boundaries; `model_construct()` and
`model_copy(update=...)` bypass Pydantic validation and must not admit external input.

`PaymentProposal` requires `mandate_id` and `checkout_id`; input `run_id` is nullable
to match MCP, but R04 must resolve an authenticated owned run context before issuing.
Its optional
`proposal` contains `merchant_name`, `items` (`name`, optional `sku`, `quantity`,
`unit_cents`), and `total_cents`, matching Adi's serializer; merchant name is nullable.
A contradictory proposed
total is retained for comparison; the backend obtains and checks the actual total
independently. The earlier Cart/CartProposal and four-field cart hash are retained
for legacy evidence, never reconstructed by inventing trusted descriptor/MCC facts.
The exact examples and remaining owner changes are in the
[agent interface alignment handoff](agent-interface-handoff.md).

`CheckoutSnapshot` requires explicit SKU, nullable category, quantity, unit price,
subscription/recurring flags, subtotal/tax/shipping/total, revision, user/attempt,
expiry, source identity and session ID; billing interval is retained if supplied.
Category `null` represents uncertainty; it must never
pass the category check. Parsing `source.method="server_fetch"` does not authenticate
a source. R03 must retrieve it through Cameron's configured protected interface.

A `VERIFIED` record requires unique, passing checks for: `mandate_confirmed`,
`mandate_valid`, `checkout_authenticated`, `checkout_integrity`, `checkout_valid`,
`category`, `product_constraints`, `quantity`, `purchase_scope`, `merchant`, `amount`,
`currency`, `subscription`, `recurring`, and `shipping`. Block/review needs reasons.
Extra checks are allowed. R03 must actually execute these checks against evidence;
an agent-supplied record is never trusted merely because its shape validates.

`PreApproval.from_grant()` creates the Valkey record. It retains the earlier names
but requires a nested `grant`; duplicate identities/amount/expiry must exactly match.
Its optional `cart_hash` remains a proposal hash. Authorization uses the nested
grant's verified checkout hash and exact amount, not the legacy budget-ceiling rule.
Grants require a protected merchant binding established before issuance and cannot
outlive the mandate or checkout. C03/C04 still enforce current authority and atomic
single use; schema validation alone cannot perform those operations.

## Canonical JSON and hashes

Use the shared helpers only. Encoding sorts object keys, removes whitespace,
preserves array order, escapes Unicode using JSON's default ASCII encoding,
normalizes datetimes to UTC ISO 8601 with `Z`, and rejects nonfinite numbers.
SHA-256 hashes the resulting UTF-8 bytes and returns lowercase hexadecimal.

| Helper | Version-1 payload |
|---|---|
| `mandate_payload()` / `mandate_hash()` | `schema_version: 1` and every mandate field except `status`, `approved_at`, `signature`, and `canonical_payload_hash`; defaults and nulls included |
| `cart_payload()` / `cart_hash()` | Exactly `mandate_id`, `merchant`, `items`, `total_cents`, retaining the earlier agent definition; ID/hash excluded, supplied currency validated as USD |
| `checkout_payload()` / `checkout_hash()` | `schema_version: 1` and every checkout field except `checkout_hash` and `source.retrieved_at`; source identity/URL/method, expiry, revision, ownership, item facts, and fulfillment remain bound |

An unchanged checkout refetch changes acquisition time but not its purchase hash.
Reordering items/constraints/attributes changes the hash. Services retain canonical
order and never sort arrays independently. Hash records auto-fill missing hashes
and reject a supplied hash inconsistent with content. Changing lifecycle status
does not rewrite the immutable human-approved payload.

Independent cart test vector (MCC is a string):

```json
{"items":[{"name":"USB-C charger","quantity":1,"unit_cents":2999}],"mandate_id":"mnd_demo","merchant":{"descriptor":"LEASH DEMO STORE","mcc":"5732","name":"Demo Store","url":"https://store.test"},"total_cents":2999}
```

SHA-256: `cfaa7470b730c2b4e76b5a3f80552d117b157c49a96819c020a642c5fda4557f`.
A hash proves content consistency, not source authenticity or human consent.
R02 implements authenticated confirmation and real Ed25519 signing/verification.
R01 validates signature format only; the test signature is an explicitly synthetic
64-byte fixture and provides no cryptographic proof.

## Event stream contract

`AuditEvent` / alias `Event` contains `event_id`, `type`, `at`, `user_id`, and `data`.
The existing event names remain, with checkout/grant/run/tool/incident lifecycle
types added. Send typed records through their JSON representation or as nested
models; callers allowlist data and summarize untrusted tool text before publishing.
`parse_provenance()` accepts `agent.tool.before`, `agent.tool.after`, and
`provenance.source` bodies. `agent_report_event()` requires authenticated user,
agent, and registered run/mode context, preserves the original event ID and
live/scripted label, redacts data,
and marks claims as non-authoritative. It never promotes a reported policy result
or trust label into a payment decision. Source snapshot metadata matches the pushed
code; object references require configured bucket/run/hash validation. Inline snapshot
bodies never enter the stream. Current guardian input/output and captured compatibility
evidence are documented in the linked handoff; `review` and structured model metadata
are supported. Canonical mandate names now match the actual guardian lookups
(`max_quantity`, `allow_subscription`, `allow_recurring`); first-draft spellings remain
input aliases, with only canonical names in signed/hash payloads.

```python
event = AuditEvent(
  type="checkout.verified", user_id=verification.user_id,
  data={"verification": verification.model_dump(mode="json")},
)
entry_id = await publish(valkey_client, event)
```

The shared wire format is `XADD leash:events * event <canonical envelope JSON>`.
`publish(client, event)` accepts an async client with `xadd()` and propagates write
failure. Consumers decode the `event` field and deduplicate by `event_id`.
`event_fields(event)` returns the same fields for Cameron's atomic authorization
transaction/script: combine consumption, cached decision, and event insertion in
one commit before responding. Standalone `publish()` does not provide that atomicity.

Known card/credential keys, typed sensitive name/value arguments, bearer strings,
and standalone PAN-like numbers are redacted recursively, including again at the
write boundary. Instrument tokens, last four, and hashes remain usable. Arbitrary
unlabeled secrets cannot be detected reliably: raw provider responses, card details,
tool arguments/results, and untrusted page bodies must never be logged or persisted
directly. Trace/source records also require sanitization at their service boundary.

## Next owner handoffs

- **Rishi / R02:** persisted immutable mandate versions, authenticated human
  confirmation, real signing/verification, and permission tests; R03 uses these
  contracts for independent checkout verification.
- **Cameron / C01-C04:** installable shared package/runtime, canonical merchant
  source and protected binding, pure authorization rules, atomic Valkey protocol.
- **Aditya / A01-A06:** consume these exact models/hash helpers/event fields; add
  explicit mandate constraints, authenticated internal run/guardian routes, new
  integrate his updated policy fixtures and trace/source envelopes. Payment, trace,
  and guardian vocabulary follows his pushed code; inspect the exact handoff for
  remaining owner actions.

R01 tests prove contract validation/hashing/event behavior. They do not claim live
Strands, merchant, Lithic, database, concurrent consumption, or end-to-end acceptance.
