# Strands Graph implementation and integration handoff

**Current integration:** the proposed private execution protocol is now implemented and locally exercised through real API/MCP/merchant/rail/SQL/Redis boundaries. Temporary workers use hash-only exact-run credentials; durable evidence uses a separate service-only lane after worker expiry. [Current handoff](../../api/full-app-handoff.md), [results](../../docs/FULL_APP_TEST_RESULTS.md) and [coverage](../../docs/LEASH_SECURITY_COVERAGE.md) supersede dependency claims below. Live Akamai/injection and deployed restart/provider proof remain unverified.

## Historical branch handoff


October 11, branch `aditya/strands-graph`, based on main `138d636`.
Owner: Aditya. **Agent implementation with fixture validation; not live acceptance.**
No deployment, shared database change, frozen contract change, or API/web edit
was performed. Existing financial and Attack Lab containment stays in place.

## Implemented

`shopper/workflow.py` builds the installed Strands SDK Graph with conditional
edges: authority -> shopping -> verification -> investigation -> recovery ->
shopping, plus payment and terminal paths. Limits are three candidate attempts,
20 node executions, 45 seconds per node, 150 seconds total, 18 model calls,
60,000 estimated input tokens and 30 MCP calls. Model HTTP retries and Strands
agent retries are disabled; model requests have a 20-second timeout and explicit
output-token limits. These are execution bounds, not a provider billing guarantee.

`shopper/runtime.py` creates a fresh shopper context for each attempt. Only the
confirmed mandate, reason codes and safe exclusions cross into recovery; prior
model transcripts and listing text do not. Checkout IDs, SKUs, source hashes and
source URLs are quarantined. The shopper remains intentionally gullible. It can
browse and propose one checkout; deterministic nodes call the existing Leash and
Store MCP services for verification and completion. No direct Python merchant or
payment fallback is added. Guardian findings remain advisory and cite observed
sources; MCP listing observations are never labeled trusted checkout evidence.

Recovery requires a persisted, explicitly nonfinancial blocked operation and only
known product-policy reasons. Missing evidence, missing financial infrastructure,
changed authority, ambiguous outcomes, Stop and exhausted limits never authorize
another purchase. A financial-attempt checkpoint precedes `request_payment`,
because that endpoint combines verification and a request for authority. A
merchant's success response cannot produce an `authorized` result; that requires
the API's matching payment result. Authorization is not settlement.

`shopper/control.py` implements a fail-closed execution client and local
cancellation. It checks before/after nodes, tools and model calls, polls during
inference, signals `Agent.cancel()` and MCP cancellation, and refuses expired or
changed worker generations. This is **not** server-side Kubernetes fencing.

`provenance/workflow.py` records actual node, edge, model-hook, investigation,
recovery and payment metadata. Existing hooks record actual MCP calls and source
evidence. No model prompts, completions or reasoning enter workflow events.
`provenance/outbox.py` fsyncs sanitized event files and retries ordered delivery
across process restarts. Durable spool delivery is not proof of API persistence
or SSE replay. The image's package-tree COPY includes every new module.

## Deliberate launch gate

Production `/runs` now requires `run_id`, `launch_id` and `mandate_id` from a fresh
human launch, in addition to its existing service bearer. The CLI requires the
two launch identifiers too. A static service token cannot autonomously register
a replacement run. Missing launch fields return 409; fabricated or obsolete
launches cannot pass the backend claim. An unavailable execution backend stops
before any shopper/model/MCP activity. There is no production local-only fallback.

**Current main does not implement the execution API below. Consequently this
branch cannot start a production Graph against current main.** Do not deploy it
as a complete working purchase flow. The old single-agent HTTP fixture is retained
only in `tests/test_wiring_local.py` for transport regression coverage.

## Proposed integration surface — owner agreement required

These are explicit client expectations for review, not new shared contracts or
claims that endpoints exist. Rishi owns API/database implementation. Agree these
details before enabling the branch; update the client to the agreed contract.

All execution requests use the mode-bound agent bearer and a registered run:

| Request | Client body / expected response |
|---|---|
| `POST /agent-runs/{id}/execution/claim` | `{protocol: "execution-v1", worker_id, launch_id}`; atomically consumes a fresh human launch and acquires its worker generation |
| `POST /agent-runs/{id}/execution/heartbeat` | `{worker_id, generation}`; checks cancellation/current authority and renews only a still-valid lease |
| `POST /agent-runs/{id}/execution/checkpoint` | `{worker_id, generation, progress}`; persists bounded attempt/node/exclusion/payment-reference state, never authority |

Claim and heartbeat responses must contain `protocol: "execution-v1"`, exact
`run_id` and `worker_id`, positive integer `generation`, `authority_current: true`,
`cancel_requested: false`, `human_launch_verified: true`, `financial_state:
"unspent"` and `lease_seconds` between 1 and 30. The claim additionally requires
`mcp_scope_enforced: true`. The client subtracts request time from lease duration,
and a response received after the previous lease expired cannot revive a worker.

The financial-state vocabulary still needs agreement: the current client stops
on any value other than `unspent`, including an outcome needing reconciliation.
A complete backend must distinguish permission to continue shopping from
read-only reconciliation and completion of an already reserved operation. Never
return `unspent` for an ambiguous or spent operation merely to keep this client
running. Adapt the client after that state contract is agreed.

The backend must bind launch/lease to human, agent mode, exact mandate version and
hash, and intended run. It must atomically reject consumed launches, stale worker
generations, resumed cancelled runs, concurrent owners and budget resets. A
checkpoint's `financial_attempted: false` is an agent claim; only independent
persisted backend state can establish no financial effect. Cancellation must
serialize with grant/rail invalidation, not just update a flag. Late checkpoints
may record evidence but must never restore execution authority. Crash recovery
must reconcile an existing operation, never restart spending from attempt zero.

The client sends `X-Leash-Run-Id`, `X-Leash-Worker-Id` and `X-Leash-Generation` to
both MCP servers. **Those servers do not yet enforce these headers.** Headers are
not credentials. Aditya must wire an agreed authenticated scope check into both
servers, including direct calls, after Rishi supplies the contract; Cameron must
enforce the corresponding scope/correlation at the merchant and payment boundary.
Do not advertise `mcp_scope_enforced` until this is implemented and tested.

The proposed executable payment projection from `check_status` requires
`payment_execution: "ready"`, `operation.financial_authority: true`, and matching
run, checkout, mandate, mandate version and hash. Current blocked operations
cannot satisfy it. This projection does not replace a scoped, expiring, one-use
grant or atomic merchant/rail enforcement. It needs joint review with the
activation/reconciliation state contract.

## Events and refresh persistence

Existing frozen tool/source reports continue to use `POST /provenance`. New
workflow reports target a **proposed, currently absent** `POST /workflow-events`
with the envelope `{event_id, type: "agent.step", run_id, agent_id, agent_mode,
timestamp, schema_version: 1, phase, data}`. Allowed phase/data schemas must be
validated and size-bounded server-side; bind identity to the bearer and registered
run. Agent reports remain observations, never authoritative payment decisions.

Rishi must persist reports append-only through API-only writes and expose them
through the existing owner-scoped history/SSE replay cursor. Follow the existing
provenance duplicate convention: 409 only for an identical event under the same
caller/run; mismatched payload/ownership is 422. The outbox treats 2xx/409 as
acknowledgment, retries transient failures and preserves permanent failures in
`rejected/`. An absent endpoint's 404 is retained there, not displayed as delivered
history. The local `/runs/{id}` registry is process-local and cannot supply refresh
or cross-pod durability. Cameron must verify persistent spool volume attachment.

## Remaining acceptance gates

1. **Rishi:** agree and implement human launch, durable worker leases/generations,
   checkpoints, bounded execution state, workflow intake and replay. Exercise Stop
   while inference/tools run, late evidence after Stop, expired leases, duplicate
   launches, concurrent replicas and restarted stale workers.
2. **Cameron + Rishi:** trusted checkout ownership/session/revision/freeze,
   financial activation/reconciliation, exact checkout-to-payment binding and
   atomic invalidation. Current main intentionally blocks even the charger.
3. **Aditya after those contracts:** enforce scopes in both MCP services; integrate
   the final operation state machine; supply an independently clean alternative
   discovery path. Current store has no separate trusted alternate listing path.
   The CLI's fixed-SKU scripted fixture does not automatically pick a replacement;
   the Graph recovery tests deliberately supply separate fixture candidates.
4. **Team:** operator-authorized isolated Attack Lab, genuine Akamai tool-calling
   evidence, one-run automatic recovery, owner-scoped SSE replay after refresh,
   and a three-minute rehearsal. Do not re-enable anonymous poisoned listings.

## Validation performed

- Agents: 178 tests passed with live inference deselected, including both local
  MCP HTTP wiring tests against stub API/store decisions. Actual Graph scheduling
  and actual Strands event loops
  are exercised with explicit fixtures, not live models or a live payment rail.
- The policy decision-matrix runner passed (16 fixture cases).
- Two live inference tests and six deployed E2E scenarios skipped because their
  required configuration was absent. The historical E2E harness also needs human
  launch/Graph integration before it can serve as current acceptance evidence.
- Correctness lint and whitespace checks passed. No image build, Kubernetes
  deployment, distributed fencing test or live merchant/payment acceptance is
  claimed. Kubernetes remains the selected runtime; Compose is not a gate here.
