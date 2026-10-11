# LEASH product, architecture and implementation alignment audit

## Latest main integration: Cameron d773079 plus V2 containment

The original V2 audit below started at f2f50a5. A later fetch found Cameron's
`d773079` (PR #14), which is preserved by fast-forward on main, with no reset,
stash or branch switch. There were no overlapping file conflicts; his committed
0007 payment migration remains unchanged and the unpublished closure/session
migrations moved to 0008/0009. Current [integration handoff](MAIN_INTEGRATION_HANDOFF.md)
supersedes preflight/route status claims in historical sections.

Serious incoming drift was reported before edits: external grant writes preceded
durable SQL, payments ignored run cancellation, instruments reused old account
cards, count scope was global, canonical mapping defaulted missing facts/currency,
reads lacked same-user agent isolation, and completion retried fresh authorization
IDs with only process-memory outcomes. Narrow authorized fixes preserve retrieval,
blocked-attempt persistence, storefront and binding primitives while preventing
unsafe spending. This does not establish a finished local purchase demo.

Now implemented/tested: strict authenticated preflight, registered owned run and
stop checks, user/agent payment reads, immutable stop requests, exclusive SINGLE_USE
transport, session revocation and CLOSED intents. Partially implemented: merchant
ownership/freeze and financial ledger. Missing: actual Graph/cancel/recovery,
run financial barrier, operation-before-side-effects and reconciliation. External
configuration/live sandbox/LKE proof remain unverified. The 137-case assessment
is unchanged; new passing regression methods do not establish full acceptance.

## V2 post-lesson audit and implementation on main

**Verdict: V2 desired-state docs reconciled; implementation remains partial and
is not ready for a truthful complete three-minute demo.** All four attachments
were read completely before changes. Main started clean at `f2f50a5`, matching
fetched origin/main; no teammate push was present at that inspection. Serious
contradictions were reported before broad edits. User's direct instruction to
implement safely possible fixes supersedes the synchronization attachment's
docs-only step; attached test descriptions are requirements, not observed results.
No branch switch/reset/stash, provider operation, shared database change,
deployment/provisioning or teammate contact occurred. Frozen R01 models/events
and existing service ownership remain unchanged.

### Delta verdict and document precedence

| Direction | Before V2 | Current desired state / exact location |
|---|---|---|
| Human authority, semantic verifier, exact checkout correlation, atomic one-use grants | Already covered; foundations only partially integrated | Preserve sections 4–6, 23 and 26; [section 27](LEASH_SPEC.md#27-v2-post-lesson-baseline) strengthens stop/issuance gates |
| Run Stop versus emergency | Earlier singular account Kill Switch blurred scope | Newly explicit: independent owned run Stop This Purchase and account Emergency Kill Switch, section 27.1; unrelated runs/users remain usable |
| Stop cutover/restart/race | Account latch exists; complete SQL/Valkey issuance synchronization absent | Section 27.2: durable requested command plus separately acknowledged atomic financial barrier, generations or equivalent fencing, loss recovery and original retry semantics |
| Graph | Real Graph/recovery already mandatory but not implemented | Section 27.3: actual SDK limits, owning-worker local cooperative cancellation plus persisted scope/lease fencing; no invented cross-pod graph.cancel API |
| Lithic card type/lifecycle | Wrapper allowed/defaulted VIRTUAL; docs preferred SINGLE_USE/PAUSE | Conflicting behavior fixed at transport: exclusive SINGLE_USE, positive explicit limit/stable UUID key, CLOSED intents; one verified checkout/operation per card still missing, section 27.4 |
| Identity/logout | JWT foundation retained; logout event only | Durable per-session token-hash revocation/new-login jti added. Static shopper tokens still lack expiry/audience/run scope. Logout is not financial Stop. Section 27.5 |
| Security cases | Component suites and six gated scenarios, no 137-case index | Exact supplied [137-case specification](LEASH_SECURITY_TEST_CASES.md) plus [complete current coverage index](LEASH_SECURITY_COVERAGE.md) |

The AGENTS V2 precedence/invariants/current-handoff blocks, build-plan V2
precedence and R13/C11/A14/H14 gates, and spec27 are synchronized. Earlier account
PAUSE-only implementation claims and original audit results below are historical,
not the current implementation boundary. Under-$40 is normalized to inclusive
max_cents=3999; no unagreed exclusive-limit field or new reason enum was invented.

### Critical drift, current paths and exact safe fixes

| Severity | Current code boundary / implementation status | Risk / required safe fix and owner |
|---|---|---|
| **P0 run financial stop — partial** | [workflow_control.py:stop_run](../api/workflow_control.py) persists owned immutable cancellation/event; [models.py:AuthorizationGrant](../shared/leash_shared/models.py) lacks run/generation binding. Provider card rows lack authoritative run/checkout association. | New financial permission cannot be safely revoked by run without affecting unrelated authority. API explicitly returns pending_run_binding. **Rishi R13/R12 + Cameron C11, Aditya consumer:** agree additive H14 contracts, issuing-generation/run binding and atomic financial barrier; never substitute account stop or close all account cards for a run. |
| **P0 actual Graph/cancellation — missing** | [runs.py:run_shopper/RunManager](../services/agents/shopper/runs.py) calls a single Agent with in-memory progress; no Graph/limits/clean recovery, control polling, lease/fence or owning-worker cancellation. | Stopped/restarted worker could continue/replace a run; SQL intent does not stop an invocation. **Aditya A11/A12/A14 + Rishi R12:** actual bounded Graph, persisted eligibility, run scopes/human launch, owner dispatch/cooperative cancel and stale-worker fencing. SDK installed capability is not implemented orchestration. |
| **P0 verified payment chain — missing/partial** | [checkout_verifier.py:verify_checkout](../api/checkout_verifier.py) uses explicit trusted-caller predicates; [payment_service.py:request_payment](../api/payment_service.py) has authenticated retrieval and blocked-attempt persistence, but no spending-enabled issuance/reconciliation path. [store/main.py:get_checkout/complete_checkout](../services/store/main.py) has process-memory binding primitives without owned durable freeze/charge; valid-bound completion remains 503. | Schemas/agent claims/booleans cannot establish independent checkout trust. **Cameron C02 + Rishi R03/R04/R11:** configured authenticated retrieval, owner/revision/freeze and exact protected charge association; durable attempts/issuance keys/reconciliation before external writes. Keep direct issuance/completion blocked until complete. |
| **P0 cross-store stop/issuance/loss — partial** | [workflow_control.py:stop_workflow](../api/workflow_control.py) commits SQL then separate rail/card calls; [webhook/store.py:RedisGrantStore](../services/webhook/store.py) has account latch/atomic consume/cache/stream but no run generations or durable rehydration protocol. Individual mandate replace/revoke still lacks rail propagation. | Delayed propagation, wiped fast state and stale issuing scope can invalidate the assumption of current authority. **Rishi R11/R13 + Cameron C04/C11:** persist operation/outbox, gate issuance, establish precise Valkey cutover and fail closed until durable generations/revocations rehydrated; race/rebuild tests. AOF/PVC alone is not this guarantee. |
| **P0 provider lifecycle — transport hardened, integration missing** | [lithic.py:create_virtual_card](../shared/leash_shared/lithic.py) now rejects reusable types/zero/default limits, sends caller UUID key and exposes unknown outcome without retries. [workflow_control.py:close_owned_cards](../api/workflow_control.py) records/retries CLOSED, never counts PAUSED as closure. | Provider idempotency, one verified operation/card, once-only secret delivery, multi-card run inventory and create/charge reconciliation are not proven. **Rishi R04/R11 + Cameron C05/C09:** durable operation before call, sandbox support/idempotency/read-back tests, exact card/run binding; no new key/card on unknown outcome. |
| **P0 ASA/merchant correlation — blocked approvals** | [handler.py:authorize](../services/webhook/handler.py) and signed ASA adapter deliberately fail closed without trusted checkout/SKU correlation. | HMAC/card type/merchant/amount cannot prove SKU. **Cameron + Rishi H05/C05:** protected merchant association before ASA approvals; verify program/enrollment/HMAC/HTTPS with real signed sandbox traffic, otherwise labeled local rail. Do not populate matching metadata from a grant to fabricate independent charge evidence. |
| **P0 complete evidence/UI/demo — partial** | [activity.py:stream_activity](../api/activity.py) persists/replays real owned events; [run-stops.tsx](../web/src/components/run-stops.tsx) and [kill-switch.tsx](../web/src/components/kill-switch.tsx) show separate controls with pending states. Product views/Graph/payment lifecycle emitters and genuine live model/injection are missing. | Passing profile/feed tests cannot establish Mission Control, automatic recovery, complete SSE, stop acknowledgments or a live demo. **Rishi R06/R07–R10 + Aditya A13/A07/A10:** real state projections/events, browser acceptance, D1–D4 and timed rehearsal. |
| **P1 logout — fixed in local SQL/HTTP scope** | [auth.py:logout/token_is_revoked](../api/auth.py), forward migration 0009, unique new-login jti. | Presented JWT now denied on future human routes; no raw token persisted, unrelated sessions/delegations preserved. Existing in-flight mutations that passed auth are not automatically undone; run/account Stop remains required to revoke delegated authority. Deployment and provider/session integration remain unverified. |
| **P1 zero-price schema — contract conflict retained visibly** | Frozen [models.py:CheckoutItem](../shared/leash_shared/models.py) Cents permits zero; verifier now blocks nonpositive item prices. | CHK-018 requests Pydantic validation-stage rejection. **Rishi with all-three contract review:** decide additive stricter purchase validation without changing legitimate shared zero-valued tax/shipping semantics; current case is NOT_RUN, not PASS. |

### Two-stop design: what is implemented and what is still proposed

Run API is human-owned, idempotent and durably scoped; it leaves another run and
shared mandate active and rejects registration retry using its same stopped ID.
It returns financial_revocation=pending_run_binding and Graph=not_acknowledged.
No effective run financial barrier, card closure or short-lived credential
revocation is claimed. A new run ID using the same static credential is still a
gap requiring human-launch scope; do not call RST-018 complete.

Emergency API revokes owned SQL authority/cancel intents before external calls,
gets acknowledgment from the existing atomic account rail latch, and records
provider CLOSED intent before requesting closure. Unknown/PAUSED/wrong-card
responses remain pending, concurrent late timeout cannot overwrite a confirmed
closure. Top-level financially_stopped means financial acknowledgments only;
Graph remains unacknowledged. Prior approved cached decisions/history are retained.
There is no reenable-old-authority route. Multiple-card, simultaneous global Stop,
provider, pod restart and generation rehydration acceptance remain unproven.

The correct H14 protocol, scoped credentials, race branches, explicit statuses,
distributed SDK cancellation and exact owner gates are specified in
[the V2 handoff](../api/v2-stop-handoff.md). This is a proposal needing contract
review, not a claim those cross-service wires are frozen or implemented.

### Requirements, tests and remaining dependencies

The [137-row implementation index](LEASH_SECURITY_COVERAGE.md) is the complete
requirement-by-requirement matrix for V2: source path/function, owner, actual or
planned test, existence, environment/command/evidence, status and remaining fix.
The original specification bytes have SHA256
F709498DECB7FC78ECD2846A6F6E786498FFA29658A036D4558F8A9FB28D9D4D.
Current assessment: **35 PASS in explicitly tested component scopes, 46 NOT_RUN,
51 MISSING, 5 BLOCKED_EXTERNAL; total 137.** No complete live Graph, sandbox
payment integration, effective run financial stop or demo is claimed. Current
test outputs and exact environments are in [V2_TEST_RESULTS.md](V2_TEST_RESULTS.md).

Highest priorities in dependency order: **all three H14** agree run/attempt/
checkout/grant/card/generation/credential contracts; **Cameron C02/C11 + Rishi
R03/R04/R11/R13** implement trusted durable financial/stop barriers; **Aditya
A11/A12/A14** implements real bounded Graph/clean recovery/worker cancellation;
**Rishi R06/R07–R10 + Aditya A13** complete real events and UI; **Cameron C06/C09/C10
and all three A07/A10** verify LKE/selected rail/full negative subset/D1–D4.
Build-plan tasks name artifacts, consumers and completion gates for humans and
their agents; no lane was reassigned.

External dependencies: sandbox SINGLE_USE program support/idempotency/ASA enrollment,
HMAC/HTTPS, actual LKE image/source/Secrets/TLS/CNI/PVC/worker bindings, genuine
Akamai inference tool call and live injection/rehearsal. Missing Graph, ledger,
run scopes, merchant binding and rehydration are implementation work, not external
configuration excuses. Use actual local rail labeling while provider proof is absent.

Documents changed: AGENTS V2 rules/status; LEASH_SPEC normative section27;
Leash-build-plan R13/C11/A14/H14 and dependency gates; this audit; exact security
case file; coverage index; test-results/evidence; api/v2-stop-handoff and historical
alignment handoff precedence. Prior valid integrations/contracts/history preserved.

## Historical pre-V2 implementation follow-up on main

### Pre-V2 implementation follow-up on main

The master specification remains the desired-state baseline. This follow-up integrates Cameron's activity/local rail (`674ef75`), ASA adapter (`a9e8cba`) and simulated merchant (`cb9263a`) with authorized implementation fixes (`09ee628` and the integration change containing this report). Main is retained; teammate commits are preserved. No reset/stash/branch switch, shared database mutation, deployment, provider operation or teammate contact occurred. Frozen R01 `models.py` and `events.py` are unchanged. The original documentation-only audit is retained below as history; it is not current implementation status.

**Verdict: materially stronger foundations, still not an aligned or demo-ready complete MVP.** Identity-only signup, sandbox-only provider access, registered provenance, persisted owned SSE/Next proxy, pure semantic policy, atomic strict local rail, durable rail-event delivery and human stop/provider PAUSE intent now work in their tested scopes. Trusted merchant retrieval/protected charge, product payments/issuance/reconciliation, real Strands Graph/clean automatic recovery, cooperative stop, ephemeral scopes and complete UI/events remain missing or partial. A seeded backend fixture grant is not a verified purchase. An ASA adapter/HMAC secret is not a proven Lithic authorization integration.

Rishi's later implementation/testing/main-push authorization supersedes the earlier audit-only scope without transferring lane ownership or waiving contract-only review. [AGENTS](../AGENTS.md), [spec26](LEASH_SPEC.md#26-master-alignment-baseline--october-10-2026), [build plan](../Leash-build-plan.md) and [current callable handoff](../api/alignment-fixes-handoff.md) describe the same scope. IT/IU/PI/M/BC/UV retain the status definitions in the historical audit; evidence is local unless stated otherwise.

## Critical remaining deviations and exact safe fixes

| Severity | Current evidence / risk | Owner and required next fix |
|---|---|---|
| **P0 financial chain** | [checkout_verifier.py](../api/checkout_verifier.py) is pure policy; [main.py](../api/main.py) has no product `/payments` or trusted checkout retrieval. [store/main.py](../services/store/main.py) now creates/reads canonical process-memory checkouts, but lacks owned sessions, durable freeze/expiry and protected charge. Its former unverified direct Lithic call was disabled; completion returns 503. Caller-supplied policy booleans and valid schemas are not independent evidence. | **Cameron C02/H04/H05:** authenticated canonical source/freeze/bind/protected charge. **Rishi R03/R04/R11:** retrieval/current signature validation, persistent attempts/verification and operation before side effect. No usable grant until all steps succeed. |
| **P0 Graph/recovery/cancel** | [runs.py:run_shopper](../services/agents/shopper/runs.py) still executes a single Agent, with in-memory progress. [workflow_control.py:run_control](../api/workflow_control.py) exists but workers do not poll. No automatic quarantine/clean recovery, fencing or bounded Graph. | **Aditya A11–A13:** actual SDK Graph, typed backend branches, deterministic exclusions/clean contexts, bounded recovery, cancellation checks and durable lease/fencing with Rishi. No purchase after unknown/hard decline/success. |
| **P0 cross-store lifecycle** | [mandate_service.py](../api/mandate_service.py) individual replace/revoke does not propagate to Valkey; [store.py](../services/webhook/store.py) enforces only its current authority projection. Global human stop is coordinated, but production grant activation/order is absent. | **Rishi + Cameron:** tested versioned activation/invalidation protocol, durable operation identity, safe issuance and reconciliation. Do not treat pending SQL audit delivery as effective financial revocation. |
| **P0 ASA correlation** | [asa.py](../services/webhook/asa.py) authenticates origin but gets no trusted exact checkout/SKU association. [handler.py](../services/webhook/handler.py) blocks ASA approval even for a legacy unbound grant. Actual ASA is not purchase-ready. | **Cameron + Rishi:** merchant-enforced checkout/grant/instrument correlation established before charge; valid signed sandbox approval/decline only after that protocol exists. Choose labeled local rail meanwhile; do not copy grant bindings onto an arbitrary provider charge to invent proof. |
| **P1 credential/session scope** | [principals.py:agent_from_token](../api/principals.py) is static owner/agent/mode, without expiry/run/tool/audience. [auth.tsx](../web/src/lib/auth.tsx) uses localStorage JWT; server token revocation/TLS/provider migration unresolved. Store caller credential is not yet a user/session scope. | **Cameron auth lead + Rishi R12 + Aditya:** preserve UUID identity, agree provider/equivalent, verify backend sessions, ephemeral scoped tools and owned canonical checkout. No competing auth framework introduced here. |
| **P0 full evidence/product** | [activity.py](../api/activity.py) persists available real events, but no Graph/inference/recovery/reconciliation emitters or incident/payment state exist. Profile feed/stop is not the six required views. | **Aditya A13 + Rishi R06/R07–R10:** agreed additive event contracts, full lifecycle capture, confirmed-intent UI/comparison/incidents/history/Attack Lab. No fabricated animation or paid/settled claim from grant/model output. |
| **P1 deployed source/boundary** | Public read-only checks: API health/ready200; rail HMAC configured true; `/rail/openapi.json` still public200. Source now narrows rail proxy, blocks `/backend/internal`, restricts pod keys and declares AOF/PVC/NetworkPolicy. These fixes are not deployed proof. | **Cameron C06/C09:** build/root image import checks, deploy reviewed main, verify HTTPS/CNI/key scopes/PVC/AOF restart and source digest. No live key value was read/printed. |
| **P0 live acceptance** | Six E2E skipped; two live inference tests deselected. No actual merchant purchase, successful live injected attempt, automatic recovery, real provider pause or <=3-minute rehearsal was run. | **All owners / Aditya A07:** complete dependencies then run actual selected-runtime scenarios S1–S7, fault/replay/restart and timed live rehearsal. Clearly label fixtures/local rail and any recording. |

## Current full requirements-to-code matrix

These 100 rows supersede historical H-Q rows for current source status. References F1–F11 identify executed evidence below. An IT entry is limited to the behavior/environment explicitly described, not an inferred full product implementation.

| ID / master section | Requirement | Current source/evidence and implementation status | Owner / priority / next dependency |
|---|---|---|---|
| Q01 / 0,21,23 | Inspect current main/worktree/integrations; preserve teammates; respect subsequent implementation authorization | PI: current main integrates 674ef75/a9e8cba/cb9263a and authorized fixes. Deployed API ready200 and rail HMAC configured; public wildcard OpenAPI still reachable F10. Actual rollout revision unknown. | All / P0: reconcile live revision before claims |
| Q02 / 1–3,16 | FinTech intent→behavior→trusted checkout→deterministic spending product | PI: identity/authority/MCP, pure verifier, strict local rail and persisted evidence exist. Complete merchant→verified payment→Graph/product UI chain absent. | Rishi+Cameron+Aditya / P0 |
| Q03 / 2,20 | Genuine three-minute sponsor/demo proof | M: no rehearsal or end-to-end result; demo script is a target | Aditya with both / P1: actual stopwatch/logs |
| Q04 / 6 | Backend-verified human session and stable owner | IT: `auth.py:get_current_user`, `principals.py:leash_user_id`; JWT/UUID owner tests F1; custom auth only | Cameron auth lead + Rishi / P0: provider decision/adapter |
| Q05 / 6,21 | Preserve agreed auth provider work; no competing framework | PI/UV: existing UUID/JWT preserved; no competing framework. Cameron auth-provider decision and session hardening still needed. | Cameron+Rishi / P1 H03 |
| Q06 / 6,17 | Secure session transport/storage/revocation and appropriate CSRF | PI: Bearer JWT/localStorage and seven-day default retained. Logout records an event but does not revoke JWT; deployed public HTTP/TLS/session scope remains a gap. | Cameron+Rishi / P1: TLS/session design; compromised-session protection partial |
| Q07 / 6 | Short-lived user/run/mandate/version/tool/audience agent credentials | PI: `principals.py:agent_from_token/bind_agent` owner/mode enable/rotation F1; no expiry/audience/run/tool claims | Rishi R12+Aditya / P0 |
| Q08 / 6,11 | Authenticated service/merchant/provider identities | PI: service/MCP auth plus distinct rail control/charge/event credentials and mandatory ASA HMAC implemented F1/F3/F4/F5. Store service auth is mandatory; user/session scope remains absent F11. | Cameron+Aditya+Rishi / P0 |
| Q09 / 6,18 | Object ownership on all reads and writes, including SSE | PI: owned mandates/cards/runs/provenance/history/SSE/control and internal owner consistency tested F1/F6. Purchase/checkout/incident routes still absent. | Rishi / P0: owner tests per endpoint |
| Q10 / 4,7 | Only human confirms exact structured authority; no agent privileges | IT: `mandate_routes.py:MandateConfirmation/approve_mandate`, `signing.py`; role/version/hash/signature negatives F1 | Rishi R02 retained; UI confirmation still Q59 |
| Q11 / 7 | Immutable original instruction/constraints/versions; signed/hash distinction | IT: `models.py:PurchaseMandate/mandate_hash`, `mandate_service.py:version_record`, SQL immutable triggers, Ed25519 F1 | Rishi; no passkey/AP2 claim |
| Q12 / 7 | Strict cents, UTC, supported currency/quantity/recurrence/attribute validation | IT for strict frozen shapes and pure policy F1; no complete trusted retrieval/purchase path. | Rishi R01 retained; R03 must enforce |
| Q13 / 7,9 | Under $40 means <4000, full total including charges | PI: pure verifier tests 3999/4000 and item+tax+shipping totals F1. Human semantic parser/confirmation UI and explicit additional fee/discount mapping pending. | Rishi+Cameron / P0: freeze zero fees/discounts for fixture or additive validated mapping |
| Q14 / 7 | Ambiguity requires human structured clarification | M: no actual interpretation/confirmation purchase UI | Rishi+Aditya / P1; never silently accept model draft |
| Q15 / 7 | Expiring active authority / replacement / revocation / history | IT for signed immutable SQL lifecycle F1. Kill stops all owned current authority; individual replace/revoke→rail propagation pending before grant issuance. | Rishi; cross-rail invalidation Q38 missing |
| Q16 / 7,15 | Enforce one successful checkout/quantity; consumed/fulfilled scope | PI: quantity/scope pure checks and atomic one-success-per-mandate-version cap tested F1/F5. Product reservation/fulfillment/operation integration absent. | Rishi+Cameron / P0 R04/C04 |
| Q17 / 6,18 | Registered live/scripted run owner/mode/version/hash before traces | IT: `mandate_service.py:register_run`, `shopper/registration.py/credentials.py`; F1/F2 | Rishi+Aditya; actual deployed provisioning UV |
| Q18 / 3,18 | Human can initiate/manage purchase workflow | PI: API proposes only via agent bearer; human confirm/read/replace/revoke exists; web only auth/profile | Rishi / P1: UI uses scoped draft proposal path; no grant from initiation |
| Q19 / 8 | Separate attackable listings from authenticated canonical merchant | PI: services/store canonical catalog is separate from attackable HTML; mandatory private service auth tested F11. Checkout ownership/session/freeze remains missing. | Cameron C02 / P0 |
| Q20 / 8,17 | Good charger and bad subscription same merchant/2999/USD | IT for canonical catalog facts F11: CHG-65W and SUB-CARE-MO share VOLT SUPPLY CO/5732/2999/USD and differ in product/subscription/recurrence. No actual charge/purchase acceptance. | Cameron+Aditya / P0; aliases preserved |
| Q21 / 8,10 | Safe compliant alternative outside quarantined source/SKU | M: store has no separate compliant recovery SKU/source or exclusion registry; two products only. | Cameron C02+Aditya A12 / P0 |
| Q22 / 8,18 | Independent server fetch configured merchant, never agent URL/cart | PI: store has authenticated checkout GET F11, but the API still has no independent configured retrieval/snapshot pipeline. Pure policy is not a fetcher. | Rishi R03+Cameron H04 / P0 |
| Q23 / 8,9 | Trusted SKU/category/attributes/quantity/subscription/recurrence | PI: store catalog supplies exact SKU/category/USB-C/wattage/quantity/subscription/recurrence F11; pure deterministic checks F1. Complete authenticated owned snapshot/retrieval is pending. | Rishi R03 / P0; guardian not proof |
| Q24 / 8,9 | Ownership, checkout revision/hash/expiry/provenance integrity | PI: frozen snapshot hashing/expiry/owner checks and pure verifier F1; protected merchant retrieval/freeze/revision association absent. | Rishi+Cameron / P0 |
| Q25 / 8,9 | All constraints deterministic, unknown category/evidence fails closed | PI: api/checkout_verifier.py:verify_checkout implements all 15 checks and fail-closed unknowns, tested F1. No API retrieval/verification/payment integration. | Rishi R03 / P0: pure verifier tests |
| Q26 / 9 | Stable typed reasons/observed checks/evidence, no model override | PI: pure policy returns typed verified/blocked checks/reasons F1; no model override. Persistent attempt/evidence/API orchestration pending. | Rishi R03 / P0 |
| Q27 / 9 | Merchant/currency/strict total/fee arithmetic/geo/shipping controls | PI: pure merchant/currency/full-total/shipping predicates tested F1; free-text location fails closed, no complete fee/merchant normalization. | Rishi+Cameron / P0 |
| Q28 / 8,12 | Frozen exact checkout-to-charge correlation prevents equal-price SKU substitution | M: merchant has no immutable checkout/grant/instrument binding. Store complete returns 503 before any provider call F11; this prevents bypass but is not an implemented purchase. | Cameron C02+Rishi R04 / P0 |
| Q29 / 12 | Usable instrument only after verified purchase; correct SINGLE_USE lifecycle | PI: signup issuance removed, direct /cards blocked F1. Existing cards are not auto-revoked by source changes; Kill records owned PAUSE outcomes. Verified SINGLE_USE issuance absent. | Rishi+Cameron / P0 |
| Q30 / 12 | Sandbox-only accurate provider selection; local simulator actual policy | IT for sandbox-only URL guard F1 and actual local policy F5; no live sandbox approval claim. | Cameron C03/C05 / P0 |
| Q31 / 12 | Short-lived exact scoped one-use grant bound to complete authority/checkout/instrument | PI: complete frozen grant installation, <=1800-second lifetime, immutable bindings and atomic consumption tested F5. Verified production issuer/persistence absent. | Rishi R04+Cameron C04 / P0 |
| Q32 / 12 | Activation ordering/setup failure unusable | M: protected prepare/bind/activate/rollback protocol still absent. Signup no longer bypasses it by issuing a card. | Rishi+Cameron / P0 |
| Q33 / 12,15 | Payment operations before side effects; stable provider idempotency | PI only for non-spending PAUSE intent before provider call (0006) F1. Purchase/card-issuance operation ledger/idempotency remain absent; those HTTP side effects disabled. | Rishi R11+Cameron C05 / P0 |
| Q34 / 12,15 | Unknown outcome reconciles; no new purchase/card on timeout | PI: financial MCP timeouts say unknown/no additional purchase; provider PAUSE intent safely retries same state F1. Payment operation lookup/reconciliation/Graph gate absent. | Rishi+Cameron+Aditya / P0 |
| Q35 / 12 | Verified/grant/card/pending/authorized/settled meaning separate | PI: `PaymentResponse` documents permission, distinct `payment_result` F1; no durable operations or settlement input | Rishi+Cameron+Aditya / P0: additive mapping |
| Q36 / 12 | Actual Lithic ASA enrollment/schemas/signatures/live signed authorization | PI/BC: services/webhook/asa.py HMAC/strict normalization/HTTP decline tests F5; deployed health reports key configured F10. Trusted checkout correlation absent so source ASA cannot approve. No enrollment/signed provider round trip exercised. | Cameron C05 / P1; choose actual simulator until proven |
| Q37 / 12,15 | Pure deterministic ASA/local rail, no LLM/SQL/merchant network | IT for pure decide/atomic local handler with Valkey-only critical I/O F5; relay/provider calls outside authorization path. Complete merchant integration and live ASA approval absent. | Cameron C03/C04 / P0 |
| Q38 / 12,13,15 | Valkey atomic consume + original decision + event commit; revocation serialization | PI: consume/cache/rail-stream Lua, user-stop serialization and fenced API relay tested with real Redis F5/F6. SQL/Valkey replacement/issuance consistency protocol still missing. | Cameron C04+Rishi R04/R05 / P0 |
| Q39 / 12,15 | Exact duplicate cached response; distinct parallel requests consume once | IT for local handler: 16 distinct concurrent events consume once; original duplicate preserved, two-grant cardinality tested F5. Not a live provider or merchant race proof. | Cameron C04/C07 / P0 |
| Q40 / 12,19 | Altered duplicate fingerprint/unsupported request/authentication errors | IT for local altered duplicates/strict HTTP, mandatory ASA auth/typed errors and scope-separated event IDs F5. Unsupported provider request coverage remains bounded. | Cameron C05/C07 / P0 |
| Q41 / 12,15 | Grant expiry/old version/cardinality/reservation/invalidation across replicas | PI: server-clock expiry/current-version/one-success/user-stop checked atomically F5; immutable replay tombstones retained. SQL activation/replacement propagation and deployment restart proof pending. | Cameron+Rishi / P0 |
| Q42 / 12 | Once-only authorized card detail delivery; store only token/last4 | PI: direct card routes omit PAN F1; wrapper optional details return, no durable delivery marker/authorization flow | Rishi R04+Cameron C05 / P0 |
| Q43 / 12,17 | Relevant provider card pause/close/expiry/reconciliation | PI: provider pause/close adapter validates card identity/state; durable owned PAUSE intent/outcomes and timeout retry tested with mocks F1/F5. No live pause, provider expiry or purchase reconciliation proof. | Cameron C09+Rishi R05/R11 / P0 if provider selected |
| Q44 / 12 | Actual decision source/rail/latency measured, ASA deadline met | PI: local HTTP measures actual decision latency/source; no p50/p95 target or provider deadline performance proof. Relay does not fabricate a latency. | Cameron C09 / P1; no fabricated numbers |
| Q45 / 10,11 | Real Strands shopper with genuine MCP tool invocation | IT SDK subprocess MCP wiring with substitute model/API/store F2. Genuine Akamai inference remains BC; source now attributes only configured provider. | Aditya A02/A03; no live claim |
| Q46 / 10 | Real SDK Graph / all required nodes / typed conditional edges | M: single Agent D05; local SDK GraphBuilder introspection T9 confirms capability | Aditya A11 / P0 |
| Q47 / 10 | Candidate/node/time/cost bounds and truthful terminal/exhaustion | M: threadpool max2 and test polling timeout do not bound workflow | Aditya A11/A12 / P0 |
| Q48 / 10 | Guardian explains linked genuine evidence without financial authority | IT for advisory evaluator: `guardian/__init__.py:evaluate`, known source filtering, strictness/model fallback F2; integrated incident UI absent | Aditya A05+Rishi R06 / P1 |
| Q49 / 10 | Source/SKU/checkout quarantine and fresh uncontaminated context | M: no containment controller; manual new-run tests D06 | Aditya A12 / P0 |
| Q50 / 10 | Autonomous unchanged-mandate recovery without human restart | M: S6 creates new run manually, no Graph D06 | Aditya A11/A12 + backend / P0 |
| Q51 / 10,12 | Recovery forbidden after hard decline, unknown outcome or authorization | PI: unknown-outcome advice corrected and one-success rail cap exists. Actual recovery/operation controller absent; cannot prove Graph stops financial retries. | Aditya+Rishi+Cameron / P0 |
| Q52 / 10,15 | Cooperative cancellation/recheck before every side effect | PI: durable cancellation and agent-owned /agent-runs/{id}/control F1. RunManager/Graph does not poll it; cooperative side-effect cancellation missing. | Aditya A12+Rishi R05 / P0 |
| Q53 / 10,15 | Durable progress/exclusions/leases/fencing, restart safety | PI: SQL run registration plus durable cancellation/pause operations F1. Run progress/exclusions/final output/leases/fencing still process-local or absent. | Rishi R11+Aditya / P0 |
| Q54 / 11 | Official MCP adapters, four finance + shopping tools; no direct fallback | IT official authenticated thin MCP adapters F2–F4; timeout warning improved. Financial targets and canonical merchant remain unfinished. | Aditya retained; Rishi/Cameron implement targets |
| Q55 / 11,17 | Store-only browse/off-origin redirects reject; arbitrary internal URL denied | IT: `mcp-store/main.py:resolve_store_target/fetch_store_page`, F4 | Aditya; configured-origin trust/egress still Cameron |
| Q56 / 11,18 | MCP tool authority derives authenticated run scope; direct bypass equally enforced | PI: distinct local charge/control/publisher credentials and internal web-route block F5/F6. Short-lived run/mandate/tool scope and real protected merchant missing. | Aditya+Rishi+Cameron / P0 |
| Q57 / 10,14 | Original source hash, redacted snapshots and actual stored hash | IT for local/mock paths: `evidence/snapshots.py`, `hooks.py` F2/F4; real object storage BC | Aditya+Cameron; record real storage availability |
| Q58 / 5,10 | Genuine Akamai Strands tool-calling, provider fallback truth | BC: configured-provider attribution fixed, matched env/model settings tested F2. Two genuine inference tests deselected; no live Akamai tool-call proof. | Aditya A02 / P0: actual round trip/latency/failure evidence |
| Q59 / 3,16 | Mission Control/explicit human semantic confirmation/original intent visible | M: home auth card only; no purchase UI; signature API exists Q10 | Rishi R08 / P1 |
| Q60 / 16 | Live activity/Graph/clean recovery and readable comparison | PI: genuine profile activity/SSE source exists F6/F7; required Graph/recovery/comparison panels absent. | Rishi R08/R09+Aditya events / P1 |
| Q61 / 16 | Incident timeline/evidence inspection and genuine history/receipts | PI: owned persisted activity history works F1/F6; complete incident/receipt/evidence proof-chain reads and UI absent. | Rishi R06/R09/R10 / P1 |
| Q62 / 16 | Attack Lab changes listing only, not mandate/outcome | PI: STORE_EVIL_MODE and query toggle alter listing HTML only; catalog remains unchanged F11. Full Attack Lab/Graph outcome UI is missing. | Cameron C02+Aditya A08+Rishi R09 / P0 |
| Q63 / 13 | Human-only durable idempotent Kill Switch owner endpoint/UI | PI: human-only durable stop endpoint/control and UI compiled; SQL/rail/owned provider-intent tests F1/F5/F6. Actual browser interaction/cooperative Graph stop unverified. | Rishi R05 / P0 |
| Q64 / 13 | Atomic unused-grant invalidation, stop Graph/recovery; actual effective ack | PI: unused grant stop/revocation and effective rail ack tested F5/F6. Cancellation survives SQL restart, but workers do not cooperate; replace/revoke propagation pending. | Cameron C04+Rishi R05+Aditya A12 / P0 |
| Q65 / 13 | Provider pause requested/confirmed/failed/unknown, no reversal claim | PI: durable provider intent and actual confirmed/unknown response handling F1/F5; no prior authorization reversal claim. Provider calls mocked; live supported controls BC. | Cameron C09+Rishi / P0 |
| Q66 / 13,19 | Kill races at every phase/restart/repeated clicks/cross-owner/failure | PI: local read→commit stop/revoke races, owner isolation, repeats, expiry and provider timeout tests F1/F5; all Graph/issuance phases and deployment restart remain untested. | All within lane / P0 S7 |
| Q67 / 14,15 | Durable append-only state-event coupling and outbox | PI: commit-ordered SQL audit + consume/decision/rail-stream atomic coupling + fenced relay tested F1/F5/F6. Purchase-operation state/events absent. | Rishi R06/R11+Cameron stream / P0 |
| Q68 / 14,18 | Authenticated provenance intake, sanitization/dedup/recovery | IT for bounded registered-run /provenance sanitization/ownership/duplicate semantics F1 and real disk spool F2; original rejected spool needs operator-controlled reingestion. | Rishi R06+Aditya / P0 |
| Q69 / 14 | Comprehensive event taxonomy captures real auth/Graph/inference/all financial/recovery events | PI: auth/mandate/tool/source/authorization/stop/provider-control events persisted. Inference/Graph/verification/recovery/reconciliation lifecycle emitters/contracts missing. | Rishi contracts/R06+Aditya A13+Cameron rail / P0 |
| Q70 / 14 | Product SSE persisted id/event/data, heartbeat/reconnect/replay/resync | IT for persisted owned SQL SSE, heartbeat/after/Last-Event-ID, actual Next streaming and reconnect F1/F6. Full lifecycle coverage Q69 remains partial. | Rishi R06+Cameron integration / P0 |
| Q71 / 14,15 | Authorized history/cursors/stream ownership, refresh reconstruction | IT for owner history/stream replay F1/F6; complete incident/receipt/source reconstruction still absent. | Rishi / P0 |
| Q72 / 14,15 | SSE reconnect/browser refresh never starts new Graph or charge | IT: SSE GET/reconnect only reads history and never starts run/charge F1/F6. Distributed worker/payment restart safety remains a separate missing requirement. | Rishi+Aditya / P0 |
| Q73 / 14 | No secrets/PAN/private prompts/CoT in events, snapshots or logs | PI: frozen redaction/bounded intake/rail persisted redaction and type-only warnings tested F1–F5; store validation omits sensitive input and cannot call/log provider results F11. Future emitters/routes need tests. | All / P0 for financial data; synthetic transport/log tests |
| Q74 / 14,16 | Actual agent/rail/recording labels; block-before-payment != provider decline | PI: sandbox guard, local/ASA rail namespace and configured model attribution corrected. Actual live/scripted evidence retained; complete UI/provider outcome chain absent. | All / P1 |
| Q75 / 14 | Source→tool→trusted checkout→decision incident linkage; cautious causality | PI: source/tool hashes and guardian known citations F2/F4; no persisted complete incident | Aditya+Rishi / P1 |
| Q76 / 15 | PostgreSQL durable domain and recoverable financial records | PI: durable identity/mandate/run/audit/cancellation/provider-PAUSE operation tables F1. Checkout/grant/payment/reconciliation/incident/milestone SQL tables absent. | Rishi R03/R04/R06/R11 / P0 |
| Q77 / 15 | SQL/Valkey outages fail closed; no stale cached grants | PI: DB/Valkey failure closed, wrong stream type prevents consume, original decision survives delivery outage/replay F1/F5. Issuance/provider crash reconciliation absent. | Rishi+Cameron / P0 |
| Q78 / 15 | MCP/inference outage bounded fail-closed, no tool bypass | PI: MCP connection errors stop run F2; full Graph budgets/payment ambiguity M | Aditya / P0 |
| Q79 / 5,21 | Preserve actual LKE topology; no Compose replacement | IT for preserving existing LKE topology; 20 manifest documents parse F9. Source includes store, scoped keys, financial policies and Valkey PVC; live cluster state UV. | Cameron C06 / P0; no deployment performed |
| Q80 / 5 | Repository-root API image copies runtime/shared/migrations | IU: root API/store/webhook Dockerfiles copy their runtime/shared; API also migrations. Flat runtime import smoke passes F9; Docker daemon unavailable so no actual image build/import proof. | Rishi image + Cameron build / P1: actual image import test |
| Q81 / 5,15 | Ready database/schema vs health liveness | IT local schema/DB readiness failures F1; public health/ready200 F10. Readiness is not proof of complete payment safety. | Cameron+Rishi; not full security readiness |
| Q82 / 5,15 | Persistent trace spool survives pod restart | IU: PVC 5Gi RWO /app/trace-spool declared; local restart outbox tests F2; actual mount UV | Cameron / P1: PVC/image rollout proof |
| Q83 / 6,15 | TLS, service auth, NetworkPolicy, scoped Secrets and safe public boundary | PI: explicit pod Secret allowlists including store; financial NetworkPolicy; default-private MCP; exact signed ASA and listing-only store proxies; browser internal/checkout routes rejected F6/F7/F9. CNI/TLS/rollout UV. | Cameron+endpoint owners / P0 |
| Q84 / 5,15 | Database/Valkey availability and safe chosen runtime | PI: real disposable PostgreSQL/Redis tests pass; Valkey PVC/AOF declarations parse F9. Actual cluster persistence/restart/availability unknown. | Cameron / P0: read-only resource proof/Valkey setup |
| Q85 / 5,21 | Shared installability and reproducible imports/builds | PI: namespace marker/source-copy/PYTHONPATH works F1–F4; shared/pyproject.toml absent | Cameron C01; service owners image imports / P1 |
| Q86 / 18,21 | Frozen contracts, OpenAPI mappings and generated frontend types | PI: R01 accepted/frozen; actual OpenAPI inspected; generated api-types missing; new Graph/unknown/event concepts not yet agreed | Rishi H01/H12 with all three / P0 |
| Q87 / 18,21 | Handoff callable valid/failure examples + actual tests + limits | PI: callable current handoff api/alignment-fixes-handoff.md includes status bodies/env/tests/limits. Merchant/payment/Graph handoffs still require owners. | All named sender owners / P0 |
| Q88 / 17 | Core fraud/threat matrix covers prompt/tool poisoning, SKU/recurrence/budget/ownership/replay/kill/ambiguity/recovery | PI: real pure verifier/local rail/stop/trace negatives now tested. Merchant binding, Graph recovery, issuance ambiguity and full E2E remain missing. | Rishi/Cameron/Aditya / P0; Q19–Q78 |
| Q89 / 17 | Compromised session/stolen data/disputes have bounded partial claims | PI: JWT validation/redaction, no server session revocation/reauth or payment disputes; no broad protection proof | Cameron+Rishi / P1; disclose partial scope |
| Q90 / 17 | Dishonest merchant/fulfillment/counterfeits/ACH/full chargeback controls outside guarantee | IT as documented scope only: 23.4/26.7 limits retained; no corresponding capability claimed | All; future work, not security coverage |
| Q91 / 19 | Unit/mock integration/security matrix distinct from live provider/model E2E | IT for transparent evidence: F1–F11 separate unit/mock/local-engine/transport from live proof. Six E2E skipped, two live inference deselected. | All; cannot mark E2E complete |
| Q92 / 19 | S1 actual legitimate charger authorization/receipt | M: purchase E2E skipped T8. Catalog/create/read now exist F11; protected charge/payment operations/receipt remain absent. | All / P0 |
| Q93 / 19 | Combined live S2→S6 attack/block/quarantine/automatic unchanged-authority recovery | M: manual two-run test skipped T8; no Graph/live injection proof | Aditya+Rishi+Cameron / P0 |
| Q94 / 19 | S3 exact boundary/tax/shipping overspend no instrument | PI: pure verifier tests total/tax/shipping/3999 boundary F1; no full trusted merchant/payment E2E result. | Rishi+Cameron / P0 |
| Q95 / 19 | S4 incomplete/untrusted/stale evidence no grant | PI: pure verifier fails missing authentication/unknown evidence F1; no runtime authenticated retrieval→no-grant product flow. | Rishi+Cameron / P0 |
| Q96 / 19 | S5 expiry/replay/parallel attempts/altered duplicates | PI: real Redis local expiry/replay/concurrency/altered payload enforcement F5. Full product E2E scenario is skipped. | Cameron+Rishi+Aditya / P0 |
| Q97 / 19 | S7 master Kill Switch storyline | PI: actual local API/rail/Next stop+persisted SSE smoke F6; no real Graph cancellation or live provider/full S7 demo. | All / P0 |
| Q98 / 19 | Faults: direct bypass, provider lost response/DB failure, worker restart, model outage, malformed findings | PI: local atomic late-stop/expiry/wrongtype, duplicate/outage/crash-relay, SQL rollback and provider-PAUSE unknown tests. Payment-provider lost-success/issuance/worker recovery untested. | All / P0 |
| Q99 / 20 | Safe reset, no grant reuse/history deletion, labeled recorded fallback | PI: live/scripted distinct mandate/token/lane docs/tests; actual reset/rehearsal UV; manual recovery outdated | Aditya+Cameron+Rishi / P1 |
| Q100 / 22,24,26 | Dependency order, all critical differentiators retained, truthful completion | PI: current docs/100-row matrix reflect tested fixes and preserve every critical requirement. Complete MVP/three-minute rehearsal still not demonstrated. | All; dependency tasks below |

## Current executed tests and verification

| Evidence | Actual result | Scope and limit |
|---|---|---|
| F1 API | **107 tests pass**, 33.356s, including **25 real disposable PostgreSQL tests** and the opt-in stack smoke. API/shared correctness Ruff passed. | Signed immutable authority, identity-only signup, provenance/ownership/dedup, replay/control, provider PAUSE intent with mocked HTTP, pure verifier. No merchant/purchase/provider integration. Stack case is included in this total; scope in F6. |
| F2 Agents | **131 passed, 2 live inference deselected**, 47.15s, uv on PATH; the two subprocess MCP tests also passed separately. | Real SDK MCP clients/servers with substitute API/store/model, advisory guardian/hooks/outbox and truthful configuration attribution. No genuine model inference. |
| F3 Leash MCP | **33 passed**, 8.18s in this implementation follow-up. | Thin tool/schema/auth/mocked backend and unknown-timeout guidance; no actual product payment target. |
| F4 Store MCP | **40 passed**, 10.14s in this follow-up. | Origin/redirect/auth/evidence/snapshot and substitute merchant forwarding. No controlled merchant charge. |
| F5 Rail | **45 tests passed**, 0.946s; 14 run against real isolated Redis, plus HTTP/memory/ASA units. **16 rail YAML cases** pass through one matrix test. | Atomic consume/cache/stream, expiry/late stop/revoke, scope/tamper/replay/concurrency, strict credentials/lifetime/HMAC, persisted event redaction and durable relay outage/crash replay. Redis 6.0.16 test engine, not deployed Valkey8/Lithic. Verifier/merchant/handler/e2e YAML stages are not all executed by that runner. |
| F6 Stack | **1 passed**, included in F1's 107-test run after final runtime listing proxy, internal guard and backend rewrite-order fixes. | Real disposable PostgreSQL + Redis + API uvicorn + rail/store processes + built Next standalone. Seeded backend fixture grant, human stop/real acknowledgment, rail→API delivery, real persisted SSE and browser internal/merchant-checkout route rejection and simulated storefront/private auth/unverified-charge rejection. No model/provider/full purchase demo. |
| F7 Web | **pnpm lint and pnpm build pass**; final build includes streaming proxy and internal API guard. | TypeScript/ESLint/standalone source build only; no interactive browser test or deployed image proof. Existing .env.local loaded by build, contents not read/printed. |
| F8 Live E2E | **6 skipped**, 0.12s (`LEASH_E2E=1` not enabled). | Collection only; none of S1–S7/full Graph acceptance claimed. |
| F9 Static integration | **20 Kubernetes documents parse**, explicit Secret allowlists (no envFrom), real Bash syntax checks pass with LF. Frozen models/events diff empty; runtime files copied by owner Dockerfiles; flat runtime import smoke passes. | No Kubernetes API validation/rollout, Docker image build, Secret value read or CNI/PVC inspection. Financial policies require actual CNI support. |
| F11 Store | **15 passed**, 1.35s. | Canonical same-price product constraints, poisoned listings, mandatory auth/readiness, conflicting aliases/strict quantities, redacted validation and disabled unverified charge. Mocked Lithic assertion proves no call; memory checkout only, no ownership/freeze/restart or purchase proof. |
| F10 Public read-only | `/backend/health`200, `/backend/readyz`200, `/rail/health`200 with HMAC configured true; `/rail/openapi.json`200 lists both adapters/internal routes. | Reachability/configuration flag only; exact image/source and authorization behavior unknown. No POST/provider/sandbox mutation. Broad deployed proxy is not the new narrow source configuration. |

An early rail test invocation from root failed because the incoming ASA test lacked its import path; corrected and final suite passes. The first relay attempt used Redis6-unsupported exclusive XRANGE IDs; changed to compatible XREAD, then outage/crash replay passes. A new store image placeholder was absent from the shared render helper; STORE_IMAGE is now defined/rendered and the actual helper passes for every manifest. The first store proxy smoke exposed build-time rewrite destinations; a runtime server listing route corrected the origin mapping. The first internal-route smoke exposed Next rewrite ordering; moving the broad backend adapter to fallback fixed it, then stack smoke passed. One store validation test initially used a numeric string accepted as an integer; card expiry fields now validate strict bounded integers and the redaction regression passes. A repository-only parent-index assumption in rail imports was replaced with bounded ancestor lookup for flat image layout. First earlier Next cold-start smoke exceeded its short timeout; deadline/child cleanup corrected and later smoke passes without leaked child pipes. Passing final checks do not erase these limits or establish live integration.

## Resolved findings and outstanding configuration

- Historical D01/D02: signup card issuance and production/arbitrary-provider endpoint support removed; negative tests pass. Existing sandbox cards were not mass-revoked by this source edit.
- D03: signup provider side-effect/orphan path removed; durable non-spending PAUSE operations added. General issuance/charge operation identity/reconciliation is still missing.
- D04/D07/D08: real pure policy/local rail/stop/trace/SSE/relay foundations added; full trusted merchant/payment/Graph/full lifecycle gates remain partial.
- D10: blind retry guidance removed. D13: exception-text logging narrowed and provider attribution is configuration-based. D14: web effect lint fixed. D15: source Secret allowlists and financial policies added; actual deployment verification pending.
- R01 frozen contracts unchanged. Graph/reconciliation/new lifecycle concepts require a dedicated additive contract PR/all-three agreement. No ownership change is implied by narrow fixes.
- Humans must resolve Cameron's auth-provider/equivalent choice and session/TLS plan; merchant trust/taxonomy/session/freeze/binding and fees/discounts mapping; SQL/Valkey activation/revocation/fencing; concrete Graph bounds; actual provider/HTTPS/enrollment and object-storage capability. Mere env-variable names are not proof.
- Cameron supplies distinct WEBHOOK_INTERNAL_TOKEN, WEBHOOK_CHARGE_TOKEN and RAIL_EVENT_TOKEN, plus required signed ASA settings if that adapter is exposed. Old missing rail event credentials leave a retained stream pending delivery; they do not relax authorization. Actual live/scripted agent bindings/volumes remain unverified.

## Next implementation tasks in dependency order

1. **Cameron C02/H04/H05:** extend the merged catalog/authenticated checkout source with owned sessions, durable immutable checkout freeze and protected same-price SKU-to-charge binding; safe alternative outside quarantined source.
2. **Rishi R03/R04/R11 + Cameron C04/C05:** trusted retrieval/current signature checks using existing pure verifier, persisted attempts/verification/operation-before-side-effect, versioned activation/revoke propagation, idempotency, reconciliation and once-only instrument delivery. Keep unknown outcomes unusable for further purchases.
3. **Rishi R12 + Aditya H08/A11–A13:** additive typed contracts/scopes; actual bounded SDK Graph, source containment/clean autonomous recovery, control polling and durable leases/fencing; comprehensive real lifecycle emitters. Validate actual Akamai tools separately.
4. **Rishi R07–R10:** human confirmation and six required product views using authoritative persisted financial/Graph state; no hand-authored success or settlement.
5. **Cameron + all / G3/G4:** reviewed main image rollout on existing LKE with TLS/scoped keys/CNI/PVC/AOF verification; actual selected-rail S1–S7, provider faults/restart/replay, genuine live attack→automatic recovery/stop and <=3-minute rehearsal.

Preserved Cameron's store catalog/HTML/deployment additions; removed its provider-key inheritance and unverified completion path, tightened checkout auth and narrowed public store proxy. Current source still cannot claim a paid checkout.

Modified canonical docs: AGENTS current architecture/tree/boundaries, LEASH_SPEC section26.8 and factual identity/runtime mappings, build plan current task status/dependency handoffs, and this current full matrix while retaining the baseline. Added api/alignment-fixes-handoff.md and refreshed webhook README. No task is declared complete from a stub, schema, manifest or skipped test.

## Historical original audit — 2e0cbe5

Everything below describes the original documentation-only request, source revision and results. Later implementation authorization and F/Q current evidence above take precedence. Original Q IDs are prefixed H- below only to distinguish historical table rows; stable current requirement IDs remain Q01–Q100.


Audit baseline: October 10, 2026, `main` / `origin/main` at **`2e0cbe571567d3f3cca360d2dd4977776c5d18d1`**. Working tree was clean before documentation edits. Remote refs were fetched twice; no new main/Aditya commits appeared during inspection. No branch switch, reset, stash, commit, push, application-code edit, deployment, provisioning, teammate contact or shared-database write occurred. Tests used mocked services and a disposable localhost PostgreSQL instance, which was stopped afterward.

Rishi's explicit request authorizes this audit and four documentation files only. Both supplied documents were read completely before edits, including re-reading a truncated tool-output segment. Desired product/security direction comes from `LEASH_MASTER_ALIGNMENT_SPEC_2026-10-10.md` (74,216 bytes, SHA-256 `BDD05A0821DC09A5E04E0E3A448F09ACF29FEDB294F2A6618FCB9E9B43EF5B16`); the audit prompt (SHA-256 `A3CA35BDB63FCABBAE03A536FC8E2F6C387E823E249B1A35D8737015437C5FCC`) supplies workflow guidance, subordinate to Rishi's request. Neither document authorizes rewriting teammates' code. The [synchronized specification](LEASH_SPEC.md#26-master-alignment-baseline--october-10-2026) incorporates the master decisions without making teammates depend on Rishi's Downloads folder.

### Verdict

**The foundations are partly aligned; the current application is not an aligned or demo-ready LEASH MVP.** R01 validation/hashing/redaction, R02 signed immutable human authority, registered mode-bound agent identity, actual Strands MCP adapter wiring and LKE build/readiness/PVC configuration are valuable working foundations. The financial enforcement chain and the master's signature differentiators remain missing. Signup/provider behavior introduces specific conflicts even though direct `/cards` issuance is closed.

Passing existing tests does not establish trusted checkout verification, a one-use grant, payment authorization, autonomous recovery, Kill Switch, comprehensive SSE or a live attack. No approved or blocked payment scenario was executed in this audit. Previously assumed single-agent orchestration, manual recovery, narrow tool-event streaming and Compose completion are superseded. Claims must remain limited to the controlled merchant, actual correlation implemented and demonstrated rail.

Status vocabulary used below:

- **Implemented and tested (IT):** inspected executable behavior and relevant tests passed here; test environment/limits are identified.
- **Implemented but untested (IU):** concrete code/config exists but relevant execution was not performed here.
- **Partially implemented (PI):** a real subset exists; missing pieces prevent the requirement from passing.
- **Missing (M):** required behavior is absent from inspected tracked source, not merely an absent suggested filename.
- **Blocked by external configuration (BC):** integration proof depends on account/service configuration not supplied or exercised in this audit; not a claim the teammate lacks access.
- **Unknown or unverified (UV):** evidence is insufficient, especially deployed behavior whose source/version is unavailable.

P0 blocks truthful security/demo readiness; P1 requires correction/integration before the relevant claim; P2 is bounded polish/operational improvement. A missing required control is a readiness gap, not evidence an attacker has exploited a deployed endpoint.

### Serious discrepancies and exact safe fixes

| ID / severity | Evidence and conflicting code path | Risk / master requirement | Owner and minimum safe fix |
|---|---|---|---|
| D01 **P0 security** | [api/auth.py:217](../api/auth.py), `signup()` commits user at 255, invokes holder/card creation at 258/265; [lithic.py:146](../shared/leash_shared/lithic.py) defaults VIRTUAL/FOREVER and sets OPEN at 179 | Signup creates a usable provider instrument before any confirmed mandate, trusted verification or grant. Missing PAN in response does not disable the card. Prior `/cards` fix did not touch this path. Provider controls/ASA enrollment on these cards are unverified. | **Rishi** removes usable issuance from signup and decouples login from provider availability; **Cameron** supplies unusable/prepared instrument and verified-purchase lifecycle helpers. Route actual issuance through R03/R04/R11 only. Inspect/reconcile existing sandbox instruments before claiming them revoked; no audit-time mass revocation. |
| D02 **P0 boundary/claim** | [lithic.py:52](../shared/leash_shared/lithic.py) `_base_url()` accepts production and arbitrary HTTP(S); result provider fixed to `lithic_sandbox` at 215/323 | Live funds are excluded; misconfiguration can target production or send the key to an arbitrary origin while UI claims sandbox. | **Cameron:** explicit sandbox-only allowlist for MVP; reject production/unknown origins; isolated mock transport for tests. Derive accurate rail metadata from validated configuration. Add negative environment tests. |
| D03 **P0 integrity** | [auth.py:258](../api/auth.py) provider creates after user commit; on `LithicError`, `delete_user()` at 271. [lithic.py:118/190](../shared/leash_shared/lithic.py) external POSTs lack stable operation/idempotency. No payment-operation schema in `db/migrations/`. | Timeout may follow provider success: deleting local identity loses correlation, retries can create another holder/card, failed persistence leaves orphan instrument. Future charge retry would duplicate purchase. | **Rishi R11:** persist operation/owner/key/state before external write; retain unknown state and reconcile. **Cameron C05:** verified provider idempotency/status support; no blind create retry. **Aditya:** Graph stops financial recovery while unknown. Fault tests after provider success/before response/SQL commit. |
| D04 **P0 financial/demo** | [api/main.py:40](../api/main.py) registers auth/cards/mandates only; no payments/verifier/provenance routes. `services/store/`, `services/webhook/`, Valkey configuration and `tests/test_decision_cases.py` absent. R01 `CheckoutVerification`/`AuthorizationGrant` are schemas only. | No independently trusted merchant facts, enforced SKU-to-charge correlation, real deterministic authorization or atomic one-use lifecycle. Cannot demonstrate legitimate authorization or signature attack protection. | **Cameron C02–C04:** canonical merchant, protected freeze/charge binding, pure rail and atomic Valkey protocol. **Rishi R03/R04:** authenticated retrieval/full verifier and grant lifecycle. Write real boundary/concurrency tests; do not use approving stubs. |
| D05 **P0 Graph/demo** | [shopper/runs.py:99](../services/agents/shopper/runs.py) `run_shopper()` loads MCP tools then calls `agent(...)` at 125; [agent.py:37](../services/agents/shopper/agent.py) builds one `Agent`. No `GraphBuilder` import/use in tracked application. | Real Strands Graph is mandatory. SDK dependency and agent execution do not prove Graph orchestration. | **Aditya A11:** installed SDK Graph nodes/conditional edges for shopper/verifier/guardian/containment/payment/terminal, typed backend branches, explicit node/time/candidate/cost limits. Rishi supplies backend states; no model-approved payment. |
| D06 **P0 recovery/demo** | [demo-script.md:144](demo-script.md) says turn attack off and start another run; [test_s2_s6_attack_and_recovery.py:56](../tests/e2e/test_s2_s6_attack_and_recovery.py) starts another shopper. No persisted exclusion/quarantine/clean-context controller. | Manual recovery is not the master's autonomous single-Graph recovery. Reusing hostile transcript or recovery after unknown payment could repeat bad/duplicate purchases. | **Aditya A12:** deterministic pre-payment eligibility, persisted source/SKU/checkout exclusions, fresh original-mandate context, bounded recovery and cancellation. **Cameron:** safe alternative reachable without poisoned source. Test single Graph without presenter intervention, no raw attack text and no re-purchase after ambiguous/auth outcomes. |
| D07 **P0 Kill Switch** | [mandate_routes.py:101](../api/mandate_routes.py) per-mandate SQL revoke exists; [events.py:53](../shared/leash_shared/events.py) kill event is enum only. No human Kill Switch endpoint, Graph cancel or grant/card invalidation. | SQL revoke/registered-run check does not stop an already running shopper or revoke fast-path spending permission. No tested race semantics. | **Rishi R05:** human owner endpoint, durable requested/effective state and UI. **Cameron C04/C09:** serialized unused-grant invalidation and provider pause outcomes. **Aditya A12:** cooperative cancel before side effects. Gate issuance until invalidation protocol works. Preserve committed authorization. |
| D08 **P0 evidence/demo** | [outbox.py:29](../services/agents/provenance/outbox.py) posts `/provenance`; 404 is permanent at 34/132. API lacks intake. [hooks.py:127](../services/agents/provenance/hooks.py) registers only before/after tools; `audit_events` has committed mandate/run events but no delivery/read/SSE code on main. | Agents' traces move to rejected spool instead of API history. No comprehensive persisted SSE, Graph/model/recovery evidence or reloadable product timeline. MCP's event-stream transport is not product SSE. | **Rishi R06:** authenticated ownership-bound intake, identical duplicate 409/altered 422, commit then ack, history/SSE cursor replay. **Aditya A13:** full real lifecycle emitters; explicit operator-controlled reingestion of retained rejected events once route exists, respecting original ownership/dedup. Never silently relabel rejected delivery as stored. |
| D09 **P0 distributed integrity** | [runs.py:132](../services/agents/shopper/runs.py) dict registry, process-local lock/thread pool; [mandate_service.py:197](../api/mandate_service.py) persists initial run registration only | Run progress/final state and financial operation fencing do not survive pods; repeated invocation/restart can redo side effects. No run-level request idempotency or lease. | **Rishi R11 + Aditya A11/A12:** persisted milestones/attempts/cancellation/exclusions and exclusive worker lease/version/fencing; backend rejects stale side effects. Restore based on operation state, not replayed conversation. |
| D10 **P1 unsafe guidance** | [mcp-leash/main.py:81](../services/mcp-leash/main.py), `_call_api()` says “retry later” after timeout/unreachable; request_payment returns ID only if reply arrives | A future payment POST may have succeeded before response loss, and agent has no stable caller operation to poll. Generic retry advice conflicts with safe ambiguity handling. `check_status()` also calls itself read-only while documenting one-time credential delivery. | **Aditya + Rishi H07:** stable request/operation ID, typed unknown/reconciling result, status query using same identity; remove blind retry advice from financial tools. Separate/read-document credential delivery semantics and enforce delivery ownership/idempotency server-side. |
| D11 **P1 identity/network** | [principals.py:24/93](../api/principals.py) static hashed token binds owner/agent/mode only. [mcp-store/main.py:126](../services/mcp-store/main.py) store credential optional; global Store MCP token does not encode user/run. [next.config.ts:23](../web/next.config.ts) public MCP rewrites; [k8s/service.yaml:15](../k8s/service.yaml) port 80. | Missing short-lived run/mandate/version/tool/audience scope and trusted merchant ownership; public cleartext bearer transport/internal-boundary mismatch. ClusterIP/namespace alone does not authenticate calls. | **Cameron** leads H03 provider/TLS/private routing/NetworkPolicy; **Rishi R12** stable identity adapter and scoped credentials; **Aditya** endpoint/tool scope enforcement and mandatory merchant auth. Preserve current auth until agreed migration; agree any external MCP exposure. |
| D12 **P1 integration truth** | Public `/backend/openapi.json` advertises `/activity`, `/activity/stream`, `/auth/logout` absent from main and inspected remote Cameron branch. Unauthenticated activity GETs return 401; health/readiness 200. | Source/image drift: comprehensive stream scope, persistence/replay, logout semantics and deployed `/cards` patch cannot be inferred. Unreviewed live integration may differ from tested source. | **Cameron:** supply/deconflict deployed source SHA, image digest and auth/activity changes through normal handoff. **Rishi:** inspect and integrate compatible activity/auth work before writing R06/R12. Do not overwrite or redeploy during audit. |
| D13 **P1 observability/privacy** | [runs.py:183](../services/agents/shopper/runs.py) `log.exception` before redacted stored error; [sink.py:58](../services/agents/provenance/sink.py) logs exception traceback. [runs.py:58](../services/agents/shopper/runs.py) provider always says `akamai-inference`; factory accepts configured matched endpoint pairs. | Exception text can contain sensitive SDK/tool data; exact leakage not demonstrated. Provider label not verified against actual endpoint/fallback. Existing trace redaction tests do not establish whole-process log safety. | **Aditya:** sanitized error type/correlation logging without raw exception text, synthetic secret/PAN exception tests; validated actual provider identity and explicit fallback metadata. **All:** redact at ingest and transport boundaries too. |
| D14 **P1/P2 local readiness** | `pnpm lint` fails [web/src/app/profile/page.tsx:38](../web/src/app/profile/page.tsx), `react-hooks/set-state-in-effect`; tracked deployment scripts are LF but checkout CRLF, direct WSL `bash -n` fails at `need()/get_env()` | Required lint gate currently fails; Windows direct script execution is unreliable. This is not evidence Linux deployed script syntax is broken. | **Rishi:** structure profile fetch/loading state around async lifecycle without synchronous effect resets or lint suppression. **Cameron:** deliberate shell LF attributes/checkout/runbook handling; LF-normalized syntax already passes. |
| D15 **P0 secret/authority boundary** | [k8s/agents.yaml:33](../k8s/agents.yaml), [mcp-leash.yaml:21](../k8s/mcp-leash.yaml), [mcp-store.yaml:22](../k8s/mcp-store.yaml) and api.yaml all import full `app-env`. [deploy_lke.sh:109](../scripts/deploy_lke.sh) copies root .env excluding image names into that shared Secret. Template includes JWT/signing/Lithic keys and managed DB URL is added by provisioning. | When configured in app-env, financial/session signing and database credentials are inherited by shopper/guardian and thin MCP pods, violating backend-only authority and least privilege. Actual mounted contents/compromise are unverified; no key was read. | **Cameron C06:** split Secrets or explicit required secretKeyRef selection per pod; keep provider/JWT/mandate-signing/database authority out of agent/tool pods. Test rendered environment-key allowlists and preserve needed inference/store/scoped agent/service settings. |

### Requirements-to-code traceability

Every row is a requirement or explicit scope/acceptance decision from master sections (MS) 0–26. Evidence references executable paths/functions; absent implementation is stated explicitly. Tests T1–T10 are defined below. An IT row may cover only its named boundary, never the whole financial workflow. Rows marked PI/IU/BC/UV must not be called complete. Proposed fixes/tasks retain current path ownership; shared-contract additions require their own coordinated PR.

#### Product, human identity and mandate authority

| ID / MS | Requirement | Status / evidence and limit | Owner / priority / next work |
|---|---|---|---|
| H-Q01 / 0,21,23 | Inspect current main/worktree/integrations; preserve teammates; documentation audit only | IT: clean `2e0cbe5`, two fetches, branch inventory/recent merges; only four docs edited; deployed drift D12 | All / P0: reconcile live revision before claims |
| H-Q02 / 1–3,16 | FinTech intent→behavior→trusted checkout→deterministic spending product | PI: contracts/authority/MCP exist, financial chain/UI absent (D04) | Rishi+Cameron+Aditya / P0 |
| H-Q03 / 2,20 | Genuine three-minute sponsor/demo proof | M: no rehearsal or end-to-end result; demo script is a target | Aditya with both / P1: actual stopwatch/logs |
| H-Q04 / 6 | Backend-verified human session and stable owner | IT: `auth.py:get_current_user`, `principals.py:leash_user_id`; JWT/UUID owner tests T1; custom auth only | Cameron auth lead + Rishi / P0: provider decision/adapter |
| H-Q05 / 6,21 | Preserve agreed auth provider work; no competing framework | UV: current custom JWT; intended Clerk/Auth.js/equivalent and live activity auth source unknown D12 | Cameron+Rishi / P1 H03 |
| H-Q06 / 6,17 | Secure session transport/storage/revocation and appropriate CSRF | PI: Bearer JWT validated, browser localStorage; seven-day default JWT, client-only logout on main; public port80, no cookie/CSRF adapter | Cameron+Rishi / P1: TLS/session design; compromised-session protection partial |
| H-Q07 / 6 | Short-lived user/run/mandate/version/tool/audience agent credentials | PI: `principals.py:agent_from_token/bind_agent` owner/mode enable/rotation T1; no expiry/audience/run/tool claims | Rishi R12+Aditya / P0 |
| H-Q08 / 6,11 | Authenticated service/merchant/provider identities | PI: `service_auth.py`, Store MCP bearer, financial bearer forwarded T2–T4; merchant token optional, no store/rail/HMAC | Cameron+Aditya+Rishi / P0 |
| H-Q09 / 6,18 | Object ownership on all reads and writes, including SSE | PI: mandates/runs registration/cards tested T1; future checkout/payment/incident/SSE absent | Rishi / P0: owner tests per endpoint |
| H-Q10 / 4,7 | Only human confirms exact structured authority; no agent privileges | IT: `mandate_routes.py:MandateConfirmation/approve_mandate`, `signing.py`; role/version/hash/signature negatives T1 | Rishi R02 retained; UI confirmation still Q59 |
| H-Q11 / 7 | Immutable original instruction/constraints/versions; signed/hash distinction | IT: `models.py:PurchaseMandate/mandate_hash`, `mandate_service.py:version_record`, SQL immutable triggers, Ed25519 T1 | Rishi; no passkey/AP2 claim |
| H-Q12 / 7 | Strict cents, UTC, supported currency/quantity/recurrence/attribute validation | IT: shared models validators/hash vectors T1; not live policy execution | Rishi R01 retained; R03 must enforce |
| H-Q13 / 7,9 | Under $40 means <4000, full total including charges | PI: `max_cents=3999` fixtures/demo; no parser/confirmation UI/verifier; R01 total sums items+tax+shipping, no separate fees/discounts | Rishi+Cameron / P0: freeze zero fees/discounts for fixture or additive validated mapping |
| H-Q14 / 7 | Ambiguity requires human structured clarification | M: no actual interpretation/confirmation purchase UI | Rishi+Aditya / P1; never silently accept model draft |
| H-Q15 / 7 | Expiring active authority / replacement / revocation / history | IT: R02 window checks, immutable replacement/draft approval, revoke/idempotent history T1 | Rishi; cross-rail invalidation Q38 missing |
| H-Q16 / 7,15 | Enforce one successful checkout/quantity; consumed/fulfilled scope | PI: `maximum_purchases/max_quantity` validated, no actual scope reservation/consumption or fulfilled state | Rishi+Cameron / P0 R04/C04 |
| H-Q17 / 6,18 | Registered live/scripted run owner/mode/version/hash before traces | IT: `mandate_service.py:register_run`, `shopper/registration.py/credentials.py`; T1/T2 | Rishi+Aditya; actual deployed provisioning UV |
| H-Q18 / 3,18 | Human can initiate/manage purchase workflow | PI: API proposes only via agent bearer; human confirm/read/replace/revoke exists; web only auth/profile | Rishi / P1: UI uses scoped draft proposal path; no grant from initiation |

#### Trusted merchant, verifier and financial enforcement

| ID / MS | Requirement | Status / evidence and limit | Owner / priority / next work |
|---|---|---|---|
| H-Q19 / 8 | Separate attackable listings from authenticated canonical merchant | PI: MCP listing fixtures/evidence exist T4; `services/store` absent | Cameron C02 / P0 |
| H-Q20 / 8,17 | Good charger and bad subscription same merchant/2999/USD | PI: `tests/decision_cases.yaml` + listing fixtures encode facts; no actual canonical server/charge | Cameron+Aditya / P0; aliases preserved |
| H-Q21 / 8,10 | Safe compliant alternative outside quarantined source/SKU | M: no store/recovery exclusion registry | Cameron C02+Aditya A12 / P0 |
| H-Q22 / 8,18 | Independent server fetch configured merchant, never agent URL/cart | M: API verifier absent; `CheckoutSource` shape only | Rishi R03+Cameron H04 / P0 |
| H-Q23 / 8,9 | Trusted SKU/category/attributes/quantity/subscription/recurrence | PI: `CheckoutItem/CanonicalProduct` strict models T1; guardian advisory checks T2, no authentic verifier | Rishi R03 / P0; guardian not proof |
| H-Q24 / 8,9 | Ownership, checkout revision/hash/expiry/provenance integrity | PI: `CheckoutSnapshot` validates shape/hash/expiry T1; no trusted ownership retrieval/freeze | Rishi+Cameron / P0 |
| H-Q25 / 8,9 | All constraints deterministic, unknown category/evidence fails closed | M: actual API policy absent; 15 required verification checks are schema gate only | Rishi R03 / P0: pure verifier tests |
| H-Q26 / 9 | Stable typed reasons/observed checks/evidence, no model override | PI: shared verification/checks shapes + advisory guardian severity T1/T2; missing backend decision function | Rishi R03 / P0 |
| H-Q27 / 9 | Merchant/currency/strict total/fee arithmetic/geo/shipping controls | PI: validated fields/fixtures; no running enforcement or full fee normalization | Rishi+Cameron / P0 |
| H-Q28 / 8,12 | Frozen exact checkout-to-charge correlation prevents equal-price SKU substitution | M: Store MCP `complete_checkout` forwards to absent merchant; no binding enforcement | Cameron C02+Rishi R04 / P0 |
| H-Q29 / 12 | Usable instrument only after verified purchase; correct SINGLE_USE lifecycle | PI, conflicting: direct `/cards` blocked T1; signup OPEN VIRTUAL/FOREVER still exists D01 | Rishi+Cameron / P0 |
| H-Q30 / 12 | Sandbox-only accurate provider selection; local simulator actual policy | PI, conflicting: wrapper can select production/arbitrary origin, hardcoded label D02; no simulator | Cameron C03/C05 / P0 |
| H-Q31 / 12 | Short-lived exact scoped one-use grant bound to complete authority/checkout/instrument | PI: `AuthorizationGrant/PreApproval` validation/hash binding T1; no issuance/storage/consume | Rishi R04+Cameron C04 / P0 |
| H-Q32 / 12 | Activation ordering/setup failure unusable | M: no prepare/bind/activate state machine; signup skips it | Rishi+Cameron / P0 |
| H-Q33 / 12,15 | Payment operations before side effects; stable provider idempotency | M: signup provider calls precede durable provider operation, no keys D03 | Rishi R11+Cameron C05 / P0 |
| H-Q34 / 12,15 | Unknown outcome reconciles; no new purchase/card on timeout | M: no reconciling state/query/operation; MCP retry wording D10 | Rishi+Cameron+Aditya / P0 |
| H-Q35 / 12 | Verified/grant/card/pending/authorized/settled meaning separate | PI: `PaymentResponse` documents permission, distinct `payment_result` T1; no durable operations or settlement input | Rishi+Cameron+Aditya / P0: additive mapping |
| H-Q36 / 12 | Actual Lithic ASA enrollment/schemas/signatures/live signed authorization | M for responder/ASA implementation; BC for actual program/configuration proof. Holder/card wrapper exists; public docs only T10 | Cameron C05 / P1; choose actual simulator until proven |
| H-Q37 / 12,15 | Pure deterministic ASA/local rail, no LLM/SQL/merchant network | M: no rail engine/handler; models/fixtures cannot prove hot path | Cameron C03/C04 / P0 |
| H-Q38 / 12,13,15 | Valkey atomic consume + original decision + event commit; revocation serialization | M: no Valkey client/scripts/handler/runtime; SQL authority atomicity is different | Cameron C04+Rishi R04/R05 / P0 |
| H-Q39 / 12,15 | Exact duplicate cached response; distinct parallel requests consume once | M: fixture expectations exist; no rail code/runner or real concurrent test | Cameron C04/C07 / P0 |
| H-Q40 / 12,19 | Altered duplicate fingerprint/unsupported request/authentication errors | M: schemas/fixtures only; provider raw signature/type handling absent | Cameron C05/C07 / P0 |
| H-Q41 / 12,15 | Grant expiry/old version/cardinality/reservation/invalidation across replicas | M: no fast-path implementation; R02 versions alone cannot enforce existing cards | Cameron+Rishi / P0 |
| H-Q42 / 12 | Once-only authorized card detail delivery; store only token/last4 | PI: direct card routes omit PAN T1; wrapper optional details return, no durable delivery marker/authorization flow | Rishi R04+Cameron C05 / P0 |
| H-Q43 / 12,17 | Relevant provider card pause/close/expiry/reconciliation | M: wrapper only create/get/transactions/headroom, no pause adapter | Cameron C09+Rishi R05/R11 / P0 if provider selected |
| H-Q44 / 12 | Actual decision source/rail/latency measured, ASA deadline met | M: validated `PaymentDecision.latency_ms` only; no authorization measurement | Cameron C09 / P1; no fabricated numbers |

#### Graph, MCP, recovery, investigation and reliability

| ID / MS | Requirement | Status / evidence and limit | Owner / priority / next work |
|---|---|---|---|
| H-Q45 / 10,11 | Real Strands shopper with genuine MCP tool invocation | IT for SDK wiring: `runs.py:run_shopper`, two real `MCPClient`s; T2 subprocess MCP/API/store stubs. Live model integration BC | Aditya A02/A03; no live claim |
| H-Q46 / 10 | Real SDK Graph / all required nodes / typed conditional edges | M: single Agent D05; local SDK GraphBuilder introspection T9 confirms capability | Aditya A11 / P0 |
| H-Q47 / 10 | Candidate/node/time/cost bounds and truthful terminal/exhaustion | M: threadpool max2 and test polling timeout do not bound workflow | Aditya A11/A12 / P0 |
| H-Q48 / 10 | Guardian explains linked genuine evidence without financial authority | IT for advisory evaluator: `guardian/__init__.py:evaluate`, known source filtering, strictness/model fallback T2; integrated incident UI absent | Aditya A05+Rishi R06 / P1 |
| H-Q49 / 10 | Source/SKU/checkout quarantine and fresh uncontaminated context | M: no containment controller; manual new-run tests D06 | Aditya A12 / P0 |
| H-Q50 / 10 | Autonomous unchanged-mandate recovery without human restart | M: S6 creates new run manually, no Graph D06 | Aditya A11/A12 + backend / P0 |
| H-Q51 / 10,12 | Recovery forbidden after hard decline, unknown outcome or authorization | M: no typed controller/operation gate; shopper controls whole tool sequence | Aditya+Rishi+Cameron / P0 |
| H-Q52 / 10,15 | Cooperative cancellation/recheck before every side effect | M: RunManager has no cancellation; SQL registration checks only at start | Aditya A12+Rishi R05 / P0 |
| H-Q53 / 10,15 | Durable progress/exclusions/leases/fencing, restart safety | PI: SQL initial registration persists T1; progress/final output only memory D09 | Rishi R11+Aditya / P0 |
| H-Q54 / 11 | Official MCP adapters, four finance + shopping tools; no direct fallback | IT: locked MCP 2.1.1 thin servers, schemas/bearer/clients, T2–T4; target store/API absent | Aditya retained; Rishi/Cameron implement targets |
| H-Q55 / 11,17 | Store-only browse/off-origin redirects reject; arbitrary internal URL denied | IT: `mcp-store/main.py:resolve_store_target/fetch_store_page`, T4 | Aditya; configured-origin trust/egress still Cameron |
| H-Q56 / 11,18 | MCP tool authority derives authenticated run scope; direct bypass equally enforced | PI: bearer forwarded/global Store MCP auth T3/T4; no run-scoped token or protected merchant/payment code | Aditya+Rishi+Cameron / P0 |
| H-Q57 / 10,14 | Original source hash, redacted snapshots and actual stored hash | IT for local/mock paths: `evidence/snapshots.py`, `hooks.py` T2/T4; real object storage BC | Aditya+Cameron; record real storage availability |
| H-Q58 / 5,10 | Genuine Akamai Strands tool-calling, provider fallback truth | BC: `llm.py:make_model` matched pairs/max_tokens/temp tests T2, two live tests deselected; provider label hardcoded D13 | Aditya A02 / P0: actual round trip/latency/failure evidence |

#### UI, Kill Switch, comprehensive SSE and persistence

| ID / MS | Requirement | Status / evidence and limit | Owner / priority / next work |
|---|---|---|---|
| H-Q59 / 3,16 | Mission Control/explicit human semantic confirmation/original intent visible | M: home auth card only; no purchase UI; signature API exists Q10 | Rishi R08 / P1 |
| H-Q60 / 16 | Live activity/Graph/clean recovery and readable comparison | M: web routes only home/profile/signin/signup, build T6; no flow panels | Rishi R08/R09+Aditya events / P1 |
| H-Q61 / 16 | Incident timeline/evidence inspection and genuine history/receipts | M: no read APIs or UI for complete proof chain | Rishi R06/R09/R10 / P1 |
| H-Q62 / 16 | Attack Lab changes listing only, not mandate/outcome | PI: malicious listing fixtures; no merchant toggle/UI | Cameron C02+Aditya A08+Rishi R09 / P0 |
| H-Q63 / 13 | Human-only durable idempotent Kill Switch owner endpoint/UI | M: per-mandate revoke only D07; no kill route/UI | Rishi R05 / P0 |
| H-Q64 / 13 | Atomic unused-grant invalidation, stop Graph/recovery; actual effective ack | M: no grants/atomic state/cancel | Cameron C04+Rishi R05+Aditya A12 / P0 |
| H-Q65 / 13 | Provider pause requested/confirmed/failed/unknown, no reversal claim | M: no pause lifecycle; prior authorization not demonstrated | Cameron C09+Rishi / P0 |
| H-Q66 / 13,19 | Kill races at every phase/restart/repeated clicks/cross-owner/failure | M: fixture rail race only; no handler/test runner/Graph Kill Switch tests | All within lane / P0 S7 |
| H-Q67 / 14,15 | Durable append-only state-event coupling and outbox | IT for mandates/registration: SQL audit_events/triggers/delivery records T1; financial coupling M | Rishi R06/R11+Cameron stream / P0 |
| H-Q68 / 14,18 | Authenticated provenance intake, sanitization/dedup/recovery | PI: strict shared input parsing T1 + agents disk outbox T2; no API intake, 404 deadletter D08 | Rishi R06+Aditya / P0 |
| H-Q69 / 14 | Comprehensive event taxonomy captures real auth/Graph/inference/all financial/recovery events | PI: mandate/run registration audit + before/after/source hooks only; missing expanded enums/emitters | Rishi contracts/R06+Aditya A13+Cameron rail / P0 |
| H-Q70 / 14 | Product SSE persisted id/event/data, heartbeat/reconnect/replay/resync | M on main; deployed activity OpenAPI advertises stream but source/authorized behavior UV (D12) | Rishi R06+Cameron integration / P0 |
| H-Q71 / 14,15 | Authorized history/cursors/stream ownership, refresh reconstruction | M on main; public activity endpoints unauth 401 only T10, authorized replay untested | Rishi / P0 |
| H-Q72 / 14,15 | SSE reconnect/browser refresh never starts new Graph or charge | M: no product streaming/client lifecycle or backend operation idempotency | Rishi+Aditya / P0 |
| H-Q73 / 14 | No secrets/PAN/private prompts/CoT in events, snapshots or logs | PI: model callbacks off/trace shared redaction T1/T2/T4; raw exception logging risk D13 and unbuilt endpoints | All / P0 for financial data; synthetic transport/log tests |
| H-Q74 / 14,16 | Actual agent/rail/recording labels; block-before-payment != provider decline | PI: live/scripted labels/tests exist; sandbox metadata can mislabel environment; full UI absent | All / P1 |
| H-Q75 / 14 | Source→tool→trusted checkout→decision incident linkage; cautious causality | PI: source/tool hashes and guardian known citations T2/T4; no persisted complete incident | Aditya+Rishi / P1 |
| H-Q76 / 15 | PostgreSQL durable domain and recoverable financial records | PI: identities/mandates/runs/audit T1; checkout/grant/operation/card-delivery/incident milestone tables absent | Rishi R03/R04/R06/R11 / P0 |
| H-Q77 / 15 | SQL/Valkey outages fail closed; no stale cached grants | PI: R02 DB 503/rollback/readiness T1; Valkey/financial tests M | Rishi+Cameron / P0 |
| H-Q78 / 15 | MCP/inference outage bounded fail-closed, no tool bypass | PI: MCP connection errors stop run T2; full Graph budgets/payment ambiguity M | Aditya / P0 |

#### Kubernetes, contracts, risk scope and acceptance

| ID / MS | Requirement | Status / evidence and limit | Owner / priority / next work |
|---|---|---|---|
| H-Q79 / 5,21 | Preserve actual LKE topology; no Compose replacement | IT for configuration preservation: six manifest files parse T9; live cluster state UV | Cameron C06 / P0; no deployment performed |
| H-Q80 / 5 | Repository-root API image copies runtime/shared/migrations | IU: Dockerfile/source inspected, deploy buildx selects root/api/Dockerfile; Docker daemon unavailable | Rishi image + Cameron build / P1: actual image import test |
| H-Q81 / 5,15 | Ready database/schema vs health liveness | IT local readiness negatives T1; YAML readyz/healthz T9; public both200 T10 | Cameron+Rishi; not full security readiness |
| H-Q82 / 5,15 | Persistent trace spool survives pod restart | IU: PVC 5Gi RWO /app/trace-spool declared; local restart outbox tests T2; actual mount UV | Cameron / P1: PVC/image rollout proof |
| H-Q83 / 6,15 | TLS, service auth, NetworkPolicy, scoped Secrets and safe public boundary | PI, conflicting: all four Python pods import full app-env D15; public HTTP/MCP rewrites; no NetworkPolicy/TLS manifests; actual mounted keys UV | Cameron+endpoint owners / P0 |
| H-Q84 / 5,15 | Database/Valkey availability and safe chosen runtime | PI: PostgreSQL local tests/public readiness; Valkey missing; no kubectl current context/kubeconfig | Cameron / P0: read-only resource proof/Valkey setup |
| H-Q85 / 5,21 | Shared installability and reproducible imports/builds | PI: namespace marker/source-copy/PYTHONPATH works T1–T4; shared/pyproject.toml absent | Cameron C01; service owners image imports / P1 |
| H-Q86 / 18,21 | Frozen contracts, OpenAPI mappings and generated frontend types | PI: R01 accepted/frozen; actual OpenAPI inspected; generated api-types missing; new Graph/unknown/event concepts not yet agreed | Rishi H01/H12 with all three / P0 |
| H-Q87 / 18,21 | Handoff callable valid/failure examples + actual tests + limits | PI: R01/R02 handoffs exist; merchant/rail/Graph/SSE handoffs not runnable | All named sender owners / P0 |
| H-Q88 / 17 | Core fraud/threat matrix covers prompt/tool poisoning, SKU/recurrence/budget/ownership/replay/kill/ambiguity/recovery | PI: YAML expectations and model/agent units only; D04/D06/D07 missing enforcement; no claim “most fraud” | Rishi/Cameron/Aditya / P0; Q19–Q78 |
| H-Q89 / 17 | Compromised session/stolen data/disputes have bounded partial claims | PI: JWT validation/redaction, no server session revocation/reauth or payment disputes; no broad protection proof | Cameron+Rishi / P1; disclose partial scope |
| H-Q90 / 17 | Dishonest merchant/fulfillment/counterfeits/ACH/full chargeback controls outside guarantee | IT as documented scope only: 23.4/26.7 limits retained; no corresponding capability claimed | All; future work, not security coverage |
| H-Q91 / 19 | Unit/mock integration/security matrix distinct from live provider/model E2E | IT audit labeling: T1–T10 below; rail runner missing, six E2E skipped, two live inference deselected | All; cannot mark E2E complete |
| H-Q92 / 19 | S1 actual legitimate charger authorization/receipt | M: test exists but skipped T8, merchant/payment absent | All / P0 |
| H-Q93 / 19 | Combined live S2→S6 attack/block/quarantine/automatic unchanged-authority recovery | M: manual two-run test skipped T8; no Graph/live injection proof | Aditya+Rishi+Cameron / P0 |
| H-Q94 / 19 | S3 exact boundary/tax/shipping overspend no instrument | M runtime: fixture cases present, E2E skipped | Rishi+Cameron / P0 |
| H-Q95 / 19 | S4 incomplete/untrusted/stale evidence no grant | M runtime: strict shapes/fixtures only; E2E skipped | Rishi+Cameron / P0 |
| H-Q96 / 19 | S5 expiry/replay/parallel attempts/altered duplicates | M runtime: YAML/one gated negative test; no atomic handler | Cameron+Rishi+Aditya / P0 |
| H-Q97 / 19 | S7 master Kill Switch storyline | M: no current E2E Kill Switch test/implementation | All / P0 |
| H-Q98 / 19 | Faults: direct bypass, provider lost response/DB failure, worker restart, model outage, malformed findings | PI: R02 rollback/signature/advisory model tests; financial crash/reconciliation/bypass tests absent | All / P0 |
| H-Q99 / 20 | Safe reset, no grant reuse/history deletion, labeled recorded fallback | PI: live/scripted distinct mandate/token/lane docs/tests; actual reset/rehearsal UV; manual recovery outdated | Aditya+Cameron+Rishi / P1 |
| H-Q100 / 22,24,26 | Dependency order, all critical differentiators retained, truthful completion | PI: synchronized docs now require them, code incomplete; no claim of MVP completion | All; dependency tasks below |

### Tests, builds and deployed observations

These results were produced during this audit, not copied from historical handoffs. No provider credentials were used, no human session was created/modified, and no shared data was changed. Normal fixture startup/error logs in T1 are deliberate failure-path tests, followed by exit 0 / OK. Disposable PostgreSQL bound localhost:55432, database `leash_test_r02`, per-suite generated schema; tests refuse non-local/non-test database names.

| Evidence ID | Command / environment | Actual result | What it establishes / does not |
|---|---|---|---|
| T1 | `LEASH_TEST_DATABASE_URL=postgresql://rkmadhavan109@127.0.0.1:55432/leash_test_r02`; `api/.venv/Scripts/python.exe -m unittest discover -s api/tests -q` | **90 tests, OK**, 13.306s; includes 19 real PostgreSQL tests, 9 card authority/wrapper tests and contract/mock tests | Signed/owned immutable authority, migration/SQL audit/races, card route denial/redaction. Signup provider is mocked; no ASA, verified payment, Kill Switch or Graph |
| T2 | From services/agents: venv `python -m pytest -m 'not live_inference' -q --basetemp .venv/audit-test-tmp`, uv on PATH | **130 passed, 2 deselected**, 53.30s | Hook/redaction/advisory guardian/mode registration/outbox and actual SDK subprocess MCP wiring with mocked API/store/model. No live inference or complete security chain |
| T3 | From services/mcp-leash: venv `python -m pytest -q --basetemp .venv/audit-test-tmp` | **33 passed**, 11.62s | Thin financial MCP schema/auth-forwarding/mocked HTTP behavior; no live grant |
| T4 | From services/mcp-store: same pytest command | **40 passed**, 11.97s | Store-only browsing/auth/evidence/snapshot redaction and mocked checkout forwarding; not trusted merchant charge enforcement |
| T5 | agents venv Ruff `check --select E4,E7,E9,F api db` | **All checks passed** | Python correctness lint only, not full style/security enforcement |
| T6 | From web: `pnpm build` | **Passed**, compiled/TypeScript/static generation; routes `/`, `/profile`, `/signin`, `/signup` | Auth/profile web builds; no product UI functionality. Build reads existing `.env.local`; secret contents were not inspected/printed |
| T7 | From web: `pnpm lint` | **Failed, exit1**, one `react-hooks/set-state-in-effect` at profile/page.tsx:38 | Existing frontend issue D14; left unchanged under documentation-only authorization |
| T8 | agents venv `python -m pytest tests/e2e -q -rs --basetemp services/agents/.venv/audit-e2e-tmp` | **6 skipped**, `LEASH_E2E=1` required | Collection works; no scenario passed. Did not enable destructive/live scenario setup |
| T9 | Installed SDK introspection; PyYAML parse of six K8s manifests and decision fixtures; WSL Bash syntax | Strands **1.59.0**, MCP **2.1.1**; GraphBuilder conditional edges/limit APIs available; **11 manifest documents parse**; fixture YAML parse; direct Bash fails CRLF; LF-normalized both scripts exit0 | Static configuration/SDK capability only. Policy runner/store/webhook absent; no Docker image/cluster apply |
| T10 | Read-only unauthenticated HTTP GET to public `/backend/health`, `/readyz`, `/openapi.json`, `/activity`, `/activity/stream`; official docs | Health/readiness **200**; activity reads **401**; deployed extra routes absent on main. Official ASA deadline/HMAC/sandbox and Graph API checked | Public service reachable and unauthorized activity refused. No authorized SSE replay/coverage, image SHA, live auth/provider or financial behavior proof |
| T11 | Documentation diff/whitespace, local links/anchors, balanced fences, requirement/task/section consistency, frozen-file comparison and final Git status | **Passed**: 100 Q01–Q100 rows; sections 1–26 retained; local links/anchors/fences valid; frozen models/events identical to HEAD; only four authorized docs changed, main/HEAD unchanged | Documentation alignment only; no application requirement is completed by these checks |

Docker `info` failed because the Docker Desktop Linux engine pipe is absent. No image build/Compose boot was performed; Compose is optional and absent. `kubectl config current-context` reports no context and repository credential file is absent; no Secrets, PVC status, NetworkPolicy, image digest or live resource inspection occurred. Kubernetes YAML parsing is not an API-server validation/rollout. Decision YAML has expected verifier/merchant/rail/handler/e2e cases but no runner; no rail decision-matrix execution can be claimed.

Authoritative references: [Python Strands Graph API](https://strandsagents.com/docs/api/python/strands.multiagent.graph/) confirms conditional edges and execution controls; installed version introspection is the compatibility evidence. [Lithic ASA](https://docs.lithic.com/docs/auth-stream-access-asa) confirms sandbox enrollment, request authenticity setup, six-second deadline/recommended three-second response and retries; it does not prove this program is enrolled. A first attempted legacy Graph documentation URL returned 404; the current official API page was used instead.

### Conflicts reconciled and remaining decisions

| Previous understanding / master concept | Resolution in canonical docs | Implementation or decision still needed |
|---|---|---|
| Single Strands shopper considered sufficient orchestration | Actual SDK Graph mandatory, A11; separate backend financial source of truth | Aditya Graph; Rishi typed backend status |
| Second manual run or optional recovery | Single-Graph bounded clean containment/recovery mandatory A12; manual fixture separate | Candidate/source exclusions and safe operation gate |
| Six scenarios with recovery as separate S6 | Preserve S1–S6 IDs; combine S2/S6 for master attack/recovery storyline, add S7 Kill Switch | Aditya E2E/demo update |
| Narrow tool traces or MCP event-stream counted as live UI | Full persisted product SSE + state/history/replay and lifecycle emitters R06/A13 | New agreed event concepts + main/deployed activity reconciliation |
| Kill Switch deferred to hardening / provider pause equivalent | R05/C04/A12 before grants; provider pause tracked separately | Tested SQL/Valkey fail-closed protocol; human UI |
| Signup sandbox card harmless because no PAN returned | Usable card before verification conflicts; metadata protection alone insufficient | D01 owner fixes and existing instrument inventory/reconciliation |
| Card issuance considered complete payment integration | Card, grant, authorization and settlement distinct; local rail must be real | Merchant/rail/ASA and operation state |
| Compose full boot required deployment gate | Existing Kubernetes preserved; Compose optional local | LKE source/image, runtime auth/TLS/Valkey/PVC evidence |
| Cameron choosing Clerk/Auth.js vs existing custom auth | Cameron leads provider decision; Rishi retains API/schema/web ownership, adapter/migration preserves UUID/LEASH identity | Confirm retain equivalent vs provider migration; obtain unpublished deployed auth/activity source |
| Static scoped agent token deemed complete | Owner/mode bootstrap useful; run/mandate/version/tool/audience/expiry scope still required | R12/Adi scope enforcement, no unrestricted human token in model |
| Master's schema/events/routes/SKU names differ | Examples mapped to frozen R01; no rename/application-contract edits | Additive Graph/reconciliation/event mapping; fees/discounts policy, all-three contract review |
| Public MCP vs prior internal-only request | Desired default internal service + auth; optional external HTTPS client exposure requires explicit team resolution | Cameron/Rishi/Adi scope/routing handoff; no audit deploy change |
| Master's H01–H10 vs existing plan H01–H13 | Preserve plan IDs; crosswalk in spec26.6 | Callable handoffs, not renumbered assumptions |

Human/configuration decisions still outstanding: selected auth equivalent/provider and stable identity migration; documented external MCP clients if any; concrete candidate/node/time/cost limits; trusted merchant taxonomy/auth/session/freeze protocol and exact fees/discounts treatment; SQL/Valkey activation/invalidation ordering, idempotency scope/retention and worker fencing; simulator vs verified Lithic program/ASA/HMAC/HTTPS; deployed source/image and actual agent bindings/Secrets/PVC; Akamai tool-call/provider evidence; Object Storage availability or durable labeled local evidence. Existing environment names are not capability proof. No missing configuration is permission to relax enforcement.

### Dependency-ordered implementation priorities and human handoffs

1. **Rishi + Cameron — close D01–D03/D15 and reconcile live source first.** Rishi owns signup/API operation state; Cameron owns scoped pod Secrets, sandbox-only provider client/idempotency/status and current deployment/auth/activity source. Humans choose auth continuity; agents inspect compatible incoming work before adding another system. Gate all usable instrument setup on verified purchase; retain unknown provider operation correlation.
2. **All three — small H01/H03–H08 contract handoffs.** Agree typed Graph/backend phases, safe financial operation/status/unknown results, run-scoped credentials, event taxonomy/cursor, canonical store/freeze/binding and atomic invalidation protocol. Preserve existing names; any frozen-file additions use the dedicated contract-only PR. Human reviews decide boundaries; lane agents produce valid/failure examples and tests.
3. **Cameron C02–C04 + Rishi R03/R11 — real trusted merchant and financial core.** Canonical safe/unsafe equal-price fixtures plus safe alternative, authenticated owner/revision retrieval, pure deterministic verifier, operation/attempt persistence, scope reservation/fencing, atomic Valkey local rail with real consume/cache/event commit. Prove direct-charge substitution, concurrency/replay/outages before usable grants.
4. **Rishi R04/R05 + Cameron C04/C09 + Aditya A12 — grants and mandatory Kill Switch.** Protected binding/activation order, exact one-use expiry, human cancellation/effective revocation protocol and actual provider pause outcomes. Test all revocation/authorization races and unknown outcomes; no claim reversal of committed authorization.
5. **Rishi R06/R12 + Aditya A04/A13 — durable evidence/SSE and identities.** Integrate compatible deployed activity code only after source review; authenticated provenance intake/dedup/outbox replay, complete lifecycle capture, authorized cursor history/stream, stable auth adapter and ephemeral scopes. Actual UI/client reconnect must not launch work. Avoid writing over Cameron's active auth integration.
6. **Aditya A11/A12 + backend consumers — actual bounded Graph recovery.** Shopper/independent verifier/guardian/deterministic containment/payment/terminal nodes; fresh contexts; no side effects after cancellation/unknown/success; exclusive worker state. Keep unit policy tests separate from genuine Akamai model/MCP proof; capture the real attack then safe alternative without manual restart.
7. **Cameron C05/C06/C09 — selected rail and existing LKE integration.** Restrict shared app-env imports immediately (D15), keeping backend authority keys out of agent/MCP pods. Sandbox ASA only after actual enrollment/HMAC/HTTPS/signed tests; otherwise label working local policy adapter. Configure TLS/private routing/service auth/Valkey/volumes, verify image imports/source digest and persist/restart behavior. Do not redo merged API root build/readiness/PVC declarations as if missing.
8. **Rishi R07–R10 — working product UI and lint correction.** Human confirmation, original intent, Graph/recovery status, live sanitized activity, comparison, evidence/history/receipt, Attack Lab and prominent Kill Switch. Derive status from backend and generate types from agreed OpenAPI; accurately label permission/authorization/settlement and actual rail.
9. **Aditya A07/A10 + all owners — acceptance and timed rehearsal.** Original S1–S6 plus S7, automatic combined S2→S6, provider ambiguity/restart/direct-bypass/atomic race/SSE replay scenarios on chosen runtime. Actual positive purchase + actual live manipulated attempt + recovery + Kill Switch. Record rail/provider/source/latency and <=3-minute stopwatch; labeled recordings only for disclosed outage fallback.

Tasks can proceed independently within lanes once their listed interfaces are supplied, but no owner should call a dependent task complete from a stub. None of these owner actions was executed as application work in this audit.

### Documentation changes and remaining demo risk

Modified [AGENTS.md](../AGENTS.md): added master precedence, current implementation boundary, mandatory Graph/recovery/Kill Switch/SSE/side-effect invariants, Kubernetes/auth coordination and audit-only authorization. Preserved tree, lanes and frozen contracts.

Modified [LEASH_SPEC.md](LEASH_SPEC.md): retained historical directive/contracts and added normative section26 with real Graph flow, recovery eligibility/clean context/bounds, durable financial state/correlation/reconciliation, Kill Switch races, event taxonomy/cursor mapping, identity/K8s handoffs, threat limits and expanded acceptance/demo requirements. Explicitly distinguishes historical snapshots and current code.

Modified [Leash-build-plan.md](../Leash-build-plan.md): synchronized desired demo, actual baseline, owner tasks R05/R06/R11/R12/A11–A13, provider/runtime handoffs, gates and original scenario-ID compatibility plus S7. Moved revocation/reconciliation before usable grants, made automatic Graph recovery/core SSE mandatory, and removed Compose as a deployment requirement.

Created this audit: full 100-row traceability matrix, evidence/severity/owner fixes, actual test/build results, deployed-source drift, conflicts and dependency order. No frozen `models.py`/`events.py` or teammates' application code changed. Docs are uncommitted on main for review; this is not an approved deployment or finished MVP.

Before a truthful three-minute live demo, all P0 financial/Graph/recovery/Kill Switch/evidence boundaries still need runnable enforcement and selected-runtime proof. Existing passing tests are valuable foundations, while live inference, signed Lithic ASA, atomic rail, automatic recovery, authorized comprehensive SSE and full E2E remain untested/missing. The web lint failure and deployed source discrepancy remain unresolved. Do not claim live card-network decline for a pre-payment rejection, settled payment for an authorization, universal fraud prevention, or a recording as current live behavior.
