# LEASH — Product and MVP Implementation Specification

Adopted October 10, 2026 from the team's **Product Evolution & MVP Architecture Directive**. This is the authoritative product direction; [AGENTS.md](../AGENTS.md) defines coding rules/path ownership; the synchronized [Leash-build-plan.md](../Leash-build-plan.md) assigns human and coding-agent tasks, dependencies, handoffs, execution gates, and readiness evidence. Conflicting flows/timing/fallbacks from the earlier hotel/gift-card plan are superseded. Compatible stack, ownership, and service boundaries are preserved. Keep these three documents synchronized when direction or ownership changes.

**Status: requirements and implementation plan, not a claim of completed functionality.** Sections 1–20 retain the adopted directive. Section 21 records the inspected repository; sections 22–25 adapt the directive to existing decisions, define enforcement boundaries, and identify work and dependencies. Suggested paths, endpoints, schemas, and integration behaviors below are targets until implemented and verified. No application code is changed by this documentation task.

The product's central proof is a $29.99 charger succeeding and an unrelated $29.99 subscription at the same merchant being blocked despite passing ordinary merchant/amount controls. Protection comes from human-confirmed intent, trusted itemized checkout facts, and deterministic enforcement. It must still work when the shopper is fully convinced by the malicious listing.

## 1. Updated Product Identity

### Product Name

**LEASH**

### New Tagline

**The firewall between what you tell your AI to buy and what it actually tries to purchase.**

### One-Sentence Description

LEASH is an intent-aware financial authorization layer that prevents autonomous AI agents from making purchases inconsistent with the user's original instructions, even when the attempted charge satisfies ordinary card spending limits.

### The Fundamental Problem

AI agents are increasingly capable of independently researching products, navigating shopping websites, and initiating purchases.

An agent may receive a legitimate instruction:

"Buy a USB-C laptop charger for under $40."

But while browsing, it encounters untrusted or malicious information that influences its behavior.

The agent might attempt to purchase:

- An unrelated subscription.
- A different product with the same price.
- An unauthorized recurring service.
- An item from an unexpected merchant.
- Additional products the user never requested.

Conventional card controls can enforce merchant restrictions, budgets, and spending limits.

However, two completely different purchases can have the same merchant, amount, and currency.

**A transaction can be financially permissible while being semantically unauthorized.**

This is the specific gap LEASH addresses.

### What LEASH Is Not

LEASH is not merely:

- An AI shopping assistant.
- A virtual card dashboard.
- A chatbot that evaluates suspicious purchases.
- An LLM-based fraud classifier.
- A generic spending-limit manager.
- Another system that approves anything beneath a dollar threshold.

Spending limits and merchant restrictions are necessary components, but they are not the main innovation.

### LEASH's Core Innovation

LEASH separates three things that conventional agent systems frequently conflate:

1. **User intent:** What the human actually authorized.
2. **Agent behavior:** What the shopping agent decided to attempt after encountering external information.
3. **Verified transaction:** What the merchant's trusted checkout data and payment authorization actually represent.

LEASH independently compares these three elements and prevents unauthorized differences from becoming approved payments.

The original human authorization remains authoritative.

Untrusted shopping content and the shopping agent itself cannot expand or rewrite that authorization.

---

## 2. The Signature Demonstration

The entire product should be designed around one memorable security demonstration.

### Original Instruction

The user enters:

"Buy a USB-C laptop charger for under $40. No subscriptions."

LEASH creates an immutable authorization record representing that instruction.

### Legitimate Purchase

The shopping agent locates an actual USB-C charger priced at $29.99.

The independently verified checkout information matches the user's authorization.

LEASH approves the transaction through the payment authorization layer.

### Malicious Purchase

The agent encounters an attacker-controlled product description containing instructions that attempt to redirect its behavior.

The compromised agent then attempts to purchase an unrelated $29.99 subscription from the same merchant.

Notice that:

- The merchant has not changed.
- The amount has not changed.
- The currency has not changed.
- The spending limit has not been exceeded.

A conventional merchant-and-budget policy could approve either transaction.

But LEASH must identify that the attempted subscription violates the original instruction.

**LEASH blocks the attempted purchase and records the evidence explaining why.**

The judge should visibly see:

ORIGINAL INTENT → AGENT MANIPULATION → UNAUTHORIZED CHECKOUT → PAYMENT BLOCKED.

This must be functional application behavior, not a scripted frontend animation.

The central demonstration must establish that LEASH detects a violation that ordinary merchant and amount controls cannot distinguish.

---

## 3. Core MVP Architecture

Preserve our selected stack:

- **Next.js / React / TypeScript:** Frontend and interactive demonstration.
- **Tailwind CSS + shadcn/ui:** Interface components.
- **FastAPI / Python:** Core backend and business logic.
- **AWS Strands Agents SDK:** Shopping agent orchestration, provenance capture, investigation tools, and security analysis.
- **Akamai hosted AI inference:** Model execution where supported.
- **Akamai Cloud / Linode:** Actual backend deployment and application infrastructure.
- **Lithic Sandbox:** Preferred external card authorization integration, subject to verified access and configuration.
- **SQLite or PostgreSQL:** Persisted purchase mandates, checkout verification, authorization attempts, and audit events.

Use integer minor currency units for payment calculations, not floating-point dollar amounts.

The codebase should remain a single repository with independently runnable frontend and backend.

### High-Level Execution Flow

```text
USER
  |
  | Original purchase instruction
  v
LEASH INTENT MANAGER
  |
  | Confirmed, immutable authorization
  v
STRANDS SHOPPING AGENT
  |
  | Browses potentially untrusted product content
  | Produces purchase proposal
  v
LEASH CHECKOUT VERIFIER
  |
  | Independently obtains trusted checkout facts
  | Compares actual item against authorized intent
  v
DETERMINISTIC POLICY ENGINE
  |
  +-- Match --> Short-lived payment authorization
  |
  +-- Mismatch --> Block / require new user approval
  |
  +-- Unknown --> Fail closed / request verification
  |
  v
PAYMENT AUTHORIZATION LAYER
  |
  | Lithic sandbox or clearly labeled local rail
  v
APPROVE / DECLINE
  |
  v
IMMUTABLE AUDIT EVENTS + LIVE UI
```

An AI agent must never have independent authority to bypass the deterministic approval layer.

---

## 4. Human Intent Mandates

Introduce a first-class object called a **Purchase Mandate**.

A Purchase Mandate represents the user's authorized transaction boundaries.

This is our internal product concept. Do not imply full compliance with Google AP2 or any other formal protocol unless actually implemented and verified.

### Required Fields

At minimum:

```text
mandate_id
user_id / demo_session_id
original_instruction
authorized_product_category
authorized_product_constraints
maximum_total_amount_minor
currency
allowed_merchants
maximum_quantity
allow_subscriptions
allow_recurring_payments
shipping_constraints (when applicable)
created_at
expires_at
user_confirmed_at
status
canonical_payload_hash
```

The exact schema can be improved by the engineering agent.

### Mandatory Properties

#### Explicit user confirmation

The original instruction may be interpreted into structured fields using AI.

However, the proposed mandate must be shown to and confirmed by the user before being considered authoritative.

Do not silently treat an LLM interpretation as authenticated user consent.

#### Immutability

Once confirmed, the mandate cannot be changed by:

- The shopping agent.
- Product pages.
- Retrieved documents.
- Tool outputs.
- Merchant descriptions.
- The guardian's language model.

A change requires a new user authorization or explicitly versioned replacement.

#### Tamper evidence

Generate a deterministic canonical representation and hash.

A cryptographic signature or authenticated server-side association can be added where useful. Do not call an ordinary hash a signature.

#### Time limitations

Mandates expire.

Expired mandates cannot approve payments.

#### Semantic specificity

Avoid reducing the mandate to only merchant and amount.

It must preserve meaningful constraints such as product type, subscription status, and quantity.

For the principal MVP demo, product-category verification must use an independently trusted product record, not only the shopping agent's interpretation of the product page.

---

## 5. Independent Checkout Verification

This is the single most important architectural improvement.

**LEASH must not trust the shopping agent to tell it what the agent is purchasing.**

The agent's report is evidence of attempted behavior, not proof of the actual checkout.

### The Trust Boundary

Treat the following as untrusted:

- Product descriptions.
- Website body text.
- Search results.
- Reviews.
- Embedded page instructions.
- Unverified tool output.
- Agent-authored cart summaries.

The shopping agent may read these sources, but none can directly authorize payment.

### Trusted Checkout Source

For the MVP, build a controlled sandbox merchant integration with a separate canonical catalog and checkout API.

The merchant fixture should return authoritative, structured checkout data, including:

```text
checkout_id
merchant_id
items:
  - sku
  - product_name
  - product_category
  - unit_price_minor
  - quantity
  - recurring
  - subscription
currency
subtotal_minor
tax_minor
shipping_minor
total_minor
checkout_expiry
```

The backend must retrieve this data through a trusted server-side interface or validate an authenticated merchant-supplied assertion.

Do not accept a browser-generated cart JSON object as independent proof.

The attack demonstration should allow malicious content on a product listing while keeping the canonical catalog and checkout service outside the attacker's control.

Explicitly document this trust assumption.

A merchant can misrepresent its own goods; LEASH does not solve compromised or dishonest merchant infrastructure in this MVP.

### Verification

Implement deterministic checks for:

1. Correct product category.
2. Correct quantity.
3. Allowed merchant.
4. Maximum total amount.
5. Currency.
6. Recurring payment restrictions.
7. Subscription restrictions.
8. Mandate expiration.
9. Checkout expiration.
10. Completeness and integrity of required trusted checkout fields.

An LLM may help interpret ambiguous product attributes or explain a discrepancy.

However, a positive LLM opinion alone must never authorize payment.

Where category identity cannot be verified reliably, the result must be `REQUIRES_REVIEW` or `BLOCKED`, not an automatic approval.

### Checkout Binding

Generate a canonical hash of the verified checkout details and associate it with:

- The mandate.
- The merchant.
- The amount and currency.
- The selected payment instrument or verified payment correlation.
- The expiration time.
- A unique authorization ID.

Any material checkout change requires re-verification.

This is how LEASH prevents a legitimate approved checkout from being reused to justify a different purchase.

---

## 6. Payment Authorization Firewall

The payment firewall must be authoritative and independent of the shopping agent.

### Preferred Integration: Lithic Sandbox

Use Lithic's documented Auth Stream Access mechanism when our sandbox account is correctly configured.

The backend receives authorization metadata, matches it to the approved purchase, and returns an actual authorization decision.

Important constraints:

- Authorization metadata does not generally include a complete itemized shopping cart.
- The independent checkout verification therefore occurs before the card authorization request.
- Lithic's documented maximum response window is six seconds, with a recommendation to respond within three seconds.
- No LLM inference belongs inside the real-time authorization decision path.

Use the current Lithic schemas instead of inventing webhook fields or response formats.

### Purchase-to-Payment Correlation

A critical engineering requirement is correlating a specific verified checkout with the subsequent authorization request.

A card authorization alone cannot prove which SKU was purchased.

Where practical, use a dedicated sandbox virtual card or another verified payment-instrument association for each pending purchase, combined with merchant, amount, currency, and a short validity window.

Do not assume Lithic forwards arbitrary checkout IDs through the card network.

Do not claim stronger item-level verification than our actual merchant integration and payment correlation support.

For the controlled merchant demo, the independently verified checkout should be bound to the same purchase attempt that initiates the simulated card authorization.

Document the precise guarantees and limitations.

### Authorization Grant

Following successful verification, create a short-lived, one-use payment grant.

Suggested fields:

```text
grant_id
mandate_id
verified_checkout_id
verified_checkout_hash
payment_instrument_id
merchant_id
authorized_amount_minor
currency
issued_at
expires_at
status
```

### Payment Decision Rules

Approve only if:

- The mandate exists and was confirmed by the user.
- The mandate remains valid.
- The checkout was independently verified.
- The checkout satisfies all mandatory constraints.
- The payment grant is valid and unused.
- The request matches the supported payment correlation fields.
- The merchant, amount, and currency match.
- No relevant security or integrity check has failed.

Otherwise decline or route to a new explicit user-approval flow.

### Security Requirements

- Fail closed when verification cannot be completed.
- Prevent payment grant replay.
- Make decision handling atomic.
- Preserve idempotency for retried requests.
- Cache the original response for duplicate authorization event IDs where appropriate.
- Ensure concurrent requests cannot spend the same one-use grant twice.
- Verify Lithic ASA request signatures according to its configured HMAC mechanism.
- Do not confuse signature-verification failure with an ordinary payment policy decline.
- Do not store or log raw card numbers or sensitive authentication values.
- Never expose API credentials in the frontend.
- Record decision latency and the actual decision source.
- Treat payment request type and authorization adjustments according to supported integration behavior.

A declined purchase must never be recorded as successfully paid.

### Sandbox Availability

First verify Lithic sandbox credentials, ASA enrollment, and reachable webhook setup.

If unavailable, implement the same policy interface through an explicitly labeled **Local Payment Rail Simulator**.

The local simulator must execute real backend authorization code and real state transitions—not simply return a hardcoded "declined" animation.

Clearly distinguish:

- Lithic sandbox authorization.
- Local simulated authorization.
- Real-world live card payments, which are out of scope.

Never misrepresent one as another.

---

## 7. AWS Strands Integration

Strands must be central to LEASH, not an ornamental dependency.

### Shopping Agent

A genuine Strands agent should:

1. Receive the user's purchase mandate as constrained context.
2. Search a controlled product environment.
3. Inspect product information.
4. Compare candidates.
5. Select a product.
6. Attempt checkout through a registered tool.
7. Produce a real trace of its actions.

The agent should sometimes encounter adversarial content as part of the demonstration.

Its attempted actions must be observable.

### Guardian / Investigation Agent

Introduce a separate guardian or forensic investigation capability powered by Strands.

Its responsibilities:

- Examine the original mandate.
- Analyze attempted checkout behavior.
- Review the shopping agent's tool-call history.
- Identify suspicious content that attempted to change agent behavior.
- Explain the difference between user intent and attempted action.
- Produce evidence-linked, structured findings.

It may recommend denial or review, but it does not independently have the authority to grant payment.

The final payment decision belongs to deterministic backend enforcement.

### Strands Hooks and Provenance

Use supported Strands lifecycle hooks, including relevant before/after tool-call events.

Capture:

```text
event_id
run_id
timestamp
agent_id
tool_name
tool_arguments (sanitized)
source_reference
tool_result_summary
trust_classification
proposed_action
policy_decision
```

Preserve where relevant content originated so we can explain how external data affected an agent's actions.

Hooks should help us:

- Observe tool executions.
- Trace untrusted data sources.
- Intercept sensitive checkout tool calls.
- Prevent a protected tool operation from bypassing policy.
- Build the visible attack investigation timeline.

**Important:** Hooks are defense in depth. Checkout tools and the payment backend must independently enforce authorization, even if another caller bypasses a particular hook.

### Agent Security Rules

External product descriptions and similar material are task data, not trusted instructions.

The shopping agent must not be able to:

- Rewrite a confirmed mandate.
- Issue arbitrary payment grants.
- Edit audit history.
- Claim successful payment without a real authorization result.
- Directly invoke an unrestricted payment provider API.

Limit available tools and permissions.

Do not build multiple agents solely for visual effect. The shopping and guardian/investigation responsibilities are enough to demonstrate substantial Strands integration.

---

## 8. Akamai Integration

Use Akamai meaningfully.

### Hosted Inference

Configure Strands with the hackathon-provided Akamai inference endpoint where compatible.

The documented workshop service supports OpenAI-compatible chat completions and tool calling.

Validate a real Strands tool-calling round trip rather than assuming SDK compatibility.

Keep credentials exclusively server-side.

Use a provider abstraction so the application can recover from an inference outage without rewriting the agent system.

### Cloud Deployment

Run the actual FastAPI backend, including the deterministic payment authorization logic, on Akamai Cloud/Linode.

Where practical, persist audit and mandate data on Akamai-hosted storage or database infrastructure.

The Akamai-powered system must be part of the live demonstration, not merely a service mentioned in the README.

### Separation of Responsibilities

Akamai inference supports:

- Shopping-agent reasoning.
- Agent investigation.
- Structured explanations and relevant analysis.

Akamai compute supports:

- FastAPI.
- Intent mandate persistence.
- Trusted checkout verification.
- Deterministic authorization decisions.
- Auditing and event delivery.

Do not allow an external model outage to convert a denied or unverified payment into an approval.

---

## 9. MVP User Interface

The UI must communicate LEASH's innovation visually within three minutes.

Prioritize a polished cybersecurity/FinTech experience rather than a generic chatbot.

### Required Screens / Views

#### A. Mission Control

The primary demonstration dashboard.

Show:

- Original user instruction.
- Confirmed authorization constraints.
- Agent status.
- Attempted purchase.
- Live security status.
- Approval or decline result.
- Recent activity.

The original instruction should stay visible while the agent operates.

#### B. Live Agent Activity

Display a readable sequence:

- Searching products.
- Reading listing.
- Selecting candidate.
- Attempting checkout.
- Verifying trusted cart.
- Applying payment controls.
- Final transaction decision.

Events should reflect actual backend tool calls and authorization state changes.

Use server-sent events or another suitable streaming method.

Do not manufacture "live agent" events entirely inside React.

#### C. Purchase Comparison

The most important visual component.

Show the original authorization beside the actual attempted checkout.

Example:

| Attribute | User Authorized | Agent Attempted |
|---|---|---|
| Item | USB-C charger | Premium subscription |
| Amount | Under $40 | $29.99 |
| Merchant | Approved store | Same store |
| Recurring | No | Yes |
| Verdict | — | BLOCK |

Highlight the precise reason the attempted purchase was unauthorized.

#### D. Security Incident Timeline

Show the chain of events:

1. User authorized charger.
2. Agent encountered untrusted product content.
3. The content attempted to redirect behavior.
4. Agent proposed unauthorized checkout.
5. Trusted checkout revealed a subscription.
6. Policy engine blocked approval.
7. Payment authorization was declined.

Allow inspection of the relevant suspicious source and tool events.

#### E. Transaction History

Show genuine application results:

- Approved purchases.
- Blocked attempts.
- Verification failures.
- Expired authorizations.
- Provider or simulator used.
- Decision latency.

Do not label blocked attempts as completed transactions.

#### F. Attack Lab

Include a demo-focused attack control.

The presenter can select a legitimate scenario or a controlled adversarial product listing.

The attack is executed against the real shopping agent with the existing mandate unchanged.

This must not silently override backend outcomes.

The purpose is to demonstrate that LEASH remains effective when the agent's behavior changes.

---

## 10. Required MVP Scenarios

All scenarios below are part of the MVP and should have repeatable integration tests.

### Scenario 1 — Legitimate Purchase

- User authorizes a charger below $40.
- Agent selects a qualifying charger.
- Trusted checkout matches mandate.
- Policy engine issues a valid authorization grant.
- Payment sandbox/simulator approves.
- Audit trail records success.

Expected: APPROVED.

### Scenario 2 — Same Merchant, Same Amount Attack

- User authorizes a charger below $40.
- Agent encounters malicious product content.
- Agent attempts an unrelated subscription costing $29.99.
- Merchant and amount remain permissible.
- Trusted checkout identifies an unauthorized product and/or recurring obligation.
- No valid payment grant is issued for the malicious checkout.
- Payment attempt is blocked.

Expected: BLOCKED.

This is the signature demonstration and must receive the greatest attention.

### Scenario 3 — Above-Budget Purchase

- Agent attempts a legitimate category item above the approved total.
- Policy rejects it even if the agent believes it is desirable.

Expected: BLOCKED.

### Scenario 4 — Missing or Untrusted Checkout Details

- The agent proposes a purchase.
- The independent checkout source is unavailable or required information is missing.

Expected: REQUIRES_REVIEW or BLOCKED.

Never approve based solely on the shopping agent's confidence.

### Scenario 5 — Expired or Replayed Approval

- Previously valid authorization is expired or reused for a distinct transaction.
- Policy rejects the attempt.

Expected: BLOCKED.

### Scenario 6 — Authorized Purchase After an Attack

- The malicious purchase fails.
- The user retains the original mandate.
- The agent finds a compliant product or the user selects one.
- That purchase completes normally after verification.

Expected: APPROVED.

This scenario demonstrates that LEASH is not merely an aggressive blocker. It enables legitimate autonomous commerce while enforcing boundaries.

---

## 11. Core Backend Domain Models

Design schemas around domain boundaries rather than mixing everything into one JSON blob.

Recommended concepts:

```text
PurchaseMandate
AgentRun
AgentTraceEvent
ProductListing
CanonicalProduct
CheckoutSnapshot
CheckoutVerification
AuthorizationGrant
AuthorizationAttempt
PaymentDecision
SecurityIncident
AuditEvent
```

Use explicit enums and validated schemas for decision states.

Suggested checkout decisions:

```text
VERIFIED
BLOCKED
REQUIRES_REVIEW
```

Suggested payment outcomes:

```text
APPROVED
DECLINED
ERROR
```

Suggested authorization-grant states:

```text
ISSUED
CONSUMED
EXPIRED
REVOKED
```

Do not allow arbitrary model-generated strings to become official payment statuses.

Maintain an append-only event history for the demonstration.

Do not require blockchain.

---

## 12. API Design

Inspect the existing FastAPI structure and adapt appropriately.

Recommended operations:

```text
POST /api/mandates
GET  /api/mandates/{id}

POST /api/agent-runs
GET  /api/agent-runs/{id}
GET  /api/agent-runs/{id}/events

POST /api/checkouts/verify
GET  /api/checkouts/{id}

POST /api/payments/authorize
POST /api/payments/lithic/asa

GET  /api/incidents/{id}
GET  /api/transactions
GET  /health
```

A local demo payment authorization and Lithic ASA must share the same domain-level policy engine but have distinct provider adapters.

Ensure untrusted clients cannot directly mint grants or invoke privileged operations merely by calling a public endpoint.

API naming can change, but the separation of responsibilities must remain.

---

## 13. Testing Requirements

Security correctness is more important than a large quantity of superficial features.

Build automated tests for:

#### Mandates

- Structured interpretation requires confirmation.
- Confirmed mandates cannot be edited by the agent.
- Expired mandates cannot approve payments.
- Invalid amounts and currencies fail validation.
- Canonical hashes change when meaningful authorization fields change.

#### Checkout Verification

- Legitimate product passes.
- Wrong product category fails.
- Subscription prohibition is enforced.
- Unexpected merchant fails.
- Wrong quantity fails.
- Excessive amount fails.
- Altered checkout hash fails.
- Missing checkout evidence fails safely.
- Changes after verification invalidate the grant.

#### Payment Enforcement

- Matching authorization passes.
- Missing grant declines.
- Expired grant declines.
- Replayed grant declines.
- Different transaction cannot reuse the same grant.
- Concurrent authorization attempts cannot both consume one grant.
- Duplicate delivery of the same authorization event is idempotent.
- Invalid signature is rejected.
- Provider outages do not cause approval.
- Authorization decision does not invoke an LLM.

#### Agent Security

- Product-page instructions cannot modify the mandate.
- Direct checkout-tool calls cannot bypass backend verification.
- Agent manipulation is visible in the trace.
- Agent claims of success cannot create a paid transaction.
- The independent authorization layer blocks unauthorized purchases even if the shopping agent does not recognize the attack.

#### End-to-End

- Legitimate purchase completes.
- Same-merchant/same-amount attack is blocked.
- Blocked incident appears in the audit timeline.
- A subsequent compliant purchase succeeds.
- Reloading the UI preserves the real application state.

Where possible, use tests with intentionally manipulated agent outputs rather than relying on the model to make the same mistake every run.

Use reproducible adversarial fixtures and independently test the policy engine.

---

## 14. Three-Minute Hackathon Demonstration

Optimize all development decisions around this walkthrough.

### 0:00–0:20 — The Problem

Display:

"Buy a USB-C laptop charger for under $40. No subscriptions."

Explain:

"AI can shop for you now. But what happens when a website tricks it into spending your money on something you never wanted?"

Show the confirmed mandate.

### 0:20–0:45 — A Legitimate Purchase

Run an authorized shopping flow.

Show:

- Genuine agent activity.
- Trusted checkout verification.
- Actual backend authorization.
- Green approved result.

### 0:45–1:30 — The Attack

Switch to the controlled malicious listing.

The agent encounters attacker-controlled content and attempts an unauthorized checkout.

Show the original user mandate remains unchanged.

### 1:30–2:00 — The Financial Firewall

Display both purchases side by side.

Same merchant.

Same amount.

Different item and recurring obligation.

LEASH identifies the mismatch and declines the authorization.

This is the centerpiece of the presentation.

### 2:00–2:35 — Forensic Explanation

Open the incident timeline.

Show:

- The content that attempted manipulation.
- The agent's resulting checkout action.
- Trusted checkout evidence.
- Violated authorization constraints.
- The actual payment decision.

Show that the investigation comes from real Strands events and backend records.

### 2:35–3:00 — Sponsor Technology & Conclusion

Explain:

- Strands powers agent tool use and security investigation.
- Akamai powers inference and deployed backend execution.
- The financial authorization layer enforces user intent using independently verified checkout data.

Conclude:

"LEASH doesn't just limit how much AI can spend. It makes sure the AI is buying what you actually asked for."

Keep the blocked-purchase result visible at the end.

---

## 15. Engineering and Team Coordination

Assume a three-person team.

### Developer 1 — Frontend / Full-Stack

Owns:

- Next.js user interface.
- Mission Control dashboard.
- Real-time event visualization.
- Side-by-side purchase comparison.
- Incident timeline.
- Integration with backend APIs.
- Final presentation flow.

### Developer 2 — AI / Agents

Owns:

- Strands shopping agent.
- Guardian/investigation agent.
- Tool interfaces.
- Hooks and provenance.
- Akamai model integration.
- Adversarial scenarios.
- Structured investigation output.

### Developer 3 — Finance / Payment Enforcement

Coordinates finance/security validation with the existing path owners in section 24:

- Purchase mandates.
- Financial authorization rules.
- Trusted checkout schemas.
- Payment grant issuance.
- Sandbox payment integration.
- Concurrency/idempotency tests.
- Transaction audit logic.

Share API contracts and data schemas early to avoid integration conflicts.

Codex and Claude Code may work in separate areas, but neither should independently redefine the domain schemas.

The repository's documentation must provide consistent definitions for agents, state transitions, and API contracts.

---

## 16. Implementation Priority

All critical elements belong to the MVP.

Sequence implementation by dependency, not by perceived novelty.

### Phase 1 — Security Core

- Mandate creation and confirmation.
- Trusted catalog and checkout verification.
- Deterministic policy engine.
- Payment grants.
- Local authorization simulator.
- Positive and negative unit tests.

### Phase 2 — Actual AI Agent

- Strands shopping agent.
- Agent tools and hooks.
- Akamai inference integration.
- Live traces.
- Guardian investigation.

### Phase 3 — Payment Integration

- Lithic sandbox configuration if available.
- Authorization responder.
- Correlation and idempotency.
- Real sandbox approve/decline tests.
- Latency measurements.

### Phase 4 — Presentation Interface

- Mission Control.
- Side-by-side intent comparison.
- Live event stream.
- Attack Lab.
- Incident evidence panel.
- Transaction history.

These phases can proceed in parallel after the shared contracts are established.

Do not postpone integrating the frontend, backend, and payment decisions until the end.

### Final Stability Pass

Before the demo:

- Run all tests.
- Validate the deployed Akamai service.
- Confirm real agent tool calls.
- Verify a normal purchase and blocked attack.
- Reset reproducible demo fixtures.
- Measure authorization latency.
- Confirm that the UI cannot show success when the backend failed.
- Rehearse the complete presentation repeatedly.
- Keep a clearly labeled pre-recorded demonstration available only as an outage fallback, not as a substitute for claiming live functionality.

---

## 17. Non-Negotiable Security Invariants

These must appear prominently in `AGENTS.md`.

**Invariant 1:** Only the user may create or confirm purchase authority. An agent cannot enlarge it.

**Invariant 2:** Agent observations and untrusted web content cannot substitute for independently verified checkout data.

**Invariant 3:** Every approved payment must correspond to a confirmed mandate, verified checkout, and valid authorization grant.

**Invariant 4:** An LLM cannot override deterministic financial authorization rules.

**Invariant 5:** Failed, incomplete, expired, unverifiable, or inconsistent authorizations must not result in an approved payment.

**Invariant 6:** A grant is short-lived, scoped, and single-use, with idempotent handling of duplicate delivery.

**Invariant 7:** Sensitive financial tools enforce their own authorization checks regardless of agent hooks.

**Invariant 8:** The system must never represent a local simulation as a real card-network authorization.

**Invariant 9:** The audit interface reflects genuine persisted backend events, not fabricated security outcomes.

**Invariant 10:** The signature same-merchant/same-amount attack must be blocked even if the shopping agent is fully convinced the malicious purchase is appropriate.

---

## 18. Competitive Positioning

Research and product descriptions must acknowledge that existing companies and protocols already provide agent payment controls.

Relevant references include:

- Google Agent Payments Protocol (AP2): https://github.com/google-agentic-commerce/AP2
- AgentsPay: https://agentspay.ai/
- Skyfire: https://docs.skyfire.xyz/docs/features
- Lithic Authorization Stream Access: https://docs.lithic.com/docs/auth-stream-access-asa
- Strands Hooks: https://strandsagents.com/docs/user-guide/sdk/agents/hooks/
- Akamai Hack Midwest Inference: https://github.com/akamai-developers/akamai-workshop-hackmidwest/blob/main/docs/inference.md

Do not claim we invented agent payment restrictions, purchase mandates, or the concept of linking payments to intent.

Our differentiation is the integrated, attack-aware implementation:

**Original authorization → observable agent behavior → independently verified itemized checkout → deterministic payment enforcement → auditable explanation.**

The principal demonstration should show a semantic purchase violation that cannot be detected using merchant and amount restrictions alone.

---

## 19. Definition of MVP Complete

The LEASH MVP is complete when the following are true:

- [ ] A user can create and confirm a purchase mandate.
- [ ] The shopping agent runs through AWS Strands.
- [ ] The shopping agent can encounter controlled adversarial product content.
- [ ] The system records actual agent/tool events.
- [ ] A trusted checkout service provides independent itemized facts.
- [ ] The verifier enforces the original purchase constraints.
- [ ] A valid purchase receives a scoped authorization grant.
- [ ] A malicious purchase cannot obtain or reuse an authorized grant.
- [ ] The payment backend approves or declines through a real policy engine.
- [ ] Lithic sandbox integration works if verified credentials/access permit; otherwise the local rail is clearly labeled.
- [ ] The signature same-merchant/same-amount attack is blocked.
- [ ] A legitimate purchase is approved.
- [ ] A blocked attack produces an evidence-based explanation.
- [ ] Audit history survives page refresh.
- [ ] FastAPI actually runs on Akamai Cloud.
- [ ] Akamai inference is exercised through Strands when the endpoint is compatible and available.
- [ ] Authorization enforcement succeeds without an LLM call in its critical path.
- [ ] Tests verify major trust boundaries and replay defenses.
- [ ] The entire demonstration fits inside three minutes.

There is no need to build a public consumer banking platform, integrate dozens of merchants, support live customer funds, or obtain regulatory approval for a hackathon MVP.

But the core financial security mechanism must be genuine.

---

## 20. Final Direction to All Coding Agents

Treat this as the new authoritative version of LEASH.

Do not revert to the older interpretation of LEASH as an AI spending-limit product.

The single most important product requirement is:

**LEASH must demonstrate that it can stop an AI agent from buying an unauthorized item even when the amount and merchant are otherwise permitted.**

The single most important engineering requirement is:

**That protection must derive from an immutable user mandate, independently trusted checkout data, and deterministic payment enforcement—not an LLM merely deciding a purchase feels suspicious.**

The single most important presentation requirement is:

**Judges must see a legitimate purchase succeed, an agent be manipulated, an unauthorized purchase get blocked, and a traceable explanation of exactly why.**

Make the product visually exceptional, technically credible, and fully functional.

Documentation alignment establishes the shared direction. Preserve compatible existing work and implement through the agreed ownership lanes and contracts after this update is summarized.

---

## 21. Inspected repository and implementation status

Snapshot: October 10, 2026, local `main` checkout at `a27cea5` before this documentation update; working tree was clean. This describes the inspected checkout, not other developers' branches or external deployments.

| Evidence | Already present | What this does not establish |
|---|---|---|
| `api/main.py` | FastAPI application, localhost:3000 CORS configuration, `GET /health` | No mandate, checkout, payment, authorization, persistence, provenance, or streaming routes |
| `api/pyproject.toml`, `api/uv.lock`, `api/.python-version` | Python 3.12+ project; FastAPI and Strands with OpenAI extra declared/locked | No actual agent, provider setup, hooks, smoke test, or guardian |
| `web/package.json`, `web/tsconfig.json` | Next.js 16.4.0, React 19.3.0, TypeScript strict mode, pnpm scripts | No LEASH product screens |
| `web/components.json`, `web/src/app/globals.css`, `web/src/components/ui/` | Tailwind/shadcn configuration; button, card, dialog, tabs primitives | Preserve these; they are not a completed financial dashboard |
| `web/src/lib/api.ts` | Public backend URL setting and `/health` fetch helper | No authenticated product API client or SSE; starter home does not invoke the helper |
| `web/src/app/page.tsx`, `web/src/app/layout.tsx` | Starter home and layout | No actual financial/security outcomes |
| `web/AGENTS.md`, `web/README.md` | Next.js guidance and starter README | Read installed Next.js documentation before web changes; README does not describe LEASH |
| `api/README.md` | Empty file | No backend architecture/setup guide |
| Original root `AGENTS.md`, `Leash-build-plan.md` | Legacy ownership, architecture sketches, timeline | Planned services are not implemented services |

Absent at inspection: root `README.md`, root `pyproject.toml`, `services/`, `shared/`, `db/`, `tests/`, `infra/`, `.github/`, `.env.example`, Compose, Dockerfiles, generated `web/src/lib/api-types.ts`, SQL migrations, and provider adapters. `docs/LEASH_SPEC.md` is created by this task. Do not move `api/` or create empty directories merely to resemble the old diagram.

No external account, credential, ASA enrollment, public responder, managed database, Object Storage bucket, Valkey deployment, or Akamai application deployment was verified. Local environments and SDK declarations do not prove integration capability. Secrets were not read or printed.

`docker compose config` reports **“no configuration file provided: not found.”** Compose boot cannot currently be confirmed. No service test suite is present. Documentation checks are not passing security tests or a deployed end-to-end run.

## 22. Architecture conflicts and adopted resolutions

These are conflicts with prior plans; there is no implemented payment system to discard in this checkout.

| Previous assumption | Conflict | Adopted MVP resolution |
|---|---|---|
| Hotel versus $400 gift card at another merchant | Ordinary merchant/amount controls detect it | Charger versus subscription, both $29.99, same merchant/currency; legacy scenarios may remain additional regressions |
| Agent-authored cart is checkout truth | Agent can invent category or omit recurrence | API retrieves canonical checkout facts through a trusted merchant connection |
| Guardian `approve` directly leads to card issuance | Positive LLM output becomes financial authority | Mandatory deterministic verification gates grants; guardian explains/recommends block/review |
| Mandate contains category/budget but no quantity/recurrence/product constraints | Insufficient semantic consent | Add confirmed semantic constraints, quantity/scope and canonical payload hash; retain raw instruction, versions and planned Ed25519 signing |
| `PATCH` edits active mandate in place | Historical authority may be overwritten | Human-confirmed replacement version, immutable old payload, serialized revocation of old unused grants |
| `cart_hash` covers agent-authored cart | Hashing untrusted assertions is not independent proof | Preserve proposal hash separately; grant binds trusted checkout snapshot/hash |
| Card + descriptor/MCC + amount ceiling | Same-merchant SKU substitution and currency/exact-total gaps | Protected merchant checkout/instrument correlation, exact amount/currency and current mandate/version/hash |
| Respond then set used/idempotency keys | Concurrent double approval and replay on lost writes | Atomic consume/cache/event commit before an approval response |
| Stripe-equivalent two-second ASA timing | Wrong provider contract | Lithic six-second maximum, recommended under three; measure internal under-100-ms target |
| Inferred ASA payload/signature format | Fixture may diverge from actual integration | Current official schemas/SDK and configured HMAC setup; normalize via provider adapter |
| Stripe or direct Lithic-shaped request fallback | Unverified access and misleading network claim | Labeled local rail executing real domain policy/state transitions with a distinct adapter |
| `services/api/`, `/healthz` described as existing | Actual backend is `api/` with `/health` | Preserve working starter; choose added paths/routes deliberately |
| Shared contracts already “frozen” | Files were absent at initial inspection; Rishi accepted the initial R01 baseline after compatibility review | Preserve dedicated-PR/all-three-review rule for subsequent changes |
| Finance role interpreted as path reassignment | Conflicts with existing lanes | Cameron validates rail/security; Rishi retains product API/domain/schema ownership |
| Approving integration stubs | Fake verdict/card mistaken for protection | Label test stubs; never issue demo grants without completed trusted verification |
| Dashboard/audit assumed complete | UI is a starter | Six views backed by persisted events; distinguish grant, authorization and paid state |

Retain compatible decisions: selected stack, Akamai inference/compute, Lithic sandbox preference, PostgreSQL/API-only durable writes, Valkey fast path/events, human-only authority, integer cents, UTC timestamps, canonical JSON, planned Ed25519, thin stateless MCP, provenance snapshots, merchant/MCC controls, kill switch/revocation, one-use instruments, once-only card delivery, no logged financial secrets, receipts, and simulation labels. These are retained decisions; current implementation status is recorded in section 23.8; the initial inspection is historical.

## 23. Adapted implementation contract

This defines requirements for the first joint schema/API review. R01 now implements a concrete initial candidate in the shared models/events, documented in [api/README.md](../api/README.md); Rishi authorized the initial baseline; future contract changes retain coordinated review. Semantic requirements are mandatory; owners review final fields and avoid independently redefining domain contracts in each service.

### 23.1 Data conventions and field mapping

USD MVP money is nonnegative integer cents. Reject floats, booleans masquerading as integers, unsupported currencies, negative/inconsistent totals, nonpositive quantities, empty required metadata, and naive timestamps. Provider wire models keep their official names; normalized LEASH fields use `_cents`. The directive's `_minor` examples mean integer minor units, not required breaking renames.

| Directive concept | Preserve/adapt legacy name | Required meaning/addition |
|---|---|---|
| `mandate_id` | Mandate `id`; references `mandate_id` | Stable identity with immutable version/hash |
| `original_instruction` | `description` | Raw human text, never rewritten from listing content |
| `authorized_product_category` | `category` | Trusted product category; MCC is not SKU category |
| `maximum_total_amount_minor` | `max_cents` | Confirm comparator: “under $40” means `< 4000` (maximum 3999 cents), unless human explicitly confirms inclusive $40 |
| `allowed_merchants` | `merchant_allowlist` | Configured stable merchant identities |
| `expires_at`, `user_confirmed_at` | `valid_until`, `approved_at` | UTC validity and authenticated human confirmation |
| Semantic constraints | New product/quantity/subscription/recurring/shipping fields | Explicit displayed defaults; uncertainty is review/block |
| Tamper evidence | Add `canonical_payload_hash`; retain planned `signature` | Hash and cryptographic signature have distinct meanings |
| Trusted checkout money | `unit_cents`, `subtotal_cents`, `tax_cents`, `shipping_cents`, `total_cents` | Canonical SKU/category/recurrence, quantity, merchant, currency, checkout/source identity and expiry |
| Grant total | `authorized_amount_cents` | Exact verified total, not merely spending ceiling |
| Proposed Cart / `cart_hash` | Preserve as proposal evidence | Separate trusted CheckoutSnapshot and verified hash |
| PreApproval | Extend/adapt to AuthorizationGrant | Unique grant, mandate version/hash, checkout ID/hash, instrument/correlation, merchant, exact amount/currency, validity and status |
| Verdict / GuardianFindings | Guardian findings/recommendation | Advisory `block`, `review`, or `no_findings`; evidence/checks and structured nullable model metadata; never approves |
| PaymentRequest | Proposed purchase lifecycle | Separate grant issuance from actual authorization/paid result |
| ProvenanceEvent / AuthorizationDecision | Extend with trace/correlation/rail metadata | Preserve source hashes/excerpts, latency, actual decision source and event identity |

Retain existing planned prefixes `usr_`, `agt_`, `mnd_`, `crt_`, `pay_`, `run_`; agree any additional prefixes. Use UTC-aware ISO 8601. Implement one shared canonical JSON convention (`json.dumps(data, sort_keys=True, separators=(",", ":"))`) and shared hash helpers. Agree versioned payloads/item ordering before freezing.

Hash all meaningful immutable authority/checkout fields: identity, version, original instruction, semantic constraints, currency, scope, source identity and validity as applicable. Exclude mutable lifecycle state from immutable payloads; associate confirmation/signature and append-only state events with the payload. Checking one agent-supplied hash against another agent-supplied payload is not independent verification. Preserve planned server-held Ed25519 demo signing; do not claim device-passkey or AP2 compliance.

### 23.2 Domain records and lifecycle

The concepts in section 11 remain separate records: PurchaseMandate (confirmed authority), AgentRun (actual execution), AgentTraceEvent (sanitized source/tool evidence), ProductListing (untrusted presentation), CanonicalProduct (trusted catalog), CheckoutSnapshot (immutable itemized facts), CheckoutVerification (checks/binding), AuthorizationGrant (scope/instrument/validity), AuthorizationAttempt/PaymentDecision (actual request/outcome), SecurityIncident (linked evidence/violation), and AuditEvent (append-only history). All carry appropriate session/user ownership and correlation identifiers.

Mandate: proposed -> human-confirmed active -> revoked/expired/superseded. A draft grants no authority. Replacement requires explicit human confirmation and serialized old-grant invalidation while historical payloads remain immutable.

Verification: `VERIFIED`, `BLOCKED`, `REQUIRES_REVIEW`. Missing/untrusted evidence or unknown category cannot become verified because the LLM or a human clicked approve. Clarified/changed authority requires new confirmation and fresh verification.

Grant: `ISSUED` -> `CONSUMED`, `EXPIRED`, `REVOKED`; terminal states never return to issued. Expiry is the minimum of configured short grant lifetime, mandate expiry, and checkout expiry. The old 30-minute TTL is an upper-bound planning value. Duplicate issuance for one purchase must be idempotent or revoke the prior unused grant.

Payment: validated `APPROVED`, `DECLINED`, `ERROR`, with reason codes. Authentication/provider/state-store failure is an error without approval, distinct from policy decline. `BLOCKED` is an attempted purchase/verification result; an issued grant is not paid. Authorization is not settlement. Actual provider decline overrides a previously issued grant; agent text cannot create success.

For “buy a charger”, confirm successful purchase cardinality explicitly: default one qualifying checkout, quantity one. Multiple grants/purchases must not exceed that scope. A blocked attempt consumes no purchase authority; recovery uses an unchanged mandate and fresh verified checkout/grant. Repeated successful demo runs use isolated sessions/new confirmed mandates or a visible labeled reset; never secretly erase consumed-grant state. Attack/recovery uses the same unchanged mandate.

### 23.3 Trusted merchant verification

Cameron's fixture exposes attacker-editable listings separately from canonical catalog and checkout interfaces. Rishi and Cameron agree service authentication/route names; none exist yet. The shopper selects SKU/quantity and proposes an attempt. It cannot set trusted category, prices, recurring flags, merchant identity or final totals.

The API uses a configured merchant connection or validates an authenticated assertion, resolves session/checkout ownership, obtains authoritative facts server-side, validates typed fields, recomputes totals and persists an immutable snapshot. Reject unknown SKU, missing metadata, inconsistent charges, cross-session checkout IDs, invalid source authentication, expired checkout, or altered hashes. An agent-selected URL must never become the trusted verification endpoint.

Enforce category, product/shipping constraints, quantity/scope, merchant allowlist, total including tax/shipping, currency, subscription/recurring restrictions, mandate confirmation/version/validity, checkout validity and completeness/integrity. Unverifiable attributes result in review/block. Record observed and permitted values, result and evidence reference for every check. Hard checks precede investigation; guardian findings never overwrite deterministic results.

Only a `VERIFIED` record matching current confirmed authority can mint a grant. Recheck the authoritative checkout revision and freeze it for payment. Material item/quantity/total/currency/recurrence/merchant/expiry/fulfillment changes invalidate verification and unused grants; fresh verification creates a new snapshot/binding, not an in-place hash rewrite.

### 23.4 Checkout-to-payment correlation and limits

The trusted merchant binds purchase-attempt identity + checkout ID/hash + grant/instrument server-side. Its protected charge operation loads that association, rejects another checkout or changed revision, and initiates authorization for the exact frozen checkout. A caller cannot charge the subscription with a valid charger grant. This protection is mandatory even if a hook is absent or an endpoint is called directly.

The local adapter resolves authenticated internal checkout correlation server-side, rather than trusting caller-supplied IDs/hashes. Lithic ASA generally supplies payment metadata, not SKU facts. Correlate a dedicated instrument/program with the verified purchase and match supported merchant identity/descriptor, MCC, exact normalized amount/currency and time window. Never invent a card-network checkout-ID field.

**Guarantee:** within the trusted controlled merchant, canonical facts, frozen checkout, protected charge interface and grant/instrument association bind authorization to that verified checkout. LEASH rejects invalid authority, missing grants, incompatible metadata and distinct replay.

**Limitation:** presenting the card outside that protected integration at the same merchant/amount/currency can be indistinguishable at ASA. A dedicated card alone does not solve SKU substitution. Do not claim general network SKU enforcement, protection from dishonest canonical catalogs, compromised trusted merchant infrastructure, or support for arbitrary merchants. Same-amount subscription reuse of a legitimate instrument must visibly fail at the protected merchant correlation boundary; do not portray an ASA-only SKU check that the provider cannot perform. If verification blocks before ASA, show “blocked before payment”, without inventing a network callback. A demonstrated local malicious authorization with no valid grant must produce a real deterministic decline.

### 23.5 Atomic rail and persisted evidence

Use one pure domain decision engine with distinct local/Lithic adapters. It never invokes a model. A supported initial authorization requires current confirmed authority, trusted verification binding, valid unused grant, no kill switch/integrity failure, supported request type, matching correlation/instrument/merchant/MCC, **exact** amount/currency and valid expiry. Unsupported adjustments, incremental/partial authorizations, reversals or other request types cannot enter the ordinary approve branch; define safe provider-specific handling/tests before supporting them.

For planned Valkey, use a server-side atomic transaction/script with tested equivalent semantics:

1. Authenticate the adapter request. HMAC validates original raw bytes/configured headers/timestamps using current official SDK/documentation. Invalid signatures are authentication failures, consume no grant, and never become ordinary successful ASA policy responses.
2. Scope event identity by rail/provider program. Return a committed original response for the same authenticated identity and matching request fingerprint. A changed payload under that identity is an integrity error.
3. Atomically check active mandate version/revocation/scope, kill switch, grant/verification binding, expiry and consumption state; run deterministic rules. Invalidation and consumption serialize across replicas.
4. On approval, consume grant/purchase scope, store original response and append authorization evidence **in the same atomic commit before responding**. Record actual declines/errors without marking purchases paid or incorrectly consuming a valid grant on an unrelated rejected attempt.
5. API event ingestion deduplicates by event ID and acknowledges only after SQL commit; then fans out over SSE. Recover pending ingestion after restart. Browser reload reads persisted history and resumes with a cursor.

Incomplete/unavailable state or commit cannot approve. No process-local lock, response-before-consumption window or unchecked late used-key write is sufficient. Returning the original cached approval for the same event is idempotency, not a new purchase or approval of distinct replay.

Preserve planned Valkey concepts `preapproval:{card_token}`, `used:{card_token}`, `asa:{asa_token}`, `killswitch:{user_id}`, `leash:events` as adaptable interface sketches. Agree active-authority/correlation keys and rail/program-scoped decision identities before freezing. Add exact total/currency, checkout/mandate hashes, grant identity/status, correlation and validity beyond legacy PreApproval fields. Cache retention covers provider redelivery; one-use state remains effective throughout supported instrument/grant lifecycle, never disappearing early to re-enable spending.

Webhook network I/O is Valkey only. SQL, trusted merchant retrieval, Lithic issuance/pausing, inference and receipts stay outside ASA. SQLite local development also needs real transactions/uniqueness for consumption/idempotency; it does not prove multi-replica Valkey correctness. API-only durable SQL writes remain the deployed design. Record latency and actual rail/decision source.

Audit is append-only; deduplicate ingestion rather than altering history. Link mandate/version/hash, run/source/trace, trusted snapshot/checks, grant, actual authorization and incident. Redact PAN/CVV/credentials from tool args/results, logs, snapshots, events and SSE. If Object Storage is unavailable, retain durable local source evidence/hash and disclose actual storage; never fabricate a missing snapshot.

### 23.6 Proposed API and MCP responsibilities

The product API implements health/readiness and JWT signup/login/me; R02 adds mandate lifecycle/identity/run routes; payments remain pending; agents/MCP routes now exist separately. This target contract retains familiar legacy names; section 12's `/api/...` routes are suggestions, not required breaking renames. Owners agree final routes/models together.

| Operation / proposed route | Authority | Enforcement |
|---|---|---|
| `POST /mandates/propose` | Human or scoped agent drafts | No authority until human confirms |
| `POST /mandates/{id}/approve` | Human only | Exact structured payload/version/hash, authenticated confirmation and validity |
| `GET /mandates`, `GET /mandates/{id}` | Authorized subject/session/agent | No cross-user/session access |
| Replacement / `PATCH /mandates/{id}` | Human only | Draft replacement, explicit confirmation, immutable history, serialized old-grant revocation |
| Revoke / `POST /killswitch` | Human only | Serialized invalidation; instrument pause outside ASA |
| Internal agents `POST /runs`, `GET /runs/{id}` | `AGENTS_SERVICE_TOKEN`, API dispatch | Actual Strands execution tied to mandate/session, no implied consent |
| API `POST /agent-runs` | Agent bearer, authenticated mandate owner | Persist exact run ID/mode; server supplies owner/version/hash; echo only after commit |
| `POST /checkouts/verify`, `GET /checkouts/{id}` | Scoped purchase caller/trusted backend | Server retrieval/assertion validation; no arbitrary public grant minting |
| `POST /payments`, `GET /payments/{id}` | Scoped agent or API/MCP caller | Independent verification, idempotent grant issuance, once-only card details if needed |
| Payment approve/deny review | Human only | Cannot bypass evidence/checks; changed authority requires confirmation/re-verification |
| `POST /provenance` | Authenticated agent/service | Sanitized trace claims keep actual trust class; never become canonical merchant truth |
| SSE/history/incidents/receipts | Authorized UI session | Persisted outcomes, resume cursor, provider/source/latency labels, no secrets |
| Guardian evaluation/investigation | Internal authenticated service | Structured recommendations only; untrusted sources remain data |
| ASA/local authorize | Provider HMAC or internal simulator auth, distinct adapters/routes | Same deterministic engine; correct wire schema and atomic checks |

Keep human/provider/inference credentials server-side behind authenticated web routes or a server-issued scoped session. `NEXT_PUBLIC_*` cannot contain `USER_TOKEN` or provider secrets. Agent bearer credentials never authorize human-only routes. CORS is not authentication. Demo shortcuts must preserve these boundaries and be documented.

MCP uses the official locked SDK's `MCPServer` (FastMCP rename), Streamable HTTP, `stateless_http=True`, `json_response=True`, forwarded bearer auth and one backend operation per thin tool. Preserve `propose_mandate`, `list_mandates`, `request_payment`, `check_status`; payment requests reference trusted checkout identity. No grant mutation, approval, limit increase, kill switch or unrestricted provider tool. Shopping tools run in `services/mcp-store/` at `/mcp` on port 8003, separate from `services/mcp-leash/` at `/mcp` on port 8002, both owned by Aditya over Cameron's controlled merchant; backend authorization remains mandatory for any calling interface.

### 23.7 Public documentation checks

Checked October 10, 2026. Public documentation validates facts, not this team's account access or installed SDK behavior.

- [Lithic ASA](https://docs.lithic.com/docs/auth-stream-access-asa) documents six-second timeout, recommended three-second response, transaction metadata, sandbox enrollment and configurable HMAC verification headers. Verify enrollment, signed requests, schema and real sandbox approval/decline before selecting this rail. Authentication errors remain distinct from policy declines.
- [Strands hooks](https://strandsagents.com/docs/user-guide/sdk/agents/hooks/) documents before/after tool events. Validate registration/event structures against the locked local SDK; online examples alone do not establish compatibility.
- [Akamai workshop inference](https://github.com/akamai-developers/akamai-workshop-hackmidwest/blob/main/docs/inference.md) describes selected compatible operations. Exercise a genuine Strands tool-call round trip, structured findings, explicit token limits and failure behavior. Centralize setup in planned `make_model()` with provider abstraction and server-side credentials.
- [Google AP2](https://github.com/google-agentic-commerce/AP2), [AgentsPay](https://agentspay.ai/) and [Skyfire features](https://docs.skyfire.xyz/docs/features) are prior art. AgentsPay describes policy/scoped cards/audit; Skyfire describes spending rules. These references do not establish LEASH integrations or compliance. Do not claim competitors lack semantic protections; demonstrate LEASH's own verified attack-aware chain.

### 23.8 R01 accepted integration baseline

Implemented on `rishi/r01-shared-contracts`: shared Pydantic models, strict cents/quantity/boolean/MCC/UTC validation, immutable authority records, canonical JSON and SHA-256 helpers, verification/grant binding shape, nullable guardian model, sanitized event envelopes and async publishing. `api/tests/test_shared_contracts.py` exercises tamper detection, same-price subscription hash changes, bounded grant expiry, required verification checks, sensitive-data redaction and event write failures. [api/README.md](../api/README.md) is the exact field/hash/wire-format handoff for all three lanes.

The proposal `cart_hash` preserves the original four-field definition. Mandate and trusted checkout hashes are distinct versioned payloads. Payment proposals require `checkout_id`; PreApproval requires the exact nested AuthorizationGrant; a `VERIFIED` record requires all 15 named deterministic checks; stream entries store the canonical envelope in an `event` field with a deduplication `event_id`. Array order is significant. Unknown fields fail validation; adapters must reject unsupported provider facts before normalization.

The candidate incorporates main at `1818a43`, including Cameron's build/LKE/PostgreSQL provisioning and Aditya's `2e6f940` agents/MCP implementation. [The refreshed handoff](../api/agent-interface-handoff.md) records 52 passing contract tests, captured serializer/evaluator/hook/registration outputs, 33 passing locked MCP tests and 126 passing agents tests with one restart-test failure and two live tests deselected. R01 now includes `AgentRunRegistration`; the API derives owner/version/hash/status after authenticated registration. Its accepted intake contract uses 2xx after durable commit, 409 only for identical committed duplicates, 422 for altered duplicates/validation, and 5xx for outages. Current guardian/source/trace/model and semantic mandate fields remain compatible; stored snapshots carry a separate `stored_sha256`. Aditya's endpoint authentication, semantic forwarding, pre-upload redaction, hash preservation and registration/outbox fixes are present. R02 implements mandate routes and durable ownership; R06 provenance intake remains pending. Cameron owns current `k8s/`, `scripts/`, `mise.toml` as deployment paths alongside reserved `infra/`; shared packaging, API image context, persistent trace volume, protected merchant/rail/Valkey and full live acceptance remain pending. The merged shopper now uses Store MCP and the demo is live-first; a recorded live injection remains pending. Latest separate live/scripted credentials on Aditya's branch still need to merge and be provisioned with their own mandates. Do not silently weaken requirements. Section 21 remains the original historical inspection.

These schemas validate shape and content consistency, not human identity, cryptographic authenticity, source trust, current state or atomic consumption. R02 implements real signing/confirmation/persistence, R03 executes independent verification, and Cameron implements trusted merchant binding and atomic rail enforcement. No purchase route, live integration, Compose boot or end-to-end acceptance is claimed by R01. Cameron's C01 packaging and remaining runtime interface coordination remain pending; the initial absence observations in section 21 are historical snapshots.

## 24. Team handoffs and unresolved dependencies

Section 15 assigns role responsibilities; `AGENTS.md` controls path edits. Rishi owns current `api/`, product backend and persistence; Cameron owns trusted merchant, payment rail and infrastructure; Aditya owns agents/tools/MCP/provenance and adversarial fixtures. All three agree shared contracts before freezing.

The synchronized [build plan](../Leash-build-plan.md) expands this handoff summary into R01–R10, C01–C10, and A01–A10 assignments, separate human/coding-agent responsibilities, H01–H13 contracts, and G0–G5 gates. Its owner table matches `AGENTS.md`. Planned shared package metadata and the package marker have an explicit Cameron owner; Rishi retains frozen domain/event contracts. The first gate jointly agrees interfaces before dependent implementations. Service owners retain their own Dockerfiles, dependencies, and tests.

| Owner / reviewers | Concrete deliverable | Required interface or evidence |
|---|---|---|
| Rishi; all three review | Shared mandate/checkout/grant/decision/trace schemas, OpenAPI contract | Field mapping, version/hash payloads, authority scope, enums, identity/auth and money rules |
| Cameron + Rishi | Trusted catalog/checkouts and protected charge binding | Merchant authentication, canonical SKU/category facts, immutable revisions, session ownership, same-merchant/2999-cent fixtures |
| Rishi + Cameron | Verifier, grant issuance and serialized invalidation/consumption | Mandatory constraints, exact amount/currency, one-use state/current authority/correlation; no approving stub |
| Cameron | Local rail/pure engine and Valkey atomic protocol | Real approve/decline, missing-grant decline, duplicate fingerprint validation, concurrent distinct requests and outages |
| Cameron | Lithic capability report and adapter if available | Account/keys/program, ASA enrollment/HMAC, reachable HTTPS, official schemas, real sandbox results |
| Aditya | Strands shopper/investigator/tools/hooks | Locked SDK compatibility, real Akamai tool-call smoke test, sanitized trace and evidence; no unrestricted provider tool |
| Rishi | SQL migrations, event ingestion/SSE and audit reads | PostgreSQL or explicit local SQLite mode, recovery/deduplication, append-only evidence and refresh persistence |
| Rishi | Six UI views and confirmation flow | Actual API/SSE data, original mandate, checkout comparison, rail/source/latency labels, accurate errors |
| Cameron | Akamai deployment/environment templates | Real compute access, DB/Valkey connectivity, URLs/TLS/secrets, deployed FastAPI/policy smoke test |
| Aditya + service owners | Six reproducible scenarios and three-minute demo script | Independent manipulated-output security tests plus genuine model trace; expanded semantic/replay/concurrency matrix |

External/technical dependencies remain **unverified**, not assumed unavailable:

1. Lithic sandbox credentials/account/program capabilities, ASA enrollment, HMAC header/secret setup, current wire models/SDK and public HTTPS reachability. Select Lithic only after authenticated sandbox tests; keep local rail usable.
2. Akamai inference key, endpoint/model compatibility, real Strands tool calling/structured output, latency and outage behavior. Label fallback provider in run/UI metadata; deterministic controls continue during outage.
3. Akamai compute access, LKE or single-Linode topology, actual public app URL, managed PostgreSQL/Valkey connectivity and durable storage. A local-only app fails the deployment acceptance criterion.
4. Object Storage access and exact workshop `OBJ_*` names. Cameron confirms these; do not invent credentials. If unavailable, retain durable local evidence and state its storage source.
5. R01 schemas are accepted by Rishi; purchase routes, merchant authentication/category mapping, checkout freeze rules, scope reservation and atomic Valkey protocol remain pending. No independent verifier exists yet.
6. Compose, Dockerfiles/manifests, CI, root Ruff configuration, migrations, generated types and service/end-to-end tests remain pending. R01's contract suite is present; it does not prove boot/security/deployment of the full application.

Retain planned server variable names `INFERENCE_BASE_URL`, `INFERENCE_API_KEY`, `MODEL_ID`, `DATABASE_URL`, `VALKEY_URL`, `LITHIC_API_KEY`, `LITHIC_ENVIRONMENT`, `LITHIC_ASA_SECRET`, `MANDATE_SIGNING_KEY`, `DEMO_USER_ID`, `USER_TOKEN`, `AGENT_TOKEN_SHOPPER`, `API_URL`, `AGENTS_URL`, `MCP_LEASH_URL`, `MCP_STORE_URL`, `STORE_URL`. Names do not prove configured credentials. Cameron adds any rail-selection, trusted-merchant auth, grant-lifetime or session variables and confirms Object Storage names. Existing `NEXT_PUBLIC_API_URL` contains only a public backend URL.

Proceed by section 16's dependency phases: security core/local rail -> real Strands integration -> verified Lithic -> integrated presentation, integrating interfaces/UI continuously. All security-critical improvements stay MVP scope. Cut attacker swarms, unrelated agents, extra merchants, notifications and consumer-bank features before any required trust boundary/scenario/trace/replay defense. No silent fallback to live funds or assumed Stripe access.

## 25. Validation and completion evidence

Section 19's nineteen completion criteria remain unchecked in this checkout. Dependencies and this spec do not complete a financial security scenario. Update implementation status only with concrete runnable/test/deployment evidence.

| Acceptance flow | Required assertions beyond visible result |
|---|---|
| Legitimate purchase | Human confirmation, canonical charger/category/quantity, verified total, grant binding, actual local/sandbox approval and persisted history |
| Same merchant/same amount attack | Real listing/tool trace, unchanged mandate hash, identical merchant/2999 cents/USD, canonical subscription/recurrence evidence, no malicious grant, actual block/decline and incident |
| Above budget | Trusted total including tax/shipping fails confirmed comparator regardless of agent/model preference |
| Missing/untrusted evidence | Missing fields/inaccessible source/failed authentication -> review/block, no grant or successful purchase |
| Expired/replayed approval | Expired mandate/checkout/grant fails; distinct reuse fails; concurrent attempts consume at most once; genuine duplicate returns identical original response |
| Authorized recovery | Block leaves original authority unchanged/unconsumed; new compliant checkout/grant approves; blocked history persists |

Retain every test category in section 13. Add regressions for changed payload under duplicate identity, cross-session checkout IDs, exact amount/currency, immutable checkout revisions, direct protected-tool invocation, guardian override attempts, authority scope/cardinality, revocation races and ingestion recovery. Instrument tests to prove authorization invokes no inference. Manipulated-output fixtures test enforcement independently of model randomness; separately show actual Strands manipulation live and label fixture-driven runs accurately.

Before completion: run service/security/end-to-end tests; boot Compose when available; smoke-test the deployed Akamai backend/selected rail; measure decision latency; verify actual sanitized Strands traces, legitimate approval, semantic block and recovery; refresh the UI; rehearse within three minutes; visibly reset isolated fixtures; prepare a labeled prerecorded outage fallback. Provider failures cannot produce success banners or paid audit records.

Documentation validation for this update: diff/whitespace, local Markdown links, balanced fences, preservation of all twenty directive sections and nineteen completion criteria, ownership/current-versus-planned consistency, and explicit dependencies. Service/security tests and Compose boot remain pending because their implementations/configurations are absent.

Performed for the initial directive-alignment update: `git diff --check` passed; programmatic checks passed for local Markdown links, fence balance, whitespace, exact retention of the adopted directive with the two documented editorial adaptations, all 25 specification sections, all 19 unchecked MVP criteria, and all 10 prominent invariants. That initial update changed only root `AGENTS.md` and new `docs/LEASH_SPEC.md`. Compose configuration validation failed because no Compose file exists; service/security tests were not run because no test suite or security implementation is present. The subsequent team-plan alignment restores the annotated repository tree, replaces the legacy build plan, and adds synchronized execution responsibilities/references; it changes documentation only.

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

### R02 implementation boundary

[R02](../api/r02-handoff.md) implements persisted human authority and registered
agent context on its review branch: checked migrations, UUID-to-LEASH identity
mapping, explicit agent ownership/mode binding, proposal/read/list, exact version/
hash confirmation with real Ed25519, immutable history, replacement and revocation,
and `/agent-runs` commit/echo. Its SQL authority/audit mutations are transactional;
81 API tests pass including 19 real PostgreSQL tests. Frozen shared contracts stay
unchanged. It is not independent checkout verification, grant issuance, rail
invalidation, provenance ingestion, hosted deployment or live acceptance. Cameron
must coordinate root-context API builds, readiness, configured secrets and operator
provisioning. Future grants require the atomic SQL/Valkey invalidation protocol;
audit delivery cannot substitute for it. Earlier inspection sections are historical.
