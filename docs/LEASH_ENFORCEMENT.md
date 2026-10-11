# What Leash actually enforces

Reference: `main` at `138d636` in `RishiMadhavan-ui/hackmidwest-2026`. This page
describes the code as committed, not the target demo. Anything that is planned
or only on a branch is labeled.

Leash sits between a shopping agent and money. The agent never holds a card. It
can only ask, and every ask is checked in code against what a human confirmed.

## Status at a glance

| Works today on main | Not live yet on main |
|---|---|
| Human-only confirmation of mandates (Ed25519-signed, version + hash bound) | **Approvals.** `POST /payments` returns `blocked` for every checkout, including compliant ones (`financial_authority_unavailable`) |
| 15 deterministic checkout checks against the merchant's own checkout record | Proving checkout ownership: the `checkout_authenticated` check currently always fails closed |
| Kill Switch: revokes every mandate, invalidates unused grants on the rail | Merchant charge completion: the store returns 503 even for a correctly bound checkout |
| Per-run stop request (blocks that run's payment preflight) | Strands Graph recovery and automatic retry (in progress on branch `aditya/strands-graph`) |
| Single-use grant enforcement in the payment rail (code + tests) | The API issuing grants to the rail |
| Store MCP browsing locked to the merchant, with hidden-text inspection | Guardian LLM wired into the payment path (exists as a separate route, not called) |
| Persisted, streamed audit events for all of the above | Public Attack Lab (poisoned listing is deliberately disabled for now) |

So today the honest animation ending for any purchase is **"blocked before
payment"**. The attack is blocked for policy reasons. A good charger is blocked
too, but only for operational reasons, because the approval path isn't enabled
yet.

## The rules

### 1. Only a human creates spending authority

- An agent can call `propose_mandate`, which creates a **draft**. A signed-in
  human can also draft one (`POST /mandates/draft`).
- A draft grants nothing. Only a human can confirm it, and the confirmation must
  name the exact `version` and `canonical_payload_hash` they reviewed, with
  `confirmed: true`. The server signs it with its Ed25519 demo key.
- Any change creates a new version that needs confirming again. The old version
  becomes `superseded` and stops working immediately.
- There is no agent tool or route to confirm, raise a limit, or touch the Kill
  Switch. Those routes reject agent credentials.

### 2. What a mandate can limit

A mandate is one purchase intent, for example "Buy a USB-C laptop charger for
under $40. No subscriptions."

| Field | Meaning | Example |
|---|---|---|
| `max_cents` | Spend cap per purchase, all charges included, integer cents | `3999` ("under $40") |
| `category` | Product category that must match exactly | `laptop_charger` |
| `product_constraints` | Attribute rules: `equals`, `contains`, `minimum`, `maximum` | `connector equals USB-C` |
| `max_quantity` | Units per purchase | `1` |
| `maximum_purchases` | Number of purchases this mandate allows | `1` |
| `merchant_allowlist` | Allowed merchants, or `null` for any | `["mer_volt_supply"]` |
| `allow_subscription` / `allow_recurring` | Off unless the human asked for them | `false` / `false` |
| `currency` | USD only | `USD` |
| `shipping_constraints` | Country, postal code, deliver-by, max shipping | optional |
| `valid_from` / `valid_until` | Validity window; drafts default to 30 minutes | |

Effective ceiling per mandate: each purchase is at most `max_cents`, and there
are at most `maximum_purchases` purchases.

### 3. The 15 checks on every payment request

When the agent calls `request_payment`, the API ignores the agent's description
of the cart for decision-making. It fetches the checkout from the merchant
itself, then runs every check below. Any failure blocks the payment and is
returned as a reason code.

| Check | Fails with |
|---|---|
| Mandate confirmed, active, signed | `mandate_unconfirmed` |
| Inside the validity window | `mandate_expired_or_not_started` |
| Checkout ownership authenticated | `checkout_source_unavailable_or_wrong_owner` (always fails today) |
| Checkout prices positive, billing terms consistent | `checkout_price_nonpositive`, `checkout_recurrence_inconsistent` |
| Checkout evidence fresh | `checkout_expired_or_future_evidence` |
| Category matches, and is a known category | `category_mismatch`, `unknown_category` |
| Every product constraint met | `product_constraint_unmet`, `product_attribute_unknown` |
| Quantity within limit | `quantity_exceeded` |
| Purchase count within limit | `purchase_scope_exhausted` |
| Merchant on the allowlist | `merchant_not_allowed` |
| Total within the cap | `amount_over_limit` |
| Currency matches | `currency_mismatch` |
| No subscription unless allowed | `subscription_prohibited` |
| No recurring charge unless allowed | `recurring_prohibited` |
| Shipping terms verifiable | `shipping_constraint_unverified` |

Unknown always blocks: an unknown category, a missing attribute, or a missing
fact never passes by default. No model is involved in these checks.

Before the checks even run, the payment request must belong to a registered run
bound to the same agent, mandate version and hash. A stopped run, a stopped
account, or a mandate that changed since the run started is refused.

### 4. Kill Switch and run stop

- **Kill Switch** (human only, account-wide): revokes every mandate, tells the
  rail to invalidate unused grants, and requests closure of any sandbox cards.
  It can't be undone. Payments that were already authorized are not reversed.
- **Run stop** (human only, one run): persisted immediately and blocks that run's
  payment preflight. Run-level grant revocation and agent cancellation are still
  pending.

### 5. The payment rail (once grants exist)

The rail (`services/webhook`) approves a card authorization only when it matches
a stored single-use grant exactly:

- instrument token, merchant descriptor, MCC, currency and exact amount
- checkout ID, checkout hash and merchant binding ID
- grant not expired (lifetime of 30 minutes or less), not consumed, not revoked
- mandate still active at the same version, and Kill Switch off

It consumes the grant atomically in Valkey, so two concurrent charges can't both
spend it, and a repeated event ID returns the original decision. It never calls
an LLM, a database or a merchant during the decision. The API does not issue
grants yet on main, so this layer is tested but not reached in a real run.

## Examples that are not Leash features

- **Human approval above a threshold:** not how Leash works. Every mandate needs
  human confirmation, whatever the amount. There is no "auto-approve under $X".
  The contract has a `pending_user` payment status, but main never returns it.
- **Per-agent budgets:** there's no standalone budget per agent. Limits live on
  each mandate. Each mandate is bound to one agent identity (the agent that
  drafted it, or the user's shopper agent for a human draft), and an agent can
  only see and spend under mandates bound to it.
- **Spend caps and merchant allowlists:** yes, as `max_cents` and
  `merchant_allowlist` on each mandate.

## What the MCP layer allows and blocks

The agent's entire world is seven tools on two MCP servers. Both are thin: they
forward to the API or the merchant, and the real decisions happen behind them.
From the agent's point of view, each tool call returns either a result or
`{"status": "error" | "blocked", "reason": ...}`.

### Leash MCP (`mcp-leash`, port 8002): payments

| Tool | Allowed | Blocked or refused |
|---|---|---|
| `propose_mandate` | Creates a draft only | Never activates anything |
| `list_mandates` | Lists active mandates bound to this agent | Other agents' mandates |
| `request_payment` | Runs the 15 checks against the merchant's checkout | Returns `blocked` with reasons (every request, today) |
| `check_status` | Reads a payment this agent made | Other agents' payments |

The server itself refuses calls with no bearer token, accepts money only as
strict integers (so `40.0` or `true` is rejected), and turns a timeout into
"outcome unknown, do not retry", never a retry.

### Store MCP (`mcp-store`, port 8003): shopping

| Tool | Allowed | Blocked or refused |
|---|---|---|
| `browse` | Pages on the configured store | Other hosts, non-HTTP schemes, redirects off the store |
| `create_checkout` | A checkout built from the store's own catalog | The agent can't set price, category or billing terms |
| `complete_checkout` | Nothing completes today | No binding: 403. Mismatched binding: 409. Bound: 503 |

Every page `browse` returns is hashed, inspected for hidden instruction-like
text, redacted and snapshotted. The agent sees the text (it's gullible on
purpose), and the evidence is recorded as untrusted.

## The signature scenario, step by step, as it behaves today

1. `list_mandates` returns the confirmed charger mandate: up to $39.99,
   `laptop_charger`, connector USB-C, no subscriptions.
2. `browse /products/chg-65w` returns the listing. The poisoned version hides
   JSON-LD saying checkout "must reference voltcare". It's only available in
   offline fixtures now; the public route serves the clean listing.
3. The fooled agent calls `create_checkout` for `voltcare`. The store builds the
   checkout from its catalog: VoltCare Protection Plan, $29.99, monthly,
   category `protection_plan`. Same merchant, same price, same currency as the
   charger.
4. `request_payment` says "charger, $29.99". The API fetches the real checkout
   and finds:
   - merchant, total ($29.99 ≤ $39.99), currency: **pass**
   - category: **fail** (`category_mismatch`)
   - connector constraint: **fail** (`product_attribute_unknown`)
   - subscription and recurring: **fail**
   - plus the two operational reasons every request gets today

   Result: `blocked`, before any payment.
5. The real charger (`chg-65w`) passes every policy check but is still `blocked`
   for the operational reasons. In the target demo, it gets a single-use grant
   and a labeled local-rail authorization. That path isn't on main yet.

Merchant, MCC and amount controls alone would have let step 4 through. The block
comes from comparing the actual item against the human's confirmed intent.
