# V2 stop controls and SINGLE_USE handoff

This is a source/test handoff on main integrating Cameron's `d773079` onto the V2 batch, not a deployment or full
payment workflow. The V2 master and [137-case coverage index](../docs/LEASH_SECURITY_COVERAGE.md)
are authoritative. R01 models/events have not changed. No provider call, shared
migration, deployment, agent provisioning or teammate message was performed.

## Callable API and actual guarantees

Authenticated human:

- `GET /agent-runs`: up to 100 owned registered runs and their stop projection.
- `POST /agent-runs/{id}/stop`: no body. Owned run only, immutable cancellation
  intent and `run.stop.requested` event in one SQL transaction. Identical retries
  return the same intent/time; concurrent requests create one row/event.
- `GET /agent-runs/{id}/stop`: reconstructs persisted intent after refresh.
- `POST /killswitch {"on":true}`: account-wide SQL revocation/cancellation, durable
  **CLOSED** card intents, then separate atomic rail and provider acknowledgments.
  Top-level `financially_stopped` means those financial controls are acknowledged;
  it does **not** mean the Graph stopped. Otherwise `pending_enforcement`.
- `GET /killswitch`: durable account latch plus separately confirmed rail/card
  state. There is no reenable/resume endpoint; old permissions never reactivate.

Run stop returns `status: pending_enforcement`,
`financial_revocation: pending_run_binding`, `graph_cancellation: not_acknowledged`,
and `provider_card_controls: pending_run_binding`. This deliberately exposes
unfinished financial enforcement. It does not invoke account stop, close another
run's cards, revoke a shared mandate, or invalidate the agent's account token.
Agent registration of the **same stopped run ID** is now 409. A different run ID
is not yet bound to fresh human launch approval; R12 must prevent autonomous
replacement using a static credential.

Agent-owned `GET /agent-runs/{id}/control` is unchanged: `cancel_requested` and
`authority_current`. Workers do not yet poll/cancel; an offline worker is not an
acknowledged cancellation. Late sanitized traces remain accepted as evidence.

Forward migration `0008_card_closure_intents.sql` permits CLOSED while preserving
historical PAUSED rows/checksums. Only an observed CLOSED for the exact card can
confirm the new operation. Timeouts, a PAUSED response, or wrong card identity
remain unknown/pending. Retry repeats the same non-spending closure operation.
The original authorized transaction/clearing/refund history is never reversed.

Forward migration 0009 stores only the SHA256 digest/owner/expiry of logged-out
human JWTs. `/auth/logout` commits that revocation and its event together;
subsequent human routes reject that token. New sessions have distinct jti values,
so even a same-second login cannot recreate a revoked token. Other sessions and
confirmed agent delegations remain intact; logout is not either purchase stop.
The Bearer-based confirmation endpoint rejects cross-origin ambient cookies.
These checks preserve the existing auth provider/identity mapping. No session
expiry/audience/run scope for static agent credentials is claimed.

The profile now shows separate **Stop This Purchase** and **Emergency Kill Switch**
controls. Run stops are plainly labeled requests with pending enforcement.
Mission Control, Graph activity, full payment states and a live UI rehearsal are
still incomplete. Do not present the buttons as proof of working Graph stop.

## Provider transport guard (Cameron maintains this lane)

Historical `create_virtual_card` name is preserved, but all new requests must use
`SINGLE_USE`. `VIRTUAL`/`MERCHANT_LOCKED` fail before HTTP. Require an explicit
positive integer verified amount and a caller-provided persisted UUID
`idempotency_key`; send the exact same `Idempotency-Key`. A zero provider limit is
unlimited and is rejected. Defaults are SINGLE_USE/TRANSACTION, never a $500 card.
Unknown transport outcomes and unverifiable card-type responses require original
operation reconciliation; the helper never retries or creates a replacement key.
Observed account, exact limit/duration and state must also match the verified
request; missing metadata never defaults to OPEN or the requested limit.

This wrapper does not establish authority or persist an operation. `/cards` stays
blocked; `/payments` now performs preflight only and cannot issue a grant. R04/R11 must persist verification/issuance
identity before invoking it and prove once-only secret delivery and provider
reconciliation. Mock transport tests do not prove sandbox program eligibility,
provider idempotency, automatic closure or actual authorization.

## Contract freeze required before run financial enforcement

Rishi and Cameron propose, Aditya consumes, all three agree through the existing
contract-only PR rule. Do not independently rename frozen fields or treat this
proposal as a merged wire contract:

1. Bind durable purchase attempt, run, human, mandate version/hash, verified
   checkout ID/hash, grant and dedicated card to one operation. Static tokens need
   short-lived run/mandate/version/tool/audience/expiry scopes and human launch.
2. Durable account/run stop operation IDs, suspension and monotonically advancing
   account/run generations (or equivalently tested fencing). Bind issuing
   generations into grants; check them with unused-grant consumption, original
   decision cache and event commit in one fast-path atomic operation.
3. SQL stop intent gates issuance first. Commit the Valkey barrier next; only then
   acknowledge financial effectiveness. Outbox/reconciliation retries delayed
   propagation. Missing/wiped/rebuilt fast state fails closed until durable stop
   and authority state is rehydrated. Existing AOF/PVC alone does not prove this.
4. After the financial gate, request cancellation of the owning leased/fenced
   Graph worker and closure of its exact unused card(s). Track each requested,
   pending, failed/unknown and confirmed acknowledgment independently.
5. SDK `Agent.cancel()` / invocation `cancel_signal` are cooperative and local.
   Installed Graph supports `max_node_executions`, `execution_timeout`,
   `node_timeout`, `reset_on_revisit` and session manager configuration, but defaults
   are unbounded and persistence does not itself establish financial fencing.
   Do not invent a distributed `graph.cancel(run_id)` API. Aditya must guard all
   nodes/edges and MCP side effects with current durable scope/lease checks.
6. Define race ordering: stop barrier first declines new distinct events;
   authorization first preserves its original approval. A matching retry returns
   that original decision after stop, with no new consumption. An altered retry
   is a conflict. Unknown provider outcomes prevent another card/charge/recovery.

## Owners and gates

1. Rishi R13/R12 + Cameron C11 + Aditya A14: freeze additive run/generation,
   cancellation/outcome and credential contracts; valid/error wire fixtures.
2. Cameron C02: owned durable canonical checkout/freeze/charge binding.
3. Rishi R03/R04/R11/R13 + Cameron C04/C05/C11: persistent payment/issuance ledger,
   verification, generation barriers, run card links and unknown-outcome repair.
   Test stop/issuance/consume races and loss recovery **before usable grants**.
4. Aditya A11/A12/A14: real bounded Graph, clean recovery, worker lease/cancel
   dispatch and acknowledgment; no replacement run after Stop without human action.
5. Rishi R06/R07–R10 + Aditya A13: real lifecycle events, both scoped controls,
   financial/Graph/card reconciliation projections and reconnect/replay.
6. Cameron C06/C09/C10 + all: existing LKE/Secrets/PVC/CNI/TLS verification,
   configured sandbox or labeled local rail, full 137-case acceptance and D1–D4
   rehearsal. Cloud failures are external blockers; missing Graph/ledger code is
   implementation work, not an external blocker.
