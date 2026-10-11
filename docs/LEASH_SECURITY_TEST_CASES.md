# LEASH — Security, Orchestration, Payment & Demo Acceptance Test Plan

**Proposed repository destination:** `docs/LEASH_SECURITY_TEST_CASES.md`  
**Date:** 2026-10-10  
**Status:** **TEST SPECIFICATION, NOT RESULTS.** Every case begins as `NOT_RUN`; Codex must inspect the actual repository and map each ID to executable tests, evidence and owner. Do not call tests passed on the basis of this text.

## Why this exists

Consolidates the original master specification's acceptance cases and the detailed learning-session cases, including two distinct stop controls, cross-store PostgreSQL/Valkey races, Kubernetes Graph cancellation, SSE replay, single-use cards, prompt-injection recovery and payment reconciliation. Covers positive, negative, race, failure-injection and real integration scenarios.

## Labels and acceptance rules

- **Priority:** P0 = security/demo must-have; P1 = valuable hardening. Never ship an unsafe P0 bypass.
- **Level:** `UNIT` pure models/policy; `API` scoped HTTP auth/domain; `INTEG` cross-service/mock/provisioned environment; `RACE` concurrency with real atomic state; `PERF` measured hot path; `LIVE` actual Strands Graph + MCP + provider integration or correctly labeled local rail.
- **Test status:** `NOT_RUN`, `PASS`, `FAIL`, `BLOCKED_EXTERNAL`, `MISSING`, or `SKIPPED` with explanation. No evidence = not PASS.
- **Provider-specific:** If Lithic ASA or sandbox is not provisioned, mark those provider tests `BLOCKED_EXTERNAL` while proving independent policy/local-rail behavior. Do not count mock provider tests as real provider integration.
- **Test case template in automation:** use `test_<ID_normalized>_<short_name>()` as traceability marker where practical; file paths and real function names recorded in an implementation mapping annex.
- **Required per-case evidence once implemented:** exact test file/path, command, timestamp/log/artifact, environment (`unit|mock|sandbox|live`), current status, owner, open issue if failing.
- **Security invariant:** a denied pre-payment checkout never reaches card issuance; no LLM can authorize money; single-use grant only authorizes correct merchant/amount/currency/checkout association; no distinct charge after effective stop.

## Test matrix

| ID | Priority | Level | Scenario | Procedure / stimulus | Expected authoritative behavior | Status |
|---|---|---|---|---|---|---|
| `AUTH-001` | P0 | API | Unauthenticated mandate confirmation | POST confirm without session | 401/403; no confirmed mandate or grant | NOT_RUN |
| `AUTH-002` | P0 | API | Agent cannot confirm human mandate | Attempt confirmation using agent MCP token | Denied; no authority elevated | NOT_RUN |
| `AUTH-003` | P0 | API | Cross-user mandate read | User A GET user B mandate ID | 403 or safe 404; no private content | NOT_RUN |
| `AUTH-004` | P0 | API | Cross-user run stop | User A stops user B run | Denied; user B workflow and grants unchanged | NOT_RUN |
| `AUTH-005` | P0 | API | Cross-user SSE subscription | User A subscribes to user B event feed | Denied; no event leakage | NOT_RUN |
| `AUTH-006` | P0 | API | Spoofed user_id argument | Agent supplies another user_id in request body | Identity derived from signed credential; spoof rejected | NOT_RUN |
| `AUTH-007` | P0 | API | Agent token wrong mandate | Agent token for m1 requests purchase for m2 | Denied at MCP/API; no card issued | NOT_RUN |
| `AUTH-008` | P0 | API | Agent token wrong run | Agent credential for run A uses run B | Denied at MCP/API | NOT_RUN |
| `AUTH-009` | P0 | API | Expired or wrong-audience agent token | Call MCP with expired or incorrect aud token | Denied; fail closed | NOT_RUN |
| `AUTH-010` | P0 | API | Provider credential leakage prevention | Inspect logs/errors/frontend events after provider call | No Lithic API key, PAN, CVV, bearer token exposed | NOT_RUN |
| `AUTH-011` | P1 | API | Session logout and new payment requests | Invalidate session then attempt new human authority | Denied until new human login; existing payment scope policy explicit | NOT_RUN |
| `AUTH-012` | P1 | API | CSRF on session-backed confirmation | Cross-origin state change without CSRF protection | Denied according to selected auth stack | NOT_RUN |
| `MAN-001` | P0 | UNIT | Draft is not spend permission | Propose only, then request payment | No grant/card; human confirmation required | NOT_RUN |
| `MAN-002` | P0 | API | Confirmed mandate immutable/versioned | Attempt in-place change of budget or category | Rejected or new separately confirmed version; original preserved | NOT_RUN |
| `MAN-003` | P0 | UNIT | Strict under-40 boundary | Total exactly 4000 cents with exclusive limit 4000 | DENY budget reason | NOT_RUN |
| `MAN-004` | P0 | UNIT | 39.99 boundary | Total 3999 cents, otherwise valid | ALLOW for amount check | NOT_RUN |
| `MAN-005` | P0 | API | Mandate expired | Run/payment after expiration | Denied | NOT_RUN |
| `MAN-006` | P0 | API | Mandate revoked | Request fresh grant with revoked mandate | Denied | NOT_RUN |
| `MAN-007` | P0 | API | Stale mandate version/hash | Agent presents old version after human reconfirms changed scope | Denied; no grant | NOT_RUN |
| `MAN-008` | P0 | API | Wrong mandate ownership | Bind checkout belonging to A under B mandate | Denied | NOT_RUN |
| `MAN-009` | P0 | UNIT | Missing category or subscription setting | Parse underspecified mandate and attempt to confirm silently | Must ask for explicit confirmation/deny ambiguous authority | NOT_RUN |
| `MAN-010` | P0 | API | One successful purchase per mandate | Complete one authorized purchase then start another | No second success within one-success scope | NOT_RUN |
| `MAN-011` | P1 | API | Concurrent runs on same single-purchase mandate | Launch two runs against same mandate | Prevent overlapping authority or guard aggregate success atomically | NOT_RUN |
| `MAN-012` | P1 | UNIT | Currency scale parsing | Represent USD in cents not floating equality | Correct exact integer accounting | NOT_RUN |
| `CHK-001` | P0 | UNIT | Legitimate charger | Trusted canonical charger, qty 1, $29.99, one-time | ALLOW if active mandate and consistent total | NOT_RUN |
| `CHK-002` | P0 | UNIT | Signature same-price membership attack | Same merchant, same $29.99, subscription SKU | DENY PRODUCT_CATEGORY_MISMATCH + SUBSCRIPTION_NOT_ALLOWED | NOT_RUN |
| `CHK-003` | P0 | INTEG | Forged agent description | Agent labels subscription as charger; canonical checkout subscription | DENY independent of agent text | NOT_RUN |
| `CHK-004` | P0 | UNIT | Wrong quantity | 2 chargers under allowed total but mandate qty 1 | DENY QUANTITY_MISMATCH | NOT_RUN |
| `CHK-005` | P0 | UNIT | Shipping exceeds cap | Subtotal $36, shipping $6, strict under $40 | DENY on full verified total | NOT_RUN |
| `CHK-006` | P0 | UNIT | Tax exceeds cap | Subtotal $39, tax $2 | DENY total limit | NOT_RUN |
| `CHK-007` | P0 | UNIT | Wrong currency | Mandate USD, checkout EUR | DENY CURRENCY_MISMATCH | NOT_RUN |
| `CHK-008` | P0 | UNIT | Wrong merchant | Checkout belongs to non-allowed merchant | DENY merchant mismatch | NOT_RUN |
| `CHK-009` | P0 | UNIT | Wrong category but same price | A non-charger SKU at 2999 cents | DENY even if amount/merchant match | NOT_RUN |
| `CHK-010` | P0 | UNIT | Recurring hidden in line item | Recurrence true in canonical catalog but omitted listing | DENY | NOT_RUN |
| `CHK-011` | P0 | UNIT | Subtotal arithmetic tampering | Item lines sum differs from checkout subtotal | DENY inconsistent totals | NOT_RUN |
| `CHK-012` | P0 | UNIT | Total arithmetic tampering | Subtotal/tax/shipping differ from total | DENY inconsistent total | NOT_RUN |
| `CHK-013` | P0 | INTEG | Checkout revision after verification | Modify canonical checkout/version before charge | Invalidate/reverify; no old grant checkout substitution | NOT_RUN |
| `CHK-014` | P0 | INTEG | Same merchant and amount SKU swap at charge | Charge different item under identical merchant/amount/card | Merchant checkout-charge binding rejects mismatch | NOT_RUN |
| `CHK-015` | P0 | INTEG | Untrusted listing modifies canonical catalog | Inject listing content that claims new product classification | Canonical catalog unchanged; unauthorized request DENY | NOT_RUN |
| `CHK-016` | P0 | API | Unknown/stale checkout ID | Request checkout missing/expired at trusted store | Fail closed; no grant/card | NOT_RUN |
| `CHK-017` | P0 | API | Untrusted merchant response provenance | Bad auth/signature/service response | Fail closed | NOT_RUN |
| `CHK-018` | P1 | UNIT | Zero or negative quantity and price | Malformed Pydantic checkout | Validation error; never approved | NOT_RUN |
| `CHK-019` | P1 | UNIT | Exact category insufficient for attributes | Wrong wattage/connector if mandate has structured attributes | DENY on verified attributes | NOT_RUN |
| `CHK-020` | P1 | INTEG | Product replaced between listing and checkout | Catalog item ID points to different canonical SKU | Verifier uses canonical checkout, not listing | NOT_RUN |
| `GPH-001` | P0 | LIVE | Real Strands Graph exercised | Inspect runtime graph invocation, nodes and conditional transitions | Actual SDK Graph; not renamed custom loop | NOT_RUN |
| `GPH-002` | P0 | LIVE | Authentic prompt injection | Model sees poisoned MCP listing then calls wrong checkout tool | Actual model/tool trace; policy rejects wrong product | NOT_RUN |
| `GPH-003` | P0 | INTEG | Graph routes rejection to guardian | Reject prepayment wrong product | Guardian runs; no grant/card for rejected checkout | NOT_RUN |
| `GPH-004` | P0 | INTEG | Graph recovery finds legitimate candidate | First poisoned product then second compliant charger | Same unchanged mandate; second verified; one actual authorization max | NOT_RUN |
| `GPH-005` | P0 | INTEG | Quarantine malicious listing | Retry after detected malicious listing | Previously rejected source/SKU/checkout excluded | NOT_RUN |
| `GPH-006` | P0 | INTEG | Fresh context after injection | Observe subsequent shopper model context | No raw malicious instructions reinjected; only sanitized reason/exclusions | NOT_RUN |
| `GPH-007` | P0 | INTEG | Max candidate retry cap | All products bad | Stop at configured attempt cap; no infinite loop | NOT_RUN |
| `GPH-008` | P0 | INTEG | Graph execution/time caps | Mock node hangs or cycles indefinitely | Bounded timeout and max node executions | NOT_RUN |
| `GPH-009` | P0 | INTEG | Mandate expiry during recovery | Expire mandate between graph nodes | No new checkout/grant | NOT_RUN |
| `GPH-010` | P0 | INTEG | Stop during recovery | Activate run stop while retry node queued | No further authorized side effect | NOT_RUN |
| `GPH-011` | P0 | INTEG | No valid alternate found | Only scam candidates available | Safe terminal state; no pretend success | NOT_RUN |
| `GPH-012` | P0 | INTEG | Guardian cannot grant approval | Guardian suggests approving prohibited item | Deterministic DENY remains | NOT_RUN |
| `GPH-013` | P0 | INTEG | MCP outage has no bypass | Disconnect MCP while shopping | Pause/terminate safely; no direct-tool financial escape | NOT_RUN |
| `GPH-014` | P0 | API | Direct API request still protected | Call FastAPI payment operation without Graph/MCP | Same mandate and canonical checkout checks | NOT_RUN |
| `GPH-015` | P0 | INTEG | MCP tool poisoning | Tool result contains fake system or payment instruction | No expansion of mandate or unsafe spend | NOT_RUN |
| `GPH-016` | P1 | INTEG | Agent hooks reflect actual tool calls | Real model request triggers MCP tool | Before/after tool records match actual invocation IDs | NOT_RUN |
| `GPH-017` | P1 | INTEG | Guarded Graph restart | Crash/restart after node finished | No repeated card issuance; resumes only safe stages | NOT_RUN |
| `GPH-018` | P1 | INTEG | Cancel graph and underlying agent | Stop while model streams or tool runs | Worker cooperatively cancels; independent financial gate blocks | NOT_RUN |
| `PAY-001` | P0 | UNIT | Scope match single grant | Correct card/merchant/USD/2999/grant/run/version | Approve at most once | NOT_RUN |
| `PAY-002` | P0 | RACE | Two distinct concurrent authorizations | Simultaneous A and B against one grant | At most one distinct approval | NOT_RUN |
| `PAY-003` | P0 | API | Duplicate identical provider event | Replay same authorization ID and payload | Same committed decision; no new consumption | NOT_RUN |
| `PAY-004` | P0 | API | Identical event ID conflicting payload | Retry same provider ID with changed amount | Reject/flag conflict; never silently approve | NOT_RUN |
| `PAY-005` | P0 | UNIT | Wrong card on matching grant | Valid amount/merchant, wrong card token | Decline | NOT_RUN |
| `PAY-006` | P0 | UNIT | Wrong merchant on matching grant | Valid card/amount, wrong merchant | Decline | NOT_RUN |
| `PAY-007` | P0 | UNIT | Wrong amount on matching grant | Correct card, amount changed to 3000 | Decline | NOT_RUN |
| `PAY-008` | P0 | UNIT | Expired grant | Attempt after TTL/authoritative expiry | Decline | NOT_RUN |
| `PAY-009` | P0 | UNIT | Consumed grant | Second distinct authorization on consumed grant | Decline | NOT_RUN |
| `PAY-010` | P0 | API | Invalid ASA request authentication | Unauthenticated/invalid provider request | Reject, no grant consumption | NOT_RUN |
| `PAY-011` | P0 | INTEG | Valkey outage in ASA | Simulate Valkey unreachable | No approval; record and surface failure | NOT_RUN |
| `PAY-012` | P0 | INTEG | PostgreSQL unavailable for issuance | Disconnect persistent store while issuing grant | Fail closed; no untracked authority | NOT_RUN |
| `PAY-013` | P0 | INTEG | Authorization unknown outcome | Network times out after provider may have authorized | RECONCILING; no new card/charge until resolved | NOT_RUN |
| `PAY-014` | P0 | INTEG | Card issuance timeout idempotency | Provider creates card but reply drops | Reconcile/idempotency; no second card | NOT_RUN |
| `PAY-015` | P0 | API | Only SINGLE_USE card type created | Inspect every MVP Lithic create-card request | type SINGLE_USE; no reusable type paths | NOT_RUN |
| `PAY-016` | P0 | INTEG | New card after independent verification | Attempt checkout before verifier passes | No card issued until current verified authority | NOT_RUN |
| `PAY-017` | P0 | INTEG | One successful auth stops Graph buying | Receive authorization APPROVED | One-success scope consumed; no second product/card | NOT_RUN |
| `PAY-018` | P0 | INTEG | Authorization vs settlement semantics | Sandbox ASA approves without clearing | UI says authorized, not settled | NOT_RUN |
| `PAY-019` | P0 | INTEG | Checkout pre-block not card decline | Policy rejects before card creation | UI says blocked checkout; no fabricated ASA decline | NOT_RUN |
| `PAY-020` | P0 | INTEG | Sandbox vs simulator proof | Switch to simulator with no Lithic keys | Rail visibly Local Simulator; no invented card/provider IDs | NOT_RUN |
| `PAY-021` | P0 | RACE | Provider duplicate after run Stop | Approved event re-delivered after Stop effective | Same prior decision returned; no new distinct spend; history preserved | NOT_RUN |
| `PAY-022` | P1 | INTEG | Refund/force-post distinction | Card closed then later provider clearing/refund | Record/reconcile; do not claim closure reversed transaction | NOT_RUN |
| `PAY-023` | P1 | PERF | ASA deadline budget | Exercise adapter + hot path with configured provider payload | Measure latency against configured Lithic timeout; never LLM in path | NOT_RUN |
| `RST-001` | P0 | API | Human Stop This Purchase only target run | Stop run A while run B active | A revoked, B unaffected and usable | NOT_RUN |
| `RST-002` | P0 | API | User cannot stop another user run | Cross-user stop request | 403/404, target unchanged | NOT_RUN |
| `RST-003` | P0 | INTEG | Stop before agent starts | Stop queued run | No Graph shopping or card issuance | NOT_RUN |
| `RST-004` | P0 | INTEG | Stop during listing retrieval | Stop during MCP/product tool | Tool cancelled best-effort, no downstream payment permission | NOT_RUN |
| `RST-005` | P0 | INTEG | Stop during Guardian analysis | Stop while guardian investigating | No recovery/payment after Stop | NOT_RUN |
| `RST-006` | P0 | INTEG | Stop after checkout verification | Race stop before grant issuance | Stale verifier ALLOW cannot produce live grant | NOT_RUN |
| `RST-007` | P0 | INTEG | Stop after SINGLE_USE card issued | Issue card but stop before ASA | Valkey blocks next auth; provider closure attempted | NOT_RUN |
| `RST-008` | P0 | RACE | Atomic Stop wins over distinct ASA | Stop effective before ASA consumes grant | ASA declines | NOT_RUN |
| `RST-009` | P0 | RACE | Atomic ASA wins before Stop | ASA commits before stop barrier | Prior APPROVED retained; future distinct requests declined | NOT_RUN |
| `RST-010` | P0 | API | Double click Stop | Send same stop command twice | Idempotent operation and no reactivation | NOT_RUN |
| `RST-011` | P0 | INTEG | Stop persists over Pod restart | Stop then restart agent/payment/API Pod | No resumed graph or spending authority | NOT_RUN |
| `RST-012` | P0 | INTEG | Pending Valkey propagation | Stop recorded in PG, delay fast-path revocation | Do not claim spending revoked prematurely; issuance gated, repair/reconcile | NOT_RUN |
| `RST-013` | P0 | INTEG | Valkey rebuild retains Stop | Stop run then restart/wipe ephemeral Valkey with safe recovery | Fail closed until durable revocations rehydrated | NOT_RUN |
| `RST-014` | P0 | INTEG | Lithic closure fails | Provider close rejects/timeouts | Local authority remains blocked; card status PENDING/FAILED accurately shown | NOT_RUN |
| `RST-015` | P0 | INTEG | Stop after ASA approval | Approved payment then click Stop | Do not claim reversal; status authorized/reconcile separately | NOT_RUN |
| `RST-016` | P0 | INTEG | SSE disconnect during Stop | Browser refresh after stop request | Backend finishes stop; client recovers persisted events | NOT_RUN |
| `RST-017` | P1 | API | Stop cannot be called by MCP agent | Use only short-lived agent token | Forbidden; no human intent spoof | NOT_RUN |
| `RST-018` | P1 | API | Stopped run cannot auto-resume | Try restarting same graph via stale worker | Refuse; fresh human action needed | NOT_RUN |
| `EMG-001` | P0 | API | Global Kill stops all account runs | User has run A and run B; activate global Kill | Both revoked, neither can issue grants/approvals | NOT_RUN |
| `EMG-002` | P0 | API | Other users unaffected by global Kill | User A triggers global Kill; user B has active run | Only A suspended; B unaffected | NOT_RUN |
| `EMG-003` | P0 | RACE | Global generation invalidates old grants | Advance account generation while grants exist | Every old account grant declined at authorization | NOT_RUN |
| `EMG-004` | P0 | INTEG | Global Kill blocks new agent runs | Attempt fresh run after effective global stop | Denied until explicit human reenable/new authority | NOT_RUN |
| `EMG-005` | P0 | INTEG | Unfreeze does not resurrect old grants | Authenticated reenable after global stop | Old grants/cards remain invalid/closed; new mandate/action needed | NOT_RUN |
| `EMG-006` | P0 | INTEG | Many account cards closed | Several outstanding dedicated SINGLE_USE cards | Provider closure attempted for all; truthful per-card statuses | NOT_RUN |
| `EMG-007` | P0 | API | Repeated account Kill | Submit kill multiple times concurrently | Single effective transition, idempotent report | NOT_RUN |
| `EMG-008` | P0 | RACE | Global Kill versus simultaneous payment | ASA arrives same time as global Kill | Defined atomic ordering; no fresh approval after effective revoke | NOT_RUN |
| `EMG-009` | P1 | INTEG | Global Stop partial failure | Agent worker offline or Lithic unreachable | Financial gate remains closed; emit pending/failed acknowledgments | NOT_RUN |
| `EVT-001` | P0 | INTEG | All meaningful phases produce real events | End-to-end normal/attack/recovery run | Real graph/model/MCP/checkout/guardian/retry/rail states visible | NOT_RUN |
| `EVT-002` | P0 | API | Monotonic persisted event IDs | Emit multiple events for run, fetch timeline | Stable ordered IDs and durable records | NOT_RUN |
| `EVT-003` | P0 | API | Reconnect via Last-Event-ID | Disconnect after event 10; reconnect | Replay 11+ exactly/at-least once with client de-dupe; final authoritative state fetched | NOT_RUN |
| `EVT-004` | P0 | INTEG | SSE refresh does not start new Graph | Refresh/reconnect multiple times | No duplicate runs/card issuances | NOT_RUN |
| `EVT-005` | P0 | API | SSE authorization | Read events as unrelated user | Denied with no leak | NOT_RUN |
| `EVT-006` | P0 | INTEG | Transactional outbox recovery | Commit event then crash before SSE publish | Recovered/published after restart | NOT_RUN |
| `EVT-007` | P0 | UNIT | Sensitive-data redaction | Serialize event with private payment/model fields | No raw PAN/CVV/API key/tokens/hidden reasoning | NOT_RUN |
| `EVT-008` | P0 | INTEG | Payment state accurate | Authorization yes, settlement not confirmed | Dashboard does not say settled/charged | NOT_RUN |
| `EVT-009` | P0 | INTEG | Stop control scoped UI | Look at active Run Stop and global Kill | Separate user controls; distinct scopes clearly described | NOT_RUN |
| `EVT-010` | P1 | INTEG | Provider closure lifecycle in SSE | Emit request, pending, confirmed/failed | No fake success before provider confirmation | NOT_RUN |
| `EVT-011` | P1 | INTEG | Inference metadata truthful | Strands/Akamai model request during run | Provider, model, duration visible without internal reasoning | NOT_RUN |
| `INF-001` | P0 | INTEG | Two Kubernetes workers claim same run | Start two agent Pods competing on run lease | At most one active side-effect owner; stale fenced | NOT_RUN |
| `INF-002` | P0 | INTEG | Kubernetes restart mid-card issuance | Restart after provider may have created card | Reconcile; no duplicate purchase card | NOT_RUN |
| `INF-003` | P0 | INTEG | Kubernetes restart mid-Graph | Restart after verifier | No duplicate grant; persisted state guards resume | NOT_RUN |
| `INF-004` | P0 | INTEG | MCP service down | Stop MCP Service or network path | Agents pause/fail closed; no unrestricted fallback | NOT_RUN |
| `INF-005` | P0 | INTEG | Akamai inference down | Fail model call | Safe paused/failed Graph; existing ASA still deterministic | NOT_RUN |
| `INF-006` | P0 | INTEG | Valkey unavailable under load | Drop Valkey during ASA | No authorization approval from stale in-memory cache | NOT_RUN |
| `INF-007` | P0 | INTEG | K8s ingress SSE remains live | Ingress through TLS, long-running stream | No bad buffering, authentication intact, reconnect works | NOT_RUN |
| `INF-008` | P0 | INTEG | Provider webhook publicly reachable, protected | Send authenticated and unauthenticated callbacks | Valid requests pass; invalid rejected; DB not exposed | NOT_RUN |
| `INF-009` | P1 | INTEG | Secret references correct | Inspect K8s Secrets/service config | No credential in source or public frontend, provider config only backend | NOT_RUN |
| `INF-010` | P1 | INTEG | Rolling deploy keeps data safe | Roll out code while active runs exist | No duplicate payment, persistent data survives | NOT_RUN |
| `DEMO-001` | P0 | LIVE | Three-minute genuine attack story | Confirm, poison, block, guard, quarantine, recover, authorize | Real tool/Graph evidence, same-price merchant, one card max | NOT_RUN |
| `DEMO-002` | P0 | LIVE | Run Stop during active recovery | Run two independent demos, stop one mid-retry | One run stops; other continues; SSE shows enforcement | NOT_RUN |
| `DEMO-003` | P0 | LIVE | Global Kill demo | Launch two runs under same user, kill globally | Both stop with truthful card/rail statuses | NOT_RUN |
| `DEMO-004` | P0 | LIVE | Non-Lithic fallback truthful | Run demo without ASA enrollment/keys | Clearly labeled Local Rail Simulator; honest judge narration | NOT_RUN |

## Multi-step demo scripts (requires evidence, not a slide animation)

### D1 — Genuine attack, block, investigate, recover, approve

1. Human signs in; proposes and *confirms* exactly one USB-C charger, total **strictly under** $40, no subscription.
2. Launch a real Strands Graph. Shopper sees product listings via genuine authenticated MCP. Publish actual Graph/model/tool activity via persisted SSE.
3. Controlled poisoned listing genuinely causes wrong $29.99 recurring membership proposal at the **same merchant, amount and currency** as the charger.
4. Trusted merchant canonical checkout reveals wrong SKU and recurring flag. Deterministic backend rejects before creating card/grant. Guardian produces an evidence-linked advisory explanation.
5. Recovery controller excludes malicious source/SKU, retains exact confirmed mandate hash, starts fresh Strands context and obtains a real compliant $29.99 charger checkout.
6. Backend authorizes **one** narrow grant and **one new Lithic `SINGLE_USE` card** if configured. Merchant charges bound checkout; ASA/local simulator authenticates and atomically consumes grant. Distinguish *authorization* from clearing/settlement.
7. Timeline persists across browser refresh. Show outcome without claiming a simulated approval came from Lithic.

### D2 — Run Stop only

1. Create separate active run A and B for the same human (use distinct mandates or explicitly concurrency-safe setup).
2. A holds or is about to hold an unused grant; B remains active.
3. Human presses **Stop This Purchase** on A. Postgres stop intent, Valkey run revocation barrier, Graph cooperative cancellation, MCP spending denial and dedicated card closure each report independent status.
4. Attempt a new ASA authorization for A and assert decline. Verify B still behaves normally; no global suspension.
5. Refresh SSE, show persisted stop timeline. Explicitly explain previously approved authorizations cannot be undone.

### D3 — Global emergency stop

1. Create two active independent runs and unused cards/grants for one user; optionally a second account to test isolation.
2. Human presses **Emergency Kill Switch**. Account generation advances and all run grants become unusable; all active Graphs receive cancellation; pending SINGLE_USE cards closed where possible.
3. All *new distinct* authorization attempts decline after the effective barrier; the other account remains unaffected.
4. Report provider failures as pending/failed; don't fake closure. Clearing of already approved charges remains possible.

### D4 — Double-spend and uncertain outcome

1. Submit two distinct authorization IDs concurrently for the same grant; at most one approved. Redeliver the winning same event ID and ensure identical cached response.
2. Simulate a provider timeout after the external effect might already have occurred; preserve `RECONCILING`, prohibit issuing a second card or new charge, and recover provider status.
3. Restart a Kubernetes Pod in the middle and confirm the same invariant holds.

## Codex's required traceability annex (fill after repo inspection)

For each test ID, attach: `Owner | Current source path:function | Actual test path | Test command | Environment | Last execution result/evidence | Gap/fix | PR/branch`. Preserve existing tests and reference them rather than duplicating them. Tag cases blocked by service keys, ASA enrollment or cloud access appropriately.

## Explicit review concerns

- These test descriptions are desired behaviors. Specific internal methods (e.g., Valkey Lua, generation storage, outbox) are recommended methods, not proof that the current code already uses them. Equivalently safe implementation is acceptable with tests.
- Strands agent invocation cancellation and *Graph orchestration cancellation* are distinct. Verify installed SDK signatures; distributed worker cancellation requires application-level coordination.
- Stop effectiveness has a precise atomic fast-path boundary; do not promise that a click retroactively reverses transactions or that PostgreSQL and Valkey share one native transaction.
- The standalone simulator must exercise real deterministic rules and state transitions, not frontend-only animation.
- On actual provider rail, the card type is `SINGLE_USE` exclusively for MVP purchase cards, and any unauthorized charge test must distinguish pre-issuance block from a real ASA decline.
