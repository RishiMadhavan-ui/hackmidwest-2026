# H14 private execution protocol and historical proposal

**Current:** private execution-v1 is implemented outside unchanged frozen R01 models/events. See [spec30](LEASH_SPEC.md#30-current-integrated-execution-protocol-and-acceptance-boundary), [current handoff](../api/full-app-handoff.md) and [test results](FULL_APP_TEST_RESULTS.md). Original proposal below is a historical coordination record; references to missing Graph/scopes/barriers no longer describe main. Frozen-contract-only review still applies to later shared schema changes. Provider card/correlation integration remains incomplete and must not be inferred from reserved UUIDs.

## Historical proposal

# H14 scope and financial activation proposal — review required

This is the concrete dependency handoff for Rishi, Cameron and Aditya. It is
**not agreed wire, implemented behavior or permission to alter frozen R01**.
Existing routes, IDs, ownership and persisted history remain compatible. Resolve
this in the required contract-only PR before any usable grant/card/charge or
human launch is enabled. [Spec 27](LEASH_SPEC.md#27-v2-post-lesson-baseline) and
[current payment ledger](../api/r03-r11-handoff.md) define the invariants.

## Identity and authority chain

| Boundary / owner | Required facts and validation | Required failure behavior |
|---|---|---|
| Human launch / Rishi R12 | Current real human session explicitly starts one run for an owned active immutable mandate version/hash. Create the server run ID; enforce account/run stop and unresolved/success reservation. Provision a short-lived delegation scoped to human, agent, run, mandate/version/hash, audiences, allowed tools/phases and expiry. | Login/draft is not launch; an old agent token/new run ID cannot resurrect stopped scope. Expired/wrong audience/tool/version denies; no credential disclosed in traces. |
| MCP / Aditya | Leash forwards scoped delegation to API; Store receives distinct store-scoped delegation. Tool names/phases and current scope are checked by the destination, not merely hooks. | No direct Python/provider fallback or unrestricted shared store token for financial completion. MCP outage fails closed. |
| Canonical checkout / Cameron C02, Rishi R03 consumer | Authenticated configured source binds checkout to verified human/delegation/session/run/attempt. Return complete immutable items, merchant, total/currency, authoritative revision, expiry and freeze identity. Explicitly define which source creates those owner bindings and authenticates them. | Caller user/run fields and service bearer alone are not ownership proof. Missing owner/revision/expiry/freeze remains observed_unverified; changed checkout forces new verification. |
| Payment operation / Rishi R04/R11 | Existing durable operation owns stable attempt/payment, checkout/hash, mandate/version/hash, run, issuance UUID, reserved instrument/grant/event references. Add worker lease epoch and persistent external intent/outcome. Never infer issuance from a reserved UUID. | Commit before external writes; compare-and-set/fence stale workers; identical retries return original operation. Timeout is unknown; no new issuance key, charge ID or recovery purchase. |
| Grant / Cameron C04/C11, Rishi issuer | Add authoritative run/attempt/account+run generation and owner/freeze binding to existing exact merchant/amount/currency/checkout/instrument/expiry scope. Validate grants against current generations, not an agent claim. | Two distinct events consume once atomically; duplicate event returns original decision even after stop. Loss recovery rejects all issuance/consumption until durable generations/revocations are rehydrated. |
| Merchant completion / Cameron C02 | Only trusted completion credential with exact operation, verified frozen checkout, grant/instrument binding, stable authorization event/idempotency key and current generation may charge. Persist/read back outcome. | Charger instrument cannot fund subscription at equal price; no caller-selected cards, rail, URL or merchant. Ambiguous completion is reconciling, never a fresh authorization ID. |
| Provider / Cameron C05, Rishi R11 | Sandbox-only SINGLE_USE per verified operation, actual supported idempotency/read-back, once-only secret delivery, token/last four only in storage. | No live funds/reusable fallback. Unknown card creation remains gated until read back; no extra purchase/card. ASA must prove supported correlation or decline. |

## Stop, generations and worker acknowledgments

- **Run Stop** preserves unrelated runs and a shared mandate; **Emergency Kill
  Switch** targets only that human's account. Both persist immutable stop intents
  and increment/fence the matching authority scope. Rishi owns SQL/control views;
  Cameron owns the atomic financial barrier and rehydration; Aditya owns Graph.
- Under the atomic fast-path protocol, a previously committed authorization wins
  with its original result; an unused stale grant loses. Issuance racing stop
  cannot activate under an old generation. SQL persistence by itself is **pending**,
  not effective rail revocation. Define the actual cutover before acknowledging it.
- State responses keep `persisted`, `financial`, `graph`, `provider` and
  `reconciliation` outcomes separate, with scope/operation identity and observed
  acknowledgment epoch. Preserve existing response fields additively. CLOSED on
  the correct unused dedicated card is independent from Graph cancellation; PAUSED
  or a queued request is not closure. Existing authorizations are never reversed.
- Aditya's owning worker holds a lease/fencing epoch, polls durable control between
  nodes/tools and during inference, and invokes SDK cooperative cancellation on
  the owning process. A remote `graph.cancel(run_id)` is not an SDK guarantee.
  Late output cannot launch tools, publish a new purchase or claim canceled before
  the matching worker acknowledgment. Worker loss remains pending/fenced.
- After unavailable/wiped Valkey, Cameron restores durable account/run generations
  and revocations before opening readiness. Rishi supplies authenticated bounded
  durable state pagination/outbox only after the protocol is agreed. AOF/PVC is not
  proof of complete restoration. No broad DB call enters the ASA critical path.

## Lab scope is additional, never financial authority

Current Lab namespace is an empty, immutable separate demo identity with fixed
local-simulator rail. Operator role/control preference cannot confirm a mandate,
mint a grant, enable a provider or execute a scenario. Cameron must derive fixture
ownership from an authenticated narrow namespace/scenario command, not arbitrary
user/body IDs; Aditya must consume that same scope and enforce bounded Graph/Stop.
Agree separate command audience/token expiry/nonce or authenticated equivalent.
Never reuse operator human JWT as a merchant/service credential. No global reset.
Cleanup preserves audit, committed outcomes and unresolved operations.

## Required review artifacts and execution order

1. **Cameron:** supply canonical checkout/freeze/bind/complete request/response
   fixtures, owner-auth proof, same-price substitution negatives and durable
   idempotency/correlation behavior; supply atomic generation/barrier/read-back
   responses and loss-recovery protocol. **Aditya:** supply Graph launch/control/
   acknowledgment and MCP scope fixtures. **Rishi:** incorporate reviewed fixtures
   into additive schemas, human launch/private credential and ledger adapters.
2. **All three:** choose exact added fields, credential format and bounded lease/
   expiry values; add success/validation/error fixtures for wrong owner/run/tool/
   audience/version/generation, missing/frozen/mutated checkout, duplicate event,
   post-stop event and unknown outcome. Record human agreement in the dedicated PR.
3. **Rishi/Cameron:** tests with real SQL and Valkey cover issue-before-stop,
   stop-before-issue, consume races, duplicate after stop, process crash, stale
   lease, wiped/restarted fast state and ambiguous provider read-back. Integration
   must approve a trusted charger without relaxing any missing proof.
4. **Aditya:** real bounded Graph encounters poisoned subscription, independent
   policy rejects before payment, guardian investigates, containment excludes
   hostile context, and a compliant alternative succeeds under unchanged mandate.
   Unknown outcomes/authorization/expiry/Stop forbid further buying.
5. **All:** genuine isolated LAB-010 and signature/Stop/reconnect/restart acceptance,
   then Cameron verifies deployment/TLS/Secrets/CNI/PVC and actual selected rail.

These are blockers, not a request to rebuild working auth/policy or transfer lanes.
Current spending/attack gates stay closed while the interfaces are unresolved.
