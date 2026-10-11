# LEASH build plan

Updated October 10, 2026. Execution guide for **Rishi, Cameron, Aditya, and their coding agents**. This replaces the earlier hotel/gift-card implementation plan. It is a plan, not a record of completed work.

**Master alignment revision:** Rishi's October 10 master specification is the desired-state baseline. [Spec section 26](docs/LEASH_SPEC.md#26-master-alignment-baseline--october-10-2026) resolves previous assumptions; [the alignment audit](docs/LEASH_ALIGNMENT_AUDIT.md) preserves baseline evidence and records the implementation follow-up. Real Strands Graph, automatic clean recovery, comprehensive persisted SSE and authenticated human Kill Switch are mandatory MVP work. Kubernetes is the selected existing runtime; Compose is optional local convenience. Preserve task/handoff IDs and frozen R01 contracts. Rishi subsequently authorized implementation, testing, documentation sync and pushing on main; lane ownership and frozen-contract review remain unchanged.

Read [AGENTS.md](AGENTS.md) for coding rules, the existing/planned repository tree, and path ownership. Read [docs/LEASH_SPEC.md](docs/LEASH_SPEC.md) for product/security requirements and detailed contracts. This file answers **who does what, in which order, what must be handed off, and what proves it works**. A direction/ownership change updates all three documents together. Product requirements come from the spec; path ownership comes from AGENTS; this plan cannot quietly override either.

## The result everyone is building

The user confirms: **“Buy a USB-C laptop charger for under $40. No subscriptions.”** A poisoned listing redirects a genuine Strands shopper toward an unrelated $29.99 subscription at the **same merchant, 2999-cent amount and USD currency** as the valid charger. Independent canonical checkout facts expose the mismatch; deterministic enforcement blocks it before payment. **Real Strands Graph** investigates, quarantines the source/candidate and automatically starts clean shopping for a compliant alternative under unchanged authority. The charger receives a real labeled authorization. Full persisted SSE explains the flow, and human Kill Switch stops a separate fresh/unspent workflow. Total must be at most 3999 cents, including required tax/shipping/fees.

The proof chain is: **confirmed intent -> actual agent/tool behavior -> independently verified checkout -> scoped one-use grant -> real backend authorization -> persistent, evidence-linked UI**. Do not replace any link with an approving stub, agent-authored cart, hardcoded outcome, or React-only animation. The controlled merchant must bind its protected charge operation to the exact verified checkout; ASA metadata alone does not prove SKU identity.

## Current checkout and planned structure

**Current implementation follow-up:** integrates Cameron's activity/local-rail changes (`674ef75`) and ASA adapter (`a9e8cba`) with Rishi's authorized fixes. Signup creates identity only; provider access is sandbox-only. Registered agent provenance, persisted owner-scoped history/SSE through Next, deterministic checkout policy, strict local rail with atomic one-use consumption/event caching, durable rail-event delivery and human stop/provider-pause intents are implemented and locally tested. **Not a complete or deployed MVP:** trusted merchant retrieval/protected charge binding, product payment routes/issuance/reconciliation, real Strands Graph/automatic recovery/cooperative stop, short-lived run scopes and full workflow/UI remain unfinished. Frozen R01 models/events and ownership are unchanged. See [the current handoff](api/alignment-fixes-handoff.md) and [audit](docs/LEASH_ALIGNMENT_AUDIT.md).

**Historical R01 integration snapshot:**

R01 baseline review: incorporated main at `1818a43` includes Cameron's build/LKE/PostgreSQL provisioning and Aditya's `2e6f940` agents/MCP/guardian/provenance/tests. R01 incorporates main with the AGENTS.md conflict resolved, adds `AgentRunRegistration`, and refreshes peer captures; all 52 contract tests pass. API now has JWT signup/login/me and a PostgreSQL users table from Cameron's PR #5; web has signup/signin/profile. R02 now implements mandate/run routes in R02; payments remain pending. [api/agent-interface-handoff.md](api/agent-interface-handoff.md) records exact interfaces, peer-suite results and remaining reconciliation. Remaining interface coordination, installable shared package/API image wiring, application persistence/routes, merchant/rail/Valkey, Compose and live acceptance remain pending. Spec section 21 retains the original inspection snapshot.

Keep the existing backend in `api/`; `services/api/` is a reserved alternative. The annotated tree is in [AGENTS.md](AGENTS.md#repository-tree). Current deployment lives in `k8s/` and `scripts/`. Current ports: API 8000, web 3000, agents local 8001/LKE 8000, Leash MCP 8002 and Store MCP 8003. Merchant/rail ports are not frozen and must not collide with Store MCP. API supports `/health` and `/healthz` liveness plus `/readyz` readiness.

No integrations or account credentials are assumed ready. Original and current file-status observations are snapshots; refresh them before starting code. Leave unrelated working-tree changes intact.

## Ownership — identical to AGENTS.md

Each person's coding agent normally edits that person's paths. Rishi explicitly authorized narrow cross-lane integration/security fixes in this follow-up; this does not transfer ownership. Cross-lane work is an interface handoff; the owner makes the edit. Existing ownership is retained. Shared package metadata/marker files are assigned to Cameron so installability has an explicit owner; domain contracts remain Rishi's.
| Path | Owner |
|---|---|
| `infra/`, `k8s/`, `scripts/`, `docker-compose.yml`, `.env.example`, `.github/`, root `pyproject.toml` | Cameron |
| `services/webhook/`, `services/store/`, `tests/test_decision_cases.py` | Cameron |
| `shared/leash_shared/lithic.py` | Cameron |
| `shared/pyproject.toml`, `shared/leash_shared/__init__.py` | Cameron |
| `api/`, `services/api/`, `db/`, `web/` | Rishi |
| `shared/leash_shared/models.py`, `shared/leash_shared/events.py` | Rishi; frozen after joint agreement |
| `services/agents/`, `services/mcp-leash/`, `services/mcp-store/` | Aditya |
| `shared/leash_shared/llm.py` | Aditya |
| `tests/decision_cases.yaml`, `tests/e2e/`, `docs/demo-script.md` | Aditya |
| `AGENTS.md`, `Leash-build-plan.md`, `README.md`, `docs/LEASH_SPEC.md` | Everyone, through small documentation PRs |

## How each human and coding agent works

The human selects the lane/task, reviews security/interface choices, supplies account access through secrets, approves shared-contract changes, and accepts the task only after seeing runnable evidence. The coding agent inspects current files, implements the selected task inside that lane, writes meaningful tests, and reports the actual outcome/dependency. A coding agent does not approve purchase authority on the human's behalf or silently acquire integration capabilities.

Every coding agent starts by reading all three direction documents, nested instructions present in its lane, current Git status and relevant installed SDK guides. Select the earliest unfinished task below whose prerequisites are satisfied. Do useful independent work if another lane's interface is pending; use labeled fixtures matching the agreed contract for isolated tests, but the demo path must fail closed without real verification. Do not redefine a missing interface or edit another lane to get past a blocker.

Use `<name>/<topic>` branches, small reviewable changes and continuous integration; pull main before starting new implementation when safe for existing local work. Shared `models.py` and `events.py` are jointly agreed first, then frozen. Later changes require a dedicated PR touching only those two contracts with all three humans' agreement. Generated web types come from OpenAPI, never separate handwritten contracts. Agents report handoff needs to their human; messages to teammates require human authorization.

A task report includes: task ID, changed paths, implemented behavior, commands/results, next consumer/handoff, unresolved dependency with owner, and whether results are local simulator, Lithic sandbox, fixture-driven or genuine agent execution. Never mark a task done merely because code was written or a dependency installed.

## Gate G0 — first 45 minutes together: freeze interfaces

**DRI: Rishi. Reviewers: Cameron and Aditya.** This is the first work now, not a claim that the old 2:30 PM checkpoint was met. Rishi drafts the domain contracts; Cameron reviews trusted checkout/rail/atomicity; Aditya reviews tools/traces/investigation. Each implements only their files after review.

- [x] Rishi accepted the R01 baseline fields/enums for PurchaseMandate, proposal Cart, AgentRun/Trace, canonical product/CheckoutSnapshot, CheckoutVerification, AuthorizationGrant, AuthorizationAttempt/PaymentDecision, SecurityIncident, AuditEvent. Use spec section 23's `_cents` mapping, UTC, canonical payload hashing, immutable confirmed versions, exact totals/currency and sanitized evidence.
- [ ] Confirm human versus agent auth/session boundaries, merchant source authentication, configured source registry, and checkout ownership. CORS or agent claims cannot substitute for auth.
- [ ] Confirm quantity/purchase cardinality and comparator: the singular request defaults to one successful checkout, quantity one; “under $40” has maximum 3999 cents unless the human confirms otherwise. A block consumes no purchase authority. Live demo sessions/reset behavior must respect consumed scope.
- [ ] Agree checkout revision freeze, trusted checkout retrieval, grant/instrument binding, protected merchant charge operation and activation order. A grant becomes usable only after all verification and required merchant correlation binding succeed; failed setup revokes any partial grant and never approves.
- [ ] Agree Valkey schemas/atomic operations for authority revocation, kill switch, scope reservation, grant issuance/consumption, idempotent event identity/fingerprint, cached response retention and audit stream commit. API owns durable writes; webhook network I/O is Valkey only.
- [ ] Agree route/request/response/error examples in spec section 23.6; choose exact route names without arbitrary renaming. Health and JWT auth routes exist; LEASH purchase routes remain pending. Agree run API location, SSE event IDs/resume/auth, incident/history queries and receipt format.
- [ ] Agree service packaging/dependencies: Cameron owns root workspace/ruff config and shared package installability; each service owner owns its project dependencies/Dockerfile. Specify how owners install/import the shared package without duplicate models.
- [ ] Agree fixtures: canonical charger and canonical subscription both total 2999 cents, same merchant/currency; the attack changes only listing text/agent behavior. Add over-budget, missing-evidence, expiry/replay and recovery fixtures. Adversarial listing text cannot edit canonical records.
- [ ] Agree selected local rail interface first; Cameron reports Lithic/Akamai capability checks without printing secrets. Genuine Strands/Akamai round-trip is separately verified by Aditya.
- [x] Rishi authorized the initial `models.py`/`events.py` baseline after peer compatibility review. Separate all-three approval messages are not claimed.
- [ ] Publish purchase-route OpenAPI and verify packaged runtime imports; remaining checkout/rail protocols still require owner coordination.

**Exit evidence:** all three have reviewed identical model/event schemas and interface examples; source trust, payment correlation and atomicity are explicit; task owners know the next handoffs. Contracts being documented is not an implemented security mechanism.

## Rishi — product backend, durable state and frontend

**Human responsibilities:** lead G0 and cross-lane product integration; review the confirmed-intent fields and user consent flow; agree source/rail protocols with Cameron; validate the UI explains actual enforcement and provider state; accept G1/G3 product integration and final application readiness. Coordinate contract PRs with both teammates.

**Coding agent lane:** `api/`, `db/`, `web/`, Rishi's frozen shared files and shared direction documents. Start with R01/R02, then verifier/payment/persistence before polishing the UI. Do not move the starter, implement Cameron's provider/merchant/infra files, or put user/provider secrets in frontend code.

| ID | Deliverable and paths | Depends on / handoff | Evidence required to finish |
|---|---|---|---|
| R01 | Agreed validated domain contracts and canonical JSON/hash helpers in `shared/leash_shared/models.py`; event schemas/publish helper in `events.py` | G0; Cameron packaging, all-three review; everyone consumes | Typed semantic authority, checkout/grant/decision/trace contracts, exact cents/UTC, hash-change vectors, shared import works |
| R02 | SQL migrations in `db/`; persistence/session/auth wiring in `api/`; mandate propose/confirm/read/replacement/revoke and registered agent-run context | R01, C01 runtime/data; Aditya consumes mandate and `/agent-runs` routes | Explicit human confirmation/signature association, immutable history, agent forbidden on privileged routes, expiry/cross-session tests; run owner/version/hash/mode bound before traces |
| R03 | Independent checkout verifier in `api/` and tests in `api/tests/` | R01, C02 canonical merchant interface; hand verified evidence to R04 | Server fetch/auth, trusted typed items/totals/revision, every constraint, unknown/missing evidence fail closed, agent cart never proof |
| R04 | Payment proposal/status, idempotent grant/instrument issuance, correlation and reconciliation in `api/` | R02/R03/R11, C03/C04 protocol and C02 binding; MCP/Graph consumes | Verified current authority only; exact scope; persist operation before side effect; uncertain setup unusable; once-only details; no new purchase while outcome unknown |
| R05 | Mandatory human Kill Switch, cancellation and replacement/revoke invalidation in `api/`, `db/`, `web/` | R02; C04 coordinated atomic protocol before grants; A12 cancellation; C09 actual provider controls | Owner-only idempotent request; effective unused-grant invalidation serialized with approval; stop runs/recovery; survive restart; report provider pause separately and preserve committed authorizations |
| R11 | Durable attempts/payment operations, idempotency, resumable run state and leases/fencing in `api/`, `db/` | R02; H05/H06 with Cameron; A11/A12 consumes | Record operation before external write; ambiguous result -> reconciliation; stale worker/repeated node cannot issue/charge twice; authorized != settled |
| R12 | Stable auth-provider adapter and short-lived run/mandate/version/tool/audience credentials | Cameron leads H03 provider decision; R02 identity mapping retained; Aditya MCP enforces scopes | Backend verified human session; no cross-owner reads/SSE; agent expiry/audience/tool negatives; migrate without orphaning history or competing auth |
| R06 | Comprehensive durable intake/SSE/history/incident reads for auth, mandates, inference, Graph, MCP, browsing, verification, guardian, recovery, grants/cards, rail, reconciliation and Kill Switch | R01 event mapping; A04/A13 emitters; C04 committed rail stream; R11 state/outbox | Commit before ack; authorized ordered replay/heartbeat/resync; dedup; browser reconnect never starts run; sanitized real events, refresh reconstruction and source/latency truth |
| R07 | Shared OpenAPI-generated `web/src/lib/api-types.ts`, typed API client and server-side user/session auth | R02/R04/R06 agreed OpenAPI | Types match contracts; no secrets in `NEXT_PUBLIC_*`; no duplicate handwritten schema; meaningful errors |
| R08 | Mission Control + explicit mandate confirmation + purchase comparison in `web/` | R07; can build layout with labeled isolated fixtures first | Original instruction stays visible; constraints vs trusted attempted facts; grant/authorization/paid distinction; actual consent and backend results |
| R09 | Real activity, incident timeline, transaction history and Attack Lab in `web/` | R06/R08, A02/A04, C02 attack scenario API | Actual streamed tool/state events, source inspection, reload persistence, actual provider/source/latency; attack never changes mandate/outcome |
| R10 | Receipts/evidence chain, empty/error/loading states, service Dockerfile/README and final integration checks | R05–R09, C06 deployment, A07 e2e | Readable signed/hash-linked chain without overstated guarantees, provider failure never success, deployed positive/block/recovery, usable phone/big-screen UI |

**R01 implementation status:** models, hashing, event publishing and contract tests are implemented as the initial accepted integration baseline. The handoff documents the mandatory `checkout_id` on payment proposals, the nested grant on PreApproval, nullable guardian model, the 15 required verification checks, and the `event` stream field. Contract tests pass; C01 shared package/runtime installation remain open. R02 signing/auth/persistence and R03 independent verification are separate work, not completed by parsing a valid record.

**Historical pre-merge integrated review:** the `9edadab` baseline includes R01, Cameron's deployment/auth work, and Aditya's merged two-service MCP implementation. R02 supplies signed mandate lifecycle, identity mapping, immutable SQL authority and registered runs. [The handoff](api/r02-handoff.md) records validation and deployment commands. Both MCP services are owned by Aditya, the merchant/deployment by Cameron; shopping tools use Store MCP and the demo is live-first. Latest separate live/scripted credentials on Aditya's branch need to merge, be supplied through Secrets, and be bound by the API operator to the same intended human with distinct mandates. Cameron's API root-context/readiness change and persistent trace volume remain pending. Rishi authorized merging R02 before that deployment follow-up. Payments, verifier, provenance intake, merchant/rail/Valkey and genuine live acceptance remain pending. Historical R01 peer-suite results are retained in the interface handoff; future frozen-contract changes require dedicated coordinated review.

**Rishi agent starting prompt:** “Read AGENTS.md, Leash-build-plan.md and docs/LEASH_SPEC.md. Work as Rishi's coding agent. Inspect current files and Git status, then implement the earliest unfinished R-task with satisfied prerequisites. Stay in the Rishi lane. Lead shared contracts through all-three review; do not treat an agent cart or positive guardian opinion as payment authority. Preserve the current api/ starter and fail closed until independent checkout and correlation are complete. Return task ID, code/tests, handoff and real blockers.”

### Current task status — implementation follow-up

| Task | Current result | Remaining completion gate |
|---|---|---|
| R01/R02 | Retained and tested; frozen models/events unchanged | Hosted operator bindings/configuration still unverified |
| R03 | Tested pure policy enforces all 15 checks | Authenticated independent merchant fetch, persistence/routes and protected checkout freeze |
| R04/R11 | Product payment/issuance/reconciliation absent; durable idempotent PAUSE intents exist only | Persist payment operation before any issuance/charge; exact trusted binding, provider idempotency and unknown-outcome query |
| R05 | Human durable stop, revoked SQL authority, cancellation records, atomic local rail latch and actual provider-pause outcome handling tested | Aditya cooperative cancellation, all-phase races, individual replacement/revoke propagation, live provider proof; no resume-old-authority route |
| R06 | Provenance 201/409/422, ordered owner SSE through Next and durable rail-stream relay tested | Full Graph/inference/verification/recovery/reconciliation emitters, incident/source/history UI and agreed additive contracts |
| R08–R10 | Identity/profile activity/stop UI build and lint pass | Human purchase confirmation, Mission Control, comparison, incident timeline, receipt and Attack Lab |
| C03/C04 | Strict local rail, immutable grants, scope cap, concurrency/replay/expiry/stop Lua tested with real Redis | Complete trusted merchant/SQL activation/replacement invalidation protocol, actual Valkey8/PVC restart tests |
| C05/C09 | Sandbox guard, mandatory signed ASA, safe non-spending card controls retained | ASA checkout correlation is absent: no provider approval claim. Issuance/lifecycle, real enrollment/HMAC/HTTPS and signed live integration proof remain |
| C06 | Scoped Secret keys, financial NetworkPolicy and Valkey AOF/PVC declarations | Cameron deploys/verifies TLS, images, CNI policy, Secrets and volumes; no rollout performed here |
| A11/A12/A13 | Still required and unfinished | Real bounded Graph, clean autonomous recovery, control polling/fencing, complete genuine events and live Akamai/injection proof |

See [api/alignment-fixes-handoff.md](api/alignment-fixes-handoff.md) for exact request examples and owner actions. Do not rebuild another copy of the working policy or relax missing evidence to get a demo green.

## Cameron — trusted merchant, deterministic payment rail and infrastructure

**Human responsibilities:** obtain/verify Lithic and Akamai account capabilities, public URLs/TLS and managed data connectivity; configure secrets server-side; review source trust, provider wire/signature behavior, correlation and atomic grant enforcement with Rishi; select the demonstrated rail based on evidence; own deployment/latency readiness. Do not promise integrations based only on an API key or sign-up.

**Coding agent lane:** Cameron's infra/workspace/packaging, merchant/webhook/SDK wrapper and policy runner paths. Build the controlled merchant plus local rail early; Lithic capability checks and deployment proceed independently. Do not change Rishi's domain contracts/migrations/API or Aditya's fixtures/tools.

| ID | Deliverable and paths | Depends on / handoff | Evidence required to finish |
|---|---|---|---|
| C01 | Shared installability/workspace config, `.env.example`, Valkey/data wiring on existing Kubernetes; optional local Compose | G0 packaging/config; service owners provide Dockerfiles | Imports and selected K8s runtime verified; no secrets in templates; actual probes/data; Compose absence does not block LKE acceptance |
| C02 | `services/store/` canonical catalog/checkouts, listing attack toggle, protected binding/charge API and tests | R01 schemas, G0 trust/correlation; hand to R03/A02 | Same merchant/2999-cent charger+subscription; malicious text cannot alter catalog; auth/session/revision checks; charger grant cannot charge subscription |
| C03 | Pure payment decision engine in `services/webhook/decide.py` and distinct local adapter | R01, G0 domain rules; A01 fixtures | Genuine approve/decline from grant/evidence/state, exact total/currency/expiry, supported request types, no LLM/SQL/merchant calls |
| C04 | Valkey atomic grant/scope/authority/invalidation/consumption/idempotency/audit protocol and handler tests | C03; agree API writes with R04/R05, events with R06 | Distinct concurrent attempts consume once; identical duplicate response; altered duplicate payload errors; cached state/revocation/commit failures never new approval |
| C05 | Sandbox-only provider wrapper/ASA adapter, idempotent issuance/status/lifecycle and request verification, or explicit capability blocker | G0; C03/C04, R11 durable operation identity and HTTPS | Reject production/arbitrary origins; current official schemas; actual signed sandbox approve/decline if selected; stable side-effect idempotency and unknown-outcome reconciliation; no invented SKU metadata or persisted PAN/CVV |
| C06 | Existing Akamai Kubernetes API/rail/merchant/agents runtime, PostgreSQL/Valkey, TLS/private routing and least-privilege Secrets | Owner Dockerfiles, C01; data schema from Rishi | Actual runtime/source/image/PVC evidence; each pod gets only needed keys; remove broad app-env imports from agent/MCP pods; no provider/JWT/mandate-signing/database keys there; durable state survives restart |
| C07 | Service tests plus `tests/test_decision_cases.py`; fault/concurrency/integrity tests | A01 fixture YAML, C02–C05 | Full policy matrix, direct-charge bypass rejection, invalid signature distinct from decline, provider/state-store outages, revocation race and no-inference checks |
| C08 | CI/image build/deploy setup in `.github/` and `infra/`, each service's deploy configuration | C01/C06; owners supply startup commands/dependencies | Reproducible image/startup, secret-only runtime config, probe/readiness and rollback; no mass formatting other lanes |
| C09 | Kill-switch card pause support via wrapper, authorization latency measurement and operating runbook in owned infra docs | C04/C05 if Lithic, R05; deployed traffic C06 | Kill switch respected independently of slow provider pause; p50/p95 actual source/rail latency; under-100-ms target measured, no fabricated figures |
| C10 | Deployed rail/reset/failure rehearsal and recording support | A07/G3, C07/C09 | Chosen rail accurately labeled, deployed tests run; authenticated local fallback ready; recording labeled prerecorded |

**Cameron agent starting prompt:** “Read all three direction documents and work only in Cameron's lane. Inspect current files, then implement the earliest unfinished C-task whose contracts are agreed. Make the controlled catalog independent from malicious listings, bind protected charge operations to verified checkouts, and build real local authorization plus atomic Valkey consumption before depending on Lithic availability. Use current official provider schemas, keep ASA network I/O Valkey-only, and return task ID, test evidence, capability status and owner handoffs without secrets.”

## Aditya — Strands, MCP, provenance, tests and presentation

**Human responsibilities:** validate Akamai inference/tool calling with actual credentials; review tool permissions, trusted/untrusted evidence and investigation output; tune/rehearse controlled adversarial listing content with Cameron; coordinate the three-minute demo and labeled resets; collect final readiness evidence and handle submission at the team's 7:30 AM Central target. The shopper must remain observable and susceptible enough to demonstrate backend protection.

**Coding agent lane:** `services/agents/`, `services/mcp-leash/`, `services/mcp-store/`, shared model factory, independent YAML fixtures, `tests/e2e/`, `docs/demo-script.md`. Start with A01 and A02; integrate real checkout tools when Rishi/Cameron hand off. Do not add prompt-injection defenses that eliminate the intentionally gullible shopper or let hooks become the only enforcement.

| ID | Deliverable and paths | Depends on / handoff | Evidence required to finish |
|---|---|---|---|
| A01 | Independent `tests/decision_cases.yaml` covering semantic/correlation/rail conditions and reproducible adversarial fixture descriptions | R01/G0; hand YAML to Cameron and scenario IDs to Rishi | Expected outcomes independently specified; duplicates/concurrency assigned to handler tests, not falsely graded by pure function |
| A02 | `shared/leash_shared/llm.py` factory/provider abstraction, real Akamai Strands smoke test in owned agent tests | C01 shared installability, human inference access | Text-only actual tool-call round trip, explicit `max_tokens`, guardian temperature 0, validated structured findings/fallback and outage metadata |
| A03 | Shopper browse/search/compare/select/checkout through both authenticated MCP servers and Graph context | R02/R12 scope, C02 canonical merchant, R03/R04; A11 orchestration | Genuine tools; intentionally susceptible shopper; phase/run-scoped permissions; backend always verifies; no unrestricted direct-tool/provider fallback |
| A04 | Supported before/after tool hooks and provenance in `services/agents/provenance/` | A02/A03, R01 event schemas/R06 intake; optional C06 snapshot store | Sanitized arguments/results, source hashes/refs/time/trust, real attempt/decision events; direct tool bypass still blocked by backend |
| A05 | Guardian/investigator in `services/agents/guardian/` | A02/A04, R03 verification/R06 evidence | Structured evidence-linked findings identify instruction versus attempt and suspicious source; recommends block/review, never grants or edits mandate |
| A06 | Official SDK stateless Streamable HTTP `services/mcp-leash/` with four thin tools and auth tests | R02/R04 actual API routes/contracts | Bearer forwarded unchanged, one API operation per tool; agent roles cannot confirm/expand/kill-switch; no alternate authorization path |
| A07 | `tests/e2e/` original S1–S6 plus S7 Kill Switch, automatic single-Graph S2→S6 and restart/reconciliation/replay tests | C02–C04, R02–R06/R11/R12, A03–A06/A11–A13, C06 | Real authorized purchase, pre-payment attack block, clean automatic recovery, bounded exhaustion, unknown-outcome no-repurchase, Kill Switch races, persisted SSE; fixture/live evidence separate |
| A08 | Attack scenario control coordination with Cameron; actual agent trace/guardian report handed to Rishi | C02/A03–A05, R09 UI | Attack changes listing/run selection only; actual subscription attempt observable; no fabricated agent manipulation or forced frontend result |
| A09 | Agent/MCP tests and Dockerfiles/READMEs; complete e2e matrix and SDK failure checks | A02–A07; hand startup/dependencies to C06 | Tool/hook redaction, direct-call bypass, immutable authority, role checks, model outages, no agent-success spoofing, service probes/startup |
| A10 | `docs/demo-script.md`: three-minute live script, exact session/reset plan, expected evidence, outage fallback and sponsor claims | G3, all-lane deployments/results | Rehearsed timing, accurate real-agent/provider labels, trusted evidence visible, no replay described as live; all required cases repeatable |
| A11 | Real SDK Strands Graph nodes/conditional edges in `services/agents/` | R02/R03/R04/R11; H05/H07/H08; genuine A02 inference | Actual Graph execution for shopper -> verifier -> guardian/containment/recovery or payment -> terminal; typed statuses, bounded nodes/time/cost; no Python-loop substitute |
| A12 | Deterministic containment, clean autonomous recovery and cooperative cancellation | A11; R05/R11 current scope; C02 compliant alternative | Quarantine source/hash/SKU/checkout; fresh context has original mandate + sanitized exclusions only; no raw hostile transcript; no retry after hard decline, unknown outcome or authorization; exhaustion/revocation/restart tests |
| A13 | Genuine invocation/inference/Graph/recovery lifecycle event capture | A04/A11/A12; R06 agreed event schema, H08/H12 | Real persisted events for node/edge/model/eligibility/restart/cancel/terminal with latency, sanitized evidence; no CoT/private prompts; reconnect does not start a run |

**Aditya agent starting prompt:** “Read AGENTS.md, Leash-build-plan.md and docs/LEASH_SPEC.md. Work only in Aditya's lane and select the earliest unfinished A-task with agreed prerequisites. Build actual Strands shopping/investigation and supported sanitized hooks, preserve the gullible shopper, and use protected backend checkout/payment interfaces. Supply independently expected security fixtures and six reproducible integration scenarios, keeping fixture-driven tests distinct from genuine agent traces. Return task ID, run/test evidence, provider status and cross-lane handoffs.”

## Contract handoffs — sender owns the implementation

Final field/route choices are approved in G0 and reflected in shared models/OpenAPI/spec; the following are the required responsibilities/data, not a claim these endpoints exist. A receiver tests its adapter against an agreed labeled fixture until the sender is ready. Integration completion requires the real sender, not a forever-stubbed response.

| Handoff | Sender -> receiver | Required contents | Needed before / acceptance |
|---|---|---|---|
| H01 Domain/events | Rishi -> both | Validated models, enums, canonical payload definitions/hash vectors, sanitized event envelope and example errors | Any cross-service implementation; all-three review and import check |
| H02 Runtime/package/config | Cameron -> both | Existing K8s namespace/DNS/images/probes/volumes, shared install method, database/Valkey, TLS/network/auth and config names; Compose optional | Selected runtime/imports actually work; image/source revision known; no Secrets values in handoff |
| H03 Human/agent authority | Cameron leads auth choice + Rishi verifier/identity -> Aditya/web | Agreed provider or retained equivalent, stable owner mapping, backend session verification, short-lived run/mandate/version/tool/audience scopes, immutable confirmation | No competing auth; preserve existing accounts/history; ownership/expiry/privileged-route negatives |
| H04 Trusted merchant | Cameron -> Rishi/Aditya | Configured authenticated retrieval, canonical SKU/category/price/quantity/recurrence, complete checkout totals/currency/revision/expiry/session | Verifier and checkout tools; malicious listing cannot mutate canonical facts |
| H05 Checkout binding | Cameron + Rishi -> shopper/rail | Authenticated purchase-attempt + checkout ID/hash + grant/instrument association, freeze/change rules, safe setup/failure order | Any usable grant or charge; different checkout cannot reuse binding |
| H06 Atomic rail protocol | Cameron -> Rishi | Grant/preapproval/current-authority/kill-switch/scope keys, atomic commands, expiry, duplicate fingerprints/cache and stream event commit | API grant writes/revoke and authorization; race/failure tests across processes |
| H07 Payment proposal/status | Rishi -> Aditya | Trusted checkout reference, purchase/run/mandate IDs, actual verification/grant/attempt states, once-only card retrieval if needed | MCP/shopper payment flow; no agent cart as proof or agent-selected success |
| H08 Trace/evidence/Graph | Aditya -> Rishi | Real model/node/edge/MCP/source/guardian/recovery/cancel events and typed Graph status, run/attempt/source IDs, latency and sanitized evidence | R06 persistence/replay and UI; no raw hostile recovery context/private reasoning; actual SDK proof |
| H09 Investigation | Aditya -> Rishi | Structured recommendation, violated constraints, source/trace/checkout evidence IDs, model/provider metadata/errors | Incident view; cannot override deterministic check/decision |
| H10 Policy fixtures | Aditya -> Cameron | Independent YAML expected outcomes and handler/e2e-only scenario definitions | C07/merge checks; semantic and ordinary controls separately exercised |
| H11 Selected rail/deployment | Cameron -> both | Public/internal URLs, actual rail/capability evidence, auth configuration references, health and latency results | Deployed demo/e2e; never include secret values in handoff |
| H12 OpenAPI/events/history | Rishi -> web/Aditya | Generated types, SSE event/cursor/auth contract, incident/history/receipt reads | UI/e2e; refresh and reconnect reconstruct true outcomes |
| H13 Demo/reset | Aditya -> both | Session/mandate/grant reset rules, fixtures, live script, failure path and rehearsal results | Freeze/submission; no silent scope reset or invented provider event |

Mark a handoff ready only when the sender supplies callable code/schema, one valid and one failure example, run/test command/result and a known limitation list. Receiver acknowledges the exact version it integrated. If a contract must change, stop its dependents and route the dedicated contract change through the three humans; work elsewhere can continue.

## Execution gates and team timeline

**Revised gate dependencies:** R05 Kill Switch and R11 operation/idempotency state belong in G1 with R03/R04/C04, before any usable instrument/grant. A11/A12 Graph and automatic recovery, R06 comprehensive SSE and R12 scoped auth belong in G2, before live acceptance. G3 additionally requires S7 Kill Switch and the combined automatic S2→S6 flow. G4 hardens these already functional controls; it cannot defer their implementation. Historical clock targets below are planning targets, not completed milestones.

Start with G0 immediately. After shared contracts, the three humans/lane agents may work concurrently inside their ownership boundaries. Every gate has a named human DRI; nobody assumes someone else validated it. Timestamp targets below preserve team intent, not completed milestones. All times are **America/Chicago**, October 10–11, 2026. If a target is already missed, replan the remaining tasks together without weakening acceptance.

| Gate / target | Human DRI | Rishi | Cameron | Aditya | Exit evidence |
|---|---|---|---|---|---|
| G0: next 45 minutes | Rishi; all review | R01 domain/authority/events | C01 packaging/runtime and source/rail protocol review | A01 fixtures and tool/event contract review | Agreed/frozen interfaces; dependencies recorded; no fake readiness |
| G1: security core; target Sat 7:00 PM | Rishi + Cameron | R02/R03/R04/R05/R11 working without model authority | C02/C03/C04 canonical merchant + real local rail | A01 independent fixtures; A02 round trip | Confirmed charger approves, same-price subscription blocks, direct bypass/replay/concurrency fail locally; actual persisted backend results |
| G2: genuine Graph integration; target Sat 10:00 PM | Aditya | R06 comprehensive SSE + R12 scope + R07 client | Merchant attack fixture; deploy staging; verified Lithic or documented local rail selection | A03–A06/A11–A13 actual Graph/MCP/recovery/events | Real Strands shopper encountered injected listing and attempted subscription; original authority unchanged; block and evidence linked |
| G3: deployed S1–S7 application; target Sun 1:00 AM | Rishi; all accept | R08/R09 full six-view UI, history/reload | C05–C07 actual selected rail and Akamai runtime | A07/A08 full integration matrix | S1–S7 on selected Kubernetes rail; automatic S2→S6, Kill Switch, replay/reconciliation and refresh pass |
| G4: hardening/presentation; target Sun 4:00 AM | Cameron for operations; Aditya for demo | R05/R10 invalidation/receipts/error states | C08–C10 CI/latency/failure/reset | A09/A10 regression suite/live script | Signature/fault/revocation tests, no critical-path inference, measured latency, correct labels, repeated <=3-minute rehearsal |
| G5: feature freeze; Sun 5:00 AM | All three | Critical fixes only | Confirm deployment/config; labeled backup recording | Rehearse/reset; collect evidence | No failing required scenario; local fallback ready; recording visibly prerecorded |
| Submission target: Sun 7:30 AM | Aditya | Verify final product/claim evidence | Verify deployed URL/rail status | Submit final materials after team signoff | Team submission before planned 8:00 AM deadline; do not claim submission until actual confirmation |

Local rail is built during G1 regardless of Lithic capability. Lithic research/configuration and Akamai deployment begin early and do not delay independent policy tests. UI shell/layout may proceed during G1 with labeled fixtures; switch each panel to actual API/events as soon as its handoff lands. Provider credentials supplied late do not excuse a hardcoded “security demo”.

## Security test matrix and original six scenarios plus Kill Switch

Aditya specifies independent expected fixtures; each service owner implements/tests its enforcement in their own lane. YAML cases must name their stage (`verifier`, `merchant`, `rail`, `handler`, or `e2e`): the pure rail function cannot inspect SKU facts absent from ASA metadata or test concurrency/idempotency by itself. Cameron's fixture runner handles rail cases; Rishi's verifier tests use verifier fixtures; merchant/handler/e2e checks use the actual appropriate interface.

| Boundary / case | Test owner | Required result |
|---|---|---|
| Draft/LLM interpretation without human confirmation | Rishi | No purchase authority/grant |
| Agent attempts confirm, replacement, limit raise, review approval or kill switch | Rishi + Aditya auth adapters | Forbidden, authority unchanged |
| Human confirmed payload edited, mandate version changed/revoked/expired | Rishi + Cameron race/state | Old grants unusable; immutable history retained |
| Canonical charger vs same-merchant/same-2999-cent subscription | Rishi verifier; Aditya e2e | Charger verifies; category/recurrence constraints block subscription |
| Unexpected merchant, quantity or product/shipping constraint | Rishi | Block; model confidence does not matter |
| Budget includes tax/shipping; wrong currency, invalid numeric types/totals | Rishi | Fail validation/block; confirmed comparator honored |
| Trusted source missing fields/unavailable/unauthenticated; unknown category | Rishi + Cameron merchant | Review/block, never agent-summary approval |
| Checkout changes revision/hash/items/recurrence after verification | Rishi + Cameron merchant | Revoke/invalidate binding; fresh verification required |
| Foreign-session checkout or arbitrary trusted source URL | Rishi + Cameron | Reject source/ownership substitution |
| Charger grant/instrument used for same-price subscription | Cameron protected merchant | Correlation rejection; do not invent ASA SKU visibility |
| Supported matching authorization | Cameron | Actual approval from exact valid bound grant |
| No grant, expired/revoked/consumed grant or expired checkout/authority | Cameron | Decline/no new successful purchase |
| Descriptor/merchant/MCC/instrument/currency/exact amount mismatch | Cameron | Decline; a lower charge is not automatically an exact-total match |
| Two distinct simultaneous requests for one grant/scope | Cameron | At most one approval/consumption across processes/replicas |
| Exact duplicate authenticated authorization event | Cameron handler | Identical cached original response; no second consumption/event count |
| Different payload under same event identity | Cameron handler | Integrity error, no cached success for altered content |
| Kill switch/revocation racing approval | Rishi + Cameron | Serialized authority/state; no approval after invalidation wins |
| Invalid/missing configured HMAC, tampered raw body, timestamp validation | Cameron adapter | Authentication error; no consumption; distinct from ordinary policy decline |
| Unsupported request/adjustment type, provider/state-store outage or partial commit | Cameron | No ordinary approval path; safe explicit error/decline handling |
| Authorization tries model/SQL/merchant network calls | Cameron | Tests prove critical path has none; network only Valkey |
| Direct checkout tool/API bypasses hook | Aditya tool + Rishi/Cameron backend | Same verification/charge policy still enforced |
| Model narrative claims payment succeeded | Rishi + Aditya | Cannot create approved/paid state; actual rail result controls UI/history |
| Sensitive tool args/results/snapshots/logs | All within own lane | No PAN/CVV/auth secret persisted or streamed |
| Duplicate/recovered event ingestion, refresh/SSE reconnect | Rishi + Aditya e2e | Persistent actual history, no lost/edited evidence or fabricated activity |

C07 starts testing during G1 and grows as adapters arrive; R06's minimum durable decision ingestion also belongs in G1. Full SSE/investigation/presentation then expands in G2/G3. Do not defer core concurrency/persistence verification to the final night pass.

| Scenario | Primary implementation / test | Actual outcome and essential assertion |
|---|---|---|
| S1 Legitimate charger | R03/R04 + C02–C04; A07 | `APPROVED`; human-confirmed canonical charger, valid grant, real authorization and persisted audit |
| S2 Same merchant/same amount attack | A03/A04/A08 + C02 + R03/R04; A07 | `BLOCKED`; actual subscription attempt, same merchant/2999/USD, unchanged mandate, trusted mismatch, no malicious grant; real local no-grant decline if shown |
| S3 Above budget | R03; A07 | `BLOCKED`; canonical total fails permitted comparison |
| S4 Missing/untrusted checkout | R03/C02; A07 | `REQUIRES_REVIEW` or `BLOCKED`; no grant based on shopper assurance |
| S5 Expiry/replay/concurrent delivery | R02/R04 + C04/C07; A07 | `BLOCKED` for distinct/expired use; exact duplicate response is idempotent, not a new transaction |
| S6 Automatic compliant recovery after attack | A11/A12 + R03/R04/R11 + C02–C04; A07 | S2→S6 within one real bounded Graph; quarantined source/SKU excluded; fresh context and checkout/grant; unchanged mandate; actual authorization and retained incident |
| S7 Human Kill Switch | R05 + C04/C09 + A12; A07 | Fresh unspent run/active grant stops; atomic race ordering, owner auth/idempotency/restart; actual provider pause/unknown outcomes; committed authorization not reversed |

A07 may use intentionally manipulated agent outputs to test policy repeatedly; label these as fixtures. G2 and the live presentation separately require a genuine Strands run encountering the malicious content and making the attempted action. Do not call a fixture-driven trace a live model manipulation.

## Three-minute demonstration and safe resets

Aditya owns the final callable script/reset commands in `docs/demo-script.md`. Rishi owns the visible screens; Cameron owns running rail/deployment/reset plumbing. Everyone rehearses against the actual deployment.

A singular purchase mandate cannot approve two successful checkouts. Use session B for mandatory live attack and automatic Graph recovery under one unchanged confirmed mandate; use fresh unspent session C for Kill Switch. Separate session A can prove clean S1 in preflight or if timed presentation permits. Live and scripted fallback sessions keep distinct mode-bound credentials/mandates. Make any session switch visible. Reset only through the agreed isolated demo procedure; never erase consumed grants or alter incidents to fake reuse.

| Time | Human presenter / live system action | Evidence judges see |
|---|---|---|
| 0:00–0:20 | Explain agent purchase risk | Same-price SKU problem and original human instruction |
| 0:20–0:40 | Human confirms session B and starts actual Graph | Displayed structured constraints, mandate version/hash; real SSE |
| 0:40–1:15 | Live shopper encounters poisoned listing via MCP | Genuine source/tool trace and subscription candidate, same merchant/2999/USD |
| 1:15–1:45 | Independent verifier rejects candidate; guardian investigates | Trusted product/recurrence mismatch, no malicious card/grant, persisted incident |
| 1:45–2:20 | Graph quarantines and restarts clean shopping automatically | Real node/edge events, excluded source/SKU, unchanged mandate, valid alternative and actual labeled authorization |
| 2:20–2:40 | Kill Switch on fresh session C, or disclosed replay evidence extension | Cancellation/effective unused-permission revocation and actual provider status; no reversal claim |
| 2:40–3:00 | Show persistent incident/history and sponsor contribution | Real Graph, genuine Akamai inference/compute and selected rail with accurate labels |

The earlier optional-recovery timing is superseded by this mandatory master demo: 0:00–0:20 problem; 0:20–0:40 human confirmation; 0:40–1:15 live poisoned listing and bad MCP checkout; 1:15–1:45 independent block/evidence; 1:45–2:20 automatic Graph quarantine/clean recovery and valid authorization; 2:20–2:40 Kill Switch on fresh unspent authority (or the master's explicitly labeled replay evidence extension); 2:40–3:00 sponsor/rail truth and persistent incident/history. Kill Switch functionality and S7 tests remain mandatory. Do not manually restart shopping to claim autonomous recovery. Aditya updates `docs/demo-script.md` in his lane; its current line 144 remains manual recovery. A separate clean S1 session can be shown in preflight or if rehearsed time permits. A completed attack/recovery session cannot buy twice or demonstrate prospective Kill Switch effects on an already authorized transaction.

## Risks, decisions and legitimate fallbacks

| Risk / decision owner | Immediate evidence check | Supported response |
|---|---|---|
| Lithic access/enrollment/HMAC/HTTPS — Cameron | Signed real sandbox approve/decline and provider schema tests | Select labeled Local Payment Rail Simulator if unverified; same engine/atomic backend behavior; no assumed Stripe or live funds |
| Akamai inference/Strands compatibility — Aditya | Actual tool-call round trip and validated findings | Centralized explicit provider fallback with true metadata; record outage; never turn unknown/denied checkout into approval |
| Guardian structured output — Aditya | Pydantic validation under incomplete/malformed responses | Validated plain-text JSON fallback or investigation-unavailable evidence; never model-authored grant |
| Shopper does not follow injected content — Aditya + Cameron | Actual logged run against controlled listing | Tune/rehearse listing; keep reproducible manipulated-output security tests separately labeled; no fabricated live action |
| Kubernetes/deployment trouble — Cameron | Actual service/data connectivity and probes | Single Linode runtime with real backend enforcement; Akamai compute requirement remains |
| Object Storage unavailable — Cameron + Aditya | Source snapshot upload/read test | Durable local evidence with truthful storage labels; still preserve source/hash/trace |
| UI stream/persistence failure — Rishi | Reload/reconnect from persisted API history | Fix intake/read state; no fabricated client events, success banners or overwritten history |
| Time short — all three | Unfinished critical task list at each gate | Drop swarms, extra merchants, notifications/Claude Desktop showcase first; retain every critical MVP control/view/scenario |
| Live outage during judging — Aditya | Determine actual failed dependency and rail/provider status | Clearly labeled prerecorded demonstration; do not present recording/replay as live functionality |

Humans resolve account access and scope decisions; coding agents own diagnosing and implementing within their lane. Capability status is `unverified`, `working with evidence`, or `blocked with reason/owner`; do not silently infer readiness from environment-variable names.

## Final readiness and submission signoff

The previous nineteen criteria in spec section 19 plus every master-revision gate in section 26 form the acceptance checklist; none are waived by this plan. The checks below make the team signoff concrete.

- [ ] Rishi confirms explicit human consent, immutable semantic authority, trusted checkout checks, grant gate, auth boundaries, historical versioning, durable audit/SSE, receipts and accurate six-view UI.
- [ ] Cameron confirms protected merchant binding, pure rail, atomic scope/idempotency/revocation, provider authenticity/sandbox-only lifecycle/reconciliation, no inference in ASA, actual rail/latency and existing Kubernetes integration. Optional Compose is separately labeled.
- [ ] Aditya confirms real bounded Strands Graph, genuine shopping/guardian/inference through MCP, clean automatic recovery with quarantine, cancellation/no-purchase-after-unknown, full lifecycle events, original S1–S6 plus S7 and genuine live attack trace.
- [ ] All three review same-price/same-merchant evidence, no false paid state, refresh/recovery, direct-call bypass/concurrency tests, credential redaction and known correlation limitations.
- [ ] Full service/security/e2e checks pass on the integrated app; current deployed configuration/URLs and reset procedure match the rehearsed run. Passing local fixtures alone does not complete deployment/live-agent acceptance.
- [ ] Demo is rehearsed within three minutes, session switch/consent is explicit, blocked result remains visible, provider/simulator/recording labels are correct, outage recording is clearly prerecorded.
- [ ] Aditya receives all-three human signoff, submits at the target and records actual confirmation; the plan does not itself submit anything.

## Task status and handoff reporting

Task tables are assignments, not completion marks. Record status beside the relevant task or in its linked PR/issue using `not started`, `in progress`, `ready for handoff`, `verified complete`, or `blocked`. A blocked report names the missing artifact/account/interface, human owner and next concrete action. Do not rewrite requirements to clear a blocker.

Use this handoff format for both coding agents and humans:

```text
Task: R03 / C04 / A07 (pick the actual ID)
Status and implementing owner:
Changed paths / PR or commit:
Behavior now working and its trust boundary:
Verification command + result + environment/rail/provider:
Consumer + contract version + next task:
Known limitation / blocker + responsible human + next action:
```

When changing product requirements, ownership, a shared interface or a milestone, update the affected source document and its cross-references in all three direction documents. Human confirmation of purchase authority is application behavior; human review of coding contracts is team coordination. Neither can be faked by an agent.

### R01 merge decision — October 10

Rishi authorized the initial R01 integration baseline after checking peer compatibility.
Separate approval messages from all three teammates are not claimed. Subsequent
shared-contract changes retain the dedicated PR and all-three coordination rule.
Cameron's PR #5 auth code is preserved; R02 maps its UUID user IDs
to LEASH's `usr_` identities before issuing purchase authority.

The agreed MCP direction uses separate `services/mcp-leash/` and
`services/mcp-store/` servers, both at `/mcp`, on ports 8002 and 8003. Aditya owns
both MCP services; Cameron owns the underlying merchant and deployment. Store
tools are merged and no direct Python shopping tools remain. Use separate scoped credentials, store-only browsing
with off-host/internal redirects rejected, server-side original HTML inspection,
redacted snapshots, and listing text plus evidence references/source hashes in tool
results. The API independently retrieves canonical checkout facts. Live injection
remains required; scripted runs are labeled fixtures or fallback.

## R02 implementation handoff

Historical original handoff; current implementation results are recorded in the audit and alignment-fixes handoff. Build/readiness/PVC and mode-separated credential configuration are merged. The following original operator instructions remain useful for deployment verification, not work to redo blindly.

R02 is implemented for the agreed merge/deployment handoff: migrations adopt existing
UUID auth, LEASH identity/agent ownership, exact signed human confirmation, immutable
versions, replacement/revocation/history and committed `/agent-runs` registration.
The 81-test API suite passes, including 19 real PostgreSQL tests for ownership,
expiry, mode authorization, retries, rollback and concurrency; correctness lint
passes. Frozen shared files are unchanged. See [api/r02-handoff.md](api/r02-handoff.md).

Cameron must update the API build to repo-root context and readiness to `/readyz`,
configure the signing/auth variables and distinct live/scripted agent tokens.
The API operator provisions both agents to the same intended human with their
respective mode; Aditya's latest credential selection must merge before fallback runs.
Rishi must complete independent checkout verification, payments and R06 provenance/
stream delivery. Authority mutations are atomic in SQL; R04/R05 and Cameron must
add coordinated Valkey grant invalidation before issuing any rail grant. Hosted
deployment, shared database migration and complete Compose boot remain unverified.

## Post-merge integration check — `266a805`

Historical check. The master alignment revision and current audit govern remaining work.

R02 and both teammate handoffs are merged: separate live/scripted credentials,
mandates and trace lanes, API root-context build, `/readyz` readiness and persistent
trace-spool configuration. The public API health/readiness endpoints return 200.
Actual Secrets, agent provisioning and PVC attachment remain unverified. R03 is
not started. [The R02 handoff](api/r02-handoff.md) records the current fixture/test verification.

The direct `/cards` issuance bypass is closed: agent/service credentials cannot
manage cards, human card reads are scoped to their real authenticated UUID, and
human direct issuance returns 409 because login is not verified purchase authority.
No provider issuance or card metadata insert is reachable through `POST /cards`.
The Lithic wrapper remains available for future internal verified payment issuance;
R03 is untouched and R04 must integrate confirmed authority, trusted checkout and
a valid scoped grant before issuing. Existing signup/balance sandbox behavior is
preserved and is not a verified purchase grant. Previously issued provider cards
were not revoked; deployment of the patch remains a separate handoff to Cameron.

## Next work in dependency order

1. **Cameron:** implement authenticated canonical store/checkouts and immutable protected charge binding (C02/H04/H05). Inspect the new credential names and root-context images before deployment.
2. **Rishi + Cameron:** connect trusted retrieval to the existing pure verifier; persist attempts/verification/payment operations before any side effect (R03/R04/R11), with tested SQL/Valkey ordering and replace/revoke propagation.
3. **Aditya + Rishi:** agree additive typed Graph/unknown-state/event contracts, short-lived run scopes and cancellation polling (R12/H08). Aditya implements real bounded Graph, clean recovery and cooperative stop (A11–A13).
4. **Rishi:** build confirmed-intent Mission Control/comparison/incident/history/Attack Lab on actual persisted states (R07–R10).
5. **Cameron + Aditya + Rishi:** deploy/verify selected rail on existing LKE; run live inference and signature attack→automatic recovery plus S7, restart/outage/replay and <=3-minute rehearsal. Until then, label local tests and ASA limitations accurately.
