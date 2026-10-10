# LEASH build plan

Updated October 10, 2026. Execution guide for **Rishi, Cameron, Aditya, and their coding agents**. This replaces the earlier hotel/gift-card implementation plan. It is a plan, not a record of completed work.

Read [AGENTS.md](AGENTS.md) for coding rules, the existing/planned repository tree, and path ownership. Read [docs/LEASH_SPEC.md](docs/LEASH_SPEC.md) for product/security requirements and detailed contracts. This file answers **who does what, in which order, what must be handed off, and what proves it works**. A direction/ownership change updates all three documents together. Product requirements come from the spec; path ownership comes from AGENTS; this plan cannot quietly override either.

## The result everyone is building

The user confirms: **“Buy a USB-C laptop charger for under $40. No subscriptions.”** A genuine Strands shopper buys a qualifying $29.99 charger. A poisoned listing then redirects a shopper toward an unrelated $29.99 subscription at the **same merchant and currency**. Independent canonical checkout facts expose the mismatch; deterministic backend enforcement blocks it and preserves evidence. A compliant purchase after a blocked attack still succeeds under unchanged authority.

The proof chain is: **confirmed intent -> actual agent/tool behavior -> independently verified checkout -> scoped one-use grant -> real backend authorization -> persistent, evidence-linked UI**. Do not replace any link with an approving stub, agent-authored cart, hardcoded outcome, or React-only animation. The controlled merchant must bind its protected charge operation to the exact verified checkout; ASA metadata alone does not prove SKU identity.

## Current checkout and planned structure

Existing: `api/` FastAPI starter with only `GET /health`; `web/` Next.js/React/TypeScript/Tailwind/shadcn starter, UI primitives and health helper. Strands is declared as a dependency, not integrated. R01 adds `shared/leash_shared/models.py`, `events.py`, and `api/tests/test_shared_contracts.py` as an initial review candidate on `rishi/r01-shared-contracts`. [api/README.md](api/README.md) documents exact hash payloads, field/envelope changes, test commands, and each owner's handoff. Joint freeze, Cameron's package/runtime installation, database, services, payment rails, Compose and deployment remain pending. Spec section 21 retains the original inspection snapshot.

Keep the existing product backend in `api/`. `services/api/` is a reserved legacy alternative, not a second implementation or a required move. The complete annotated tree is in [AGENTS.md](AGENTS.md#repository-tree). Planned agents/MCP/webhook/store retain the original separate service boundaries. API port 8000 and web port 3000 are current development conventions; planned agent/MCP/webhook/store ports are 8001/8002/8003/8004, to be wired by Cameron. Preserve `/health`; add agreed `/healthz` probes for new services rather than pretending they exist already.

No integrations or account credentials are assumed ready. Original and current file-status observations are snapshots; refresh them before starting code. Leave unrelated working-tree changes intact.

## Ownership — identical to AGENTS.md

Each person's coding agent edits only that person's paths. Cross-lane work is an interface handoff; the owner makes the edit. Existing ownership is retained. Shared package metadata/marker files are assigned to Cameron so installability has an explicit owner; domain contracts remain Rishi's.
| Path | Owner |
|---|---|
| `infra/`, `docker-compose.yml`, `.env.example`, `.github/`, root `pyproject.toml` | Cameron |
| `services/webhook/`, `services/store/`, `tests/test_decision_cases.py` | Cameron |
| `shared/leash_shared/lithic.py` | Cameron |
| `shared/pyproject.toml`, `shared/leash_shared/__init__.py` | Cameron |
| `api/`, `services/api/`, `db/`, `web/` | Rishi |
| `shared/leash_shared/models.py`, `shared/leash_shared/events.py` | Rishi; frozen after joint agreement |
| `services/agents/`, `services/mcp/` | Aditya |
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

- [ ] Agree fields/enums for PurchaseMandate, proposal Cart, AgentRun/Trace, canonical product/CheckoutSnapshot, CheckoutVerification, AuthorizationGrant, AuthorizationAttempt/PaymentDecision, SecurityIncident, AuditEvent. Use spec section 23's `_cents` mapping, UTC, canonical payload hashing, immutable confirmed versions, exact totals/currency and sanitized evidence.
- [ ] Confirm human versus agent auth/session boundaries, merchant source authentication, configured source registry, and checkout ownership. CORS or agent claims cannot substitute for auth.
- [ ] Confirm quantity/purchase cardinality and comparator: the singular request defaults to one successful checkout, quantity one; “under $40” has maximum 3999 cents unless the human confirms otherwise. A block consumes no purchase authority. Live demo sessions/reset behavior must respect consumed scope.
- [ ] Agree checkout revision freeze, trusted checkout retrieval, grant/instrument binding, protected merchant charge operation and activation order. A grant becomes usable only after all verification and required merchant correlation binding succeed; failed setup revokes any partial grant and never approves.
- [ ] Agree Valkey schemas/atomic operations for authority revocation, kill switch, scope reservation, grant issuance/consumption, idempotent event identity/fingerprint, cached response retention and audit stream commit. API owns durable writes; webhook network I/O is Valkey only.
- [ ] Agree route/request/response/error examples in spec section 23.6; choose exact route names without arbitrary renaming. Only `/health` exists today. Agree run API location, SSE event IDs/resume/auth, incident/history queries and receipt format.
- [ ] Agree service packaging/dependencies: Cameron owns root workspace/ruff config and shared package installability; each service owner owns its project dependencies/Dockerfile. Specify how owners install/import the shared package without duplicate models.
- [ ] Agree fixtures: canonical charger and canonical subscription both total 2999 cents, same merchant/currency; the attack changes only listing text/agent behavior. Add over-budget, missing-evidence, expiry/replay and recovery fixtures. Adversarial listing text cannot edit canonical records.
- [ ] Agree selected local rail interface first; Cameron reports Lithic/Akamai capability checks without printing secrets. Genuine Strands/Akamai round-trip is separately verified by Aditya.
- [ ] Review and freeze the first `models.py`/`events.py`; publish matching OpenAPI/examples and confirm every lane can build against them. Record any unresolved choice explicitly with its owner before coding its dependents.

**Exit evidence:** all three have reviewed identical model/event schemas and interface examples; source trust, payment correlation and atomicity are explicit; task owners know the next handoffs. Contracts being documented is not an implemented security mechanism.

## Rishi — product backend, durable state and frontend

**Human responsibilities:** lead G0 and cross-lane product integration; review the confirmed-intent fields and user consent flow; agree source/rail protocols with Cameron; validate the UI explains actual enforcement and provider state; accept G1/G3 product integration and final application readiness. Coordinate contract PRs with both teammates.

**Coding agent lane:** `api/`, `db/`, `web/`, Rishi's frozen shared files and shared direction documents. Start with R01/R02, then verifier/payment/persistence before polishing the UI. Do not move the starter, implement Cameron's provider/merchant/infra files, or put user/provider secrets in frontend code.

| ID | Deliverable and paths | Depends on / handoff | Evidence required to finish |
|---|---|---|---|
| R01 | Agreed validated domain contracts and canonical JSON/hash helpers in `shared/leash_shared/models.py`; event schemas/publish helper in `events.py` | G0; Cameron packaging, all-three review; everyone consumes | Typed semantic authority, checkout/grant/decision/trace contracts, exact cents/UTC, hash-change vectors, shared import works |
| R02 | SQL migrations in `db/`; persistence/session/auth wiring in `api/`; mandate propose/confirm/read/replacement/revoke | R01, C01 runtime/data; Aditya consumes mandate routes | Explicit human confirmation/signature association, immutable history, agent forbidden on privileged routes, expiry/cross-session tests |
| R03 | Independent checkout verifier in `api/` and tests in `api/tests/` | R01, C02 canonical merchant interface; hand verified evidence to R04 | Server fetch/auth, trusted typed items/totals/revision, every constraint, unknown/missing evidence fail closed, agent cart never proof |
| R04 | Payment proposal/status, idempotent grant/instrument issuance, correlation registration in `api/` | R02/R03, C03/C04 grant protocol and C02 binding; MCP/shopper consumes | Only verified current authority issues grant; exact amount/currency/expiry/scope; setup failure unusable; no LLM mint; once-only card delivery if needed |
| R05 | Replacement/revoke/kill-switch state invalidation plus optional provider pause via Cameron wrapper | R04, C04 atomic protocol, C05 helper when rail selected | Revocation/consumption races serialized, old unused grants rejected, agent cannot toggle; historical approvals preserved |
| R06 | Durable event ingestion, sanitized trace/provenance intake, SSE/read APIs and incidents/history in `api/` | R01 events, C04 stream, A03/A04 traces/findings | SQL commit then ack; event dedup/recovery; authorized SSE cursor resume; refresh reconstructs real status/evidence |
| R07 | Shared OpenAPI-generated `web/src/lib/api-types.ts`, typed API client and server-side user/session auth | R02/R04/R06 agreed OpenAPI | Types match contracts; no secrets in `NEXT_PUBLIC_*`; no duplicate handwritten schema; meaningful errors |
| R08 | Mission Control + explicit mandate confirmation + purchase comparison in `web/` | R07; can build layout with labeled isolated fixtures first | Original instruction stays visible; constraints vs trusted attempted facts; grant/authorization/paid distinction; actual consent and backend results |
| R09 | Real activity, incident timeline, transaction history and Attack Lab in `web/` | R06/R08, A02/A04, C02 attack scenario API | Actual streamed tool/state events, source inspection, reload persistence, actual provider/source/latency; attack never changes mandate/outcome |
| R10 | Receipts/evidence chain, empty/error/loading states, service Dockerfile/README and final integration checks | R05–R09, C06 deployment, A07 e2e | Readable signed/hash-linked chain without overstated guarantees, provider failure never success, deployed positive/block/recovery, usable phone/big-screen UI |

**R01 implementation status:** models, hashing, event publishing and contract tests are implemented as the initial review candidate. The handoff documents the mandatory `checkout_id` on payment proposals, the nested grant on PreApproval, nullable guardian model, the 15 required verification checks, and the `event` stream field. Contract tests pass; joint review/freeze and C01 shared package/runtime installation remain open. R02 signing/auth/persistence and R03 independent verification are separate work, not completed by parsing a valid record.

**Rishi agent starting prompt:** “Read AGENTS.md, Leash-build-plan.md and docs/LEASH_SPEC.md. Work as Rishi's coding agent. Inspect current files and Git status, then implement the earliest unfinished R-task with satisfied prerequisites. Stay in the Rishi lane. Lead shared contracts through all-three review; do not treat an agent cart or positive guardian opinion as payment authority. Preserve the current api/ starter and fail closed until independent checkout and correlation are complete. Return task ID, code/tests, handoff and real blockers.”

## Cameron — trusted merchant, deterministic payment rail and infrastructure

**Human responsibilities:** obtain/verify Lithic and Akamai account capabilities, public URLs/TLS and managed data connectivity; configure secrets server-side; review source trust, provider wire/signature behavior, correlation and atomic grant enforcement with Rishi; select the demonstrated rail based on evidence; own deployment/latency readiness. Do not promise integrations based only on an API key or sign-up.

**Coding agent lane:** Cameron's infra/workspace/packaging, merchant/webhook/SDK wrapper and policy runner paths. Build the controlled merchant plus local rail early; Lithic capability checks and deployment proceed independently. Do not change Rishi's domain contracts/migrations/API or Aditya's fixtures/tools.

| ID | Deliverable and paths | Depends on / handoff | Evidence required to finish |
|---|---|---|---|
| C01 | Root workspace/ruff config, shared package metadata/marker, `.env.example`, Compose, Valkey/data wiring and infrastructure skeleton | G0 packaging/config; service owners provide their Dockerfiles | Every service imports agreed package, config contains no secret values, health probes use real routes, Compose boots as services land |
| C02 | `services/store/` canonical catalog/checkouts, listing attack toggle, protected binding/charge API and tests | R01 schemas, G0 trust/correlation; hand to R03/A02 | Same merchant/2999-cent charger+subscription; malicious text cannot alter catalog; auth/session/revision checks; charger grant cannot charge subscription |
| C03 | Pure payment decision engine in `services/webhook/decide.py` and distinct local adapter | R01, G0 domain rules; A01 fixtures | Genuine approve/decline from grant/evidence/state, exact total/currency/expiry, supported request types, no LLM/SQL/merchant calls |
| C04 | Valkey atomic grant/scope/authority/invalidation/consumption/idempotency/audit protocol and handler tests | C03; agree API writes with R04/R05, events with R06 | Distinct concurrent attempts consume once; identical duplicate response; altered duplicate payload errors; cached state/revocation/commit failures never new approval |
| C05 | `shared/leash_shared/lithic.py`, official sandbox SDK/ASA adapter and request verification, or explicit capability blocker | G0 capability check; C03/C04 and reachable HTTPS | Real signed sandbox approval/decline if selected, correct fields/HMAC/request types; no invented checkout-ID metadata; no logged PAN/CVV; once-only details supported |
| C06 | Real Akamai FastAPI/rail/merchant/agents runtime, PostgreSQL/Valkey and optional Object Storage, TLS/secrets/ingress | Owner Dockerfiles, C01; data schema from Rishi | Deployed URLs/probes/connectivity, actual backend decisions on Akamai; no merely decorative cloud claim; durable data survives restart |
| C07 | Service tests plus `tests/test_decision_cases.py`; fault/concurrency/integrity tests | A01 fixture YAML, C02–C05 | Full policy matrix, direct-charge bypass rejection, invalid signature distinct from decline, provider/state-store outages, revocation race and no-inference checks |
| C08 | CI/image build/deploy setup in `.github/` and `infra/`, each service's deploy configuration | C01/C06; owners supply startup commands/dependencies | Reproducible image/startup, secret-only runtime config, probe/readiness and rollback; no mass formatting other lanes |
| C09 | Kill-switch card pause support via wrapper, authorization latency measurement and operating runbook in owned infra docs | C04/C05 if Lithic, R05; deployed traffic C06 | Kill switch respected independently of slow provider pause; p50/p95 actual source/rail latency; under-100-ms target measured, no fabricated figures |
| C10 | Deployed rail/reset/failure rehearsal and recording support | A07/G3, C07/C09 | Chosen rail accurately labeled, deployed tests run; authenticated local fallback ready; recording labeled prerecorded |

**Cameron agent starting prompt:** “Read all three direction documents and work only in Cameron's lane. Inspect current files, then implement the earliest unfinished C-task whose contracts are agreed. Make the controlled catalog independent from malicious listings, bind protected charge operations to verified checkouts, and build real local authorization plus atomic Valkey consumption before depending on Lithic availability. Use current official provider schemas, keep ASA network I/O Valkey-only, and return task ID, test evidence, capability status and owner handoffs without secrets.”

## Aditya — Strands, MCP, provenance, tests and presentation

**Human responsibilities:** validate Akamai inference/tool calling with actual credentials; review tool permissions, trusted/untrusted evidence and investigation output; tune/rehearse controlled adversarial listing content with Cameron; coordinate the three-minute demo and labeled resets; collect final readiness evidence and handle submission at the team's 7:30 AM Central target. The shopper must remain observable and susceptible enough to demonstrate backend protection.

**Coding agent lane:** `services/agents/`, `services/mcp/`, shared model factory, independent YAML fixtures, `tests/e2e/`, `docs/demo-script.md`. Start with A01 and A02; integrate real checkout tools when Rishi/Cameron hand off. Do not add prompt-injection defenses that eliminate the intentionally gullible shopper or let hooks become the only enforcement.

| ID | Deliverable and paths | Depends on / handoff | Evidence required to finish |
|---|---|---|---|
| A01 | Independent `tests/decision_cases.yaml` covering semantic/correlation/rail conditions and reproducible adversarial fixture descriptions | R01/G0; hand YAML to Cameron and scenario IDs to Rishi | Expected outcomes independently specified; duplicates/concurrency assigned to handler tests, not falsely graded by pure function |
| A02 | `shared/leash_shared/llm.py` factory/provider abstraction, real Akamai Strands smoke test in owned agent tests | C01 shared installability, human inference access | Text-only actual tool-call round trip, explicit `max_tokens`, guardian temperature 0, validated structured findings/fallback and outage metadata |
| A03 | Shopper browse/search/compare/select/checkout tools and run service/CLI in `services/agents/shopper/` | R02 mandate context, C02 catalog/listing/checkout, R04 payments | Genuine Strands execution, mandate unchanged, actual tool calls; protected checkout delegates enforcement and has no unrestricted provider API |
| A04 | Supported before/after tool hooks and provenance in `services/agents/provenance/` | A02/A03, R01 event schemas/R06 intake; optional C06 snapshot store | Sanitized arguments/results, source hashes/refs/time/trust, real attempt/decision events; direct tool bypass still blocked by backend |
| A05 | Guardian/investigator in `services/agents/guardian/` | A02/A04, R03 verification/R06 evidence | Structured evidence-linked findings identify instruction versus attempt and suspicious source; recommends block/review, never grants or edits mandate |
| A06 | Official SDK stateless Streamable HTTP `services/mcp/` with four thin tools and auth tests | R02/R04 actual API routes/contracts | Bearer forwarded unchanged, one API operation per tool; agent roles cannot confirm/expand/kill-switch; no alternate authorization path |
| A07 | `tests/e2e/` six-scenario integration runner with reset/session handling and persistence checks | C02/C03/C04, R02–R06, A03–A06; deployed URLs C06 | Positive, semantic attack, budget, missing evidence, expiry/replay, recovery; unchanged attack/recovery mandate and real results; manipulated-output fixtures separately labeled |
| A08 | Attack scenario control coordination with Cameron; actual agent trace/guardian report handed to Rishi | C02/A03–A05, R09 UI | Attack changes listing/run selection only; actual subscription attempt observable; no fabricated agent manipulation or forced frontend result |
| A09 | Agent/MCP tests and Dockerfiles/READMEs; complete e2e matrix and SDK failure checks | A02–A07; hand startup/dependencies to C06 | Tool/hook redaction, direct-call bypass, immutable authority, role checks, model outages, no agent-success spoofing, service probes/startup |
| A10 | `docs/demo-script.md`: three-minute live script, exact session/reset plan, expected evidence, outage fallback and sponsor claims | G3, all-lane deployments/results | Rehearsed timing, accurate real-agent/provider labels, trusted evidence visible, no replay described as live; all required cases repeatable |

**Aditya agent starting prompt:** “Read AGENTS.md, Leash-build-plan.md and docs/LEASH_SPEC.md. Work only in Aditya's lane and select the earliest unfinished A-task with agreed prerequisites. Build actual Strands shopping/investigation and supported sanitized hooks, preserve the gullible shopper, and use protected backend checkout/payment interfaces. Supply independently expected security fixtures and six reproducible integration scenarios, keeping fixture-driven tests distinct from genuine agent traces. Return task ID, run/test evidence, provider status and cross-lane handoffs.”

## Contract handoffs — sender owns the implementation

Final field/route choices are approved in G0 and reflected in shared models/OpenAPI/spec; the following are the required responsibilities/data, not a claim these endpoints exist. A receiver tests its adapter against an agreed labeled fixture until the sender is ready. Integration completion requires the real sender, not a forever-stubbed response.

| Handoff | Sender -> receiver | Required contents | Needed before / acceptance |
|---|---|---|---|
| H01 Domain/events | Rishi -> both | Validated models, enums, canonical payload definitions/hash vectors, sanitized event envelope and example errors | Any cross-service implementation; all-three review and import check |
| H02 Runtime/package/config | Cameron -> both | Shared install method, Compose service names/URLs/ports, datastore connection setup, configuration names without values | Local multi-service integration; owner-provided Dockerfiles/probes actually boot |
| H03 Human/agent authority | Rishi -> Aditya/web | Draft/confirmed mandate payload, immutable version/hash, auth/session scopes, readable expiry and constraints | Shopper/MCP and user confirmation; privileged-route negative tests |
| H04 Trusted merchant | Cameron -> Rishi/Aditya | Configured authenticated retrieval, canonical SKU/category/price/quantity/recurrence, complete checkout totals/currency/revision/expiry/session | Verifier and checkout tools; malicious listing cannot mutate canonical facts |
| H05 Checkout binding | Cameron + Rishi -> shopper/rail | Authenticated purchase-attempt + checkout ID/hash + grant/instrument association, freeze/change rules, safe setup/failure order | Any usable grant or charge; different checkout cannot reuse binding |
| H06 Atomic rail protocol | Cameron -> Rishi | Grant/preapproval/current-authority/kill-switch/scope keys, atomic commands, expiry, duplicate fingerprints/cache and stream event commit | API grant writes/revoke and authorization; race/failure tests across processes |
| H07 Payment proposal/status | Rishi -> Aditya | Trusted checkout reference, purchase/run/mandate IDs, actual verification/grant/attempt states, once-only card retrieval if needed | MCP/shopper payment flow; no agent cart as proof or agent-selected success |
| H08 Trace/evidence | Aditya -> Rishi | Before/after tool event IDs, run/source/hash/time, sanitized args/results, trust class, proposed action and policy outcome | Live activity/incident UI; persisted real events, redaction verified |
| H09 Investigation | Aditya -> Rishi | Structured recommendation, violated constraints, source/trace/checkout evidence IDs, model/provider metadata/errors | Incident view; cannot override deterministic check/decision |
| H10 Policy fixtures | Aditya -> Cameron | Independent YAML expected outcomes and handler/e2e-only scenario definitions | C07/merge checks; semantic and ordinary controls separately exercised |
| H11 Selected rail/deployment | Cameron -> both | Public/internal URLs, actual rail/capability evidence, auth configuration references, health and latency results | Deployed demo/e2e; never include secret values in handoff |
| H12 OpenAPI/events/history | Rishi -> web/Aditya | Generated types, SSE event/cursor/auth contract, incident/history/receipt reads | UI/e2e; refresh and reconnect reconstruct true outcomes |
| H13 Demo/reset | Aditya -> both | Session/mandate/grant reset rules, fixtures, live script, failure path and rehearsal results | Freeze/submission; no silent scope reset or invented provider event |

Mark a handoff ready only when the sender supplies callable code/schema, one valid and one failure example, run/test command/result and a known limitation list. Receiver acknowledges the exact version it integrated. If a contract must change, stop its dependents and route the dedicated contract change through the three humans; work elsewhere can continue.

## Execution gates and team timeline

Start with G0 immediately. After shared contracts, the three humans/lane agents may work concurrently inside their ownership boundaries. Every gate has a named human DRI; nobody assumes someone else validated it. Timestamp targets below preserve team intent, not completed milestones. All times are **America/Chicago**, October 10–11, 2026. If a target is already missed, replan the remaining tasks together without weakening acceptance.

| Gate / target | Human DRI | Rishi | Cameron | Aditya | Exit evidence |
|---|---|---|---|---|---|
| G0: next 45 minutes | Rishi; all review | R01 domain/authority/events | C01 packaging/runtime and source/rail protocol review | A01 fixtures and tool/event contract review | Agreed/frozen interfaces; dependencies recorded; no fake readiness |
| G1: security core; target Sat 7:00 PM | Rishi + Cameron | R02/R03/R04 working without model authority | C02/C03/C04 canonical merchant + real local rail | A01 independent fixtures; A02 round trip | Confirmed charger approves, same-price subscription blocks, direct bypass/replay/concurrency fail locally; actual persisted backend results |
| G2: genuine agent integration; target Sat 10:00 PM | Aditya | R06 real intake/SSE + R07 generated client | Merchant attack fixture; deploy staging; verified Lithic or documented local rail selection | A03–A06 actual tools/hooks/investigation/MCP | Real Strands shopper encountered injected listing and attempted subscription; original authority unchanged; block and evidence linked |
| G3: deployed six-scenario application; target Sun 1:00 AM | Rishi; all accept | R08/R09 full six-view UI, history/reload | C05–C07 actual selected rail and Akamai runtime | A07/A08 full integration matrix | All six scenarios on selected deployed rail; actual FastAPI policy on Akamai; refresh and recovery succeed |
| G4: hardening/presentation; target Sun 4:00 AM | Cameron for operations; Aditya for demo | R05/R10 invalidation/receipts/error states | C08–C10 CI/latency/failure/reset | A09/A10 regression suite/live script | Signature/fault/revocation tests, no critical-path inference, measured latency, correct labels, repeated <=3-minute rehearsal |
| G5: feature freeze; Sun 5:00 AM | All three | Critical fixes only | Confirm deployment/config; labeled backup recording | Rehearse/reset; collect evidence | No failing required scenario; local fallback ready; recording visibly prerecorded |
| Submission target: Sun 7:30 AM | Aditya | Verify final product/claim evidence | Verify deployed URL/rail status | Submit final materials after team signoff | Team submission before planned 8:00 AM deadline; do not claim submission until actual confirmation |

Local rail is built during G1 regardless of Lithic capability. Lithic research/configuration and Akamai deployment begin early and do not delay independent policy tests. UI shell/layout may proceed during G1 with labeled fixtures; switch each panel to actual API/events as soon as its handoff lands. Provider credentials supplied late do not excuse a hardcoded “security demo”.

## Security test matrix and six acceptance scenarios

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
| S6 Compliant purchase after attack | R03/R04 + C02–C04; A07 | `APPROVED`; same unchanged mandate from blocked attempt, fresh checkout/grant; incident remains in history |

A07 may use intentionally manipulated agent outputs to test policy repeatedly; label these as fixtures. G2 and the live presentation separately require a genuine Strands run encountering the malicious content and making the attempted action. Do not call a fixture-driven trace a live model manipulation.

## Three-minute demonstration and safe resets

Aditya owns the final callable script/reset commands in `docs/demo-script.md`. Rishi owns the visible screens; Cameron owns running rail/deployment/reset plumbing. Everyone rehearses against the actual deployment.

A singular purchase mandate cannot legitimately approve a second successful checkout. Prepare **two explicitly human-confirmed demo sessions** with the same displayed original instruction/constraints: session A for the legitimate success, session B for the attack (and recovery if shown). Make the session switch visible. The attack never modifies B's mandate. Use a separate preflight test session for the six-scenario rehearsal. Reset only through the agreed isolated demo procedure; never erase consumed grants invisibly or alter historical incidents to fake reuse.

| Time | Human presenter / live system action | Evidence judges see |
|---|---|---|
| 0:00–0:20 | Aditya explains problem; Rishi shows confirmed intent/constraints/session A | Charger under $40, no subscriptions; real human confirmation |
| 0:20–0:45 | Run actual shopper on legitimate listing in A | Genuine tools, trusted verification, selected actual rail, approved backend result |
| 0:45–1:30 | Visible switch to equally confirmed session B; choose malicious listing/run through Attack Lab | Real untrusted content and resulting subscription checkout attempt; B's mandate/hash unchanged |
| 1:30–2:00 | Show intent versus trusted attempted purchase and backend decision | Same merchant/2999 cents/USD; different product/recurrence; actual block. Show the true enforcement stage, no invented ASA callback |
| 2:00–2:35 | Open incident timeline | Listing/source hash, actual tool action, canonical checkout, violated checks, actual decision/source/latency |
| 2:35–3:00 | Aditya explains Strands + actual Akamai deployment + verified rail and guarantee | Keep blocked incident visible; distinguish local simulation/Lithic sandbox/recording |

S6 recovery is required in the integration/preflight evidence; it can be shown live in B if rehearsed timing permits, then return to the blocked incident. Do not suggest the attack consumed B's legitimate purchase authority. The concluding claim is limited to the controlled merchant and actual correlation implemented, not universal SKU visibility from card metadata.

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

The nineteen MVP criteria in spec section 19 remain the full acceptance checklist; none are waived by this plan. The checks below make the team signoff concrete.

- [ ] Rishi confirms explicit human consent, immutable semantic authority, trusted checkout checks, grant gate, auth boundaries, historical versioning, durable audit/SSE, receipts and accurate six-view UI.
- [ ] Cameron confirms protected merchant binding, pure deterministic rail, atomic scope/one-use/idempotency/revocation, provider signature/failure handling, no inference in ASA, actual selected rail, measured latency, Compose boot and real Akamai deployment.
- [ ] Aditya confirms genuine Strands shopping/investigation, actual sanitized hooks/source evidence, real compatible Akamai tool calling where available, protected MCP/tools, six repeatable integration scenarios and genuine live attack trace.
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
