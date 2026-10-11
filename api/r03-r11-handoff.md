# R03 / R11 + protected local-rail charge

Builds on the durable preflight foundation over `11d6696`. Verified charger
checkouts can now receive a one-use **local-rail** grant, bind at the merchant,
and complete through `/local/authorize` with a durable event id. This is not
Lithic live issuance, provider reconciliation, or a finished Graph demo.

## Callable behavior

`POST /payments` retains the frozen agent body `{mandate_id, checkout_id, run_id,
proposal?}`. The API requires an owned registered uncancelled run whose immutable
mandate version/hash still matches current confirmed, unexpired authority.
The account gate is checked first. Human credentials cannot call the tool.

The natural retry identity is human + agent + run + mandate ID/version + checkout
ID. The complete canonical body, including optional agent claims, is hashed.
Same identity/same content returns the original completed response; changed
claims return 409. Optional claims never replace independently fetched facts.

1. Lock user, then mandate; insert `payment_operations` and its genuine audit
   event. Reserve payment ID, grant reference, instrument reference, provider UUID
   issuance key and UUID authorization event ID. Commit before any merchant GET.
2. Fetch only the configured merchant origin using its **browse** service
   credential. Then own + freeze the checkout with the distinct
   `STORE_CHARGE_TOKEN` (session = `ses_{run_id}`).
3. Reacquire locks; recheck account/run cancellation, expiry and version/hash.
4. Persist canonical observation + verification. On
   `VerificationDecision.VERIFIED`:
   - bind checkout (`POST /api/checkouts/{id}/bind`) with grant +
     `authorization_event_id` (facts_hash correlation)
   - seed Valkey grant (`PUT {WEBHOOK_URL}/internal/grants`) including `run_id`
   - insert approved `payment_attempts` + `payment.approved` audit
   - finish operation `authorized` / `grant_issued_local_rail`
   - return once-only `instrument_token`, `authorization_event_id`, and
     `rail=local_payment_rail_simulator`
5. Subscription / evidence failures remain blocked with no grant seed.

`GET /payments/{id}` never re-discloses the instrument. Authorized ops report
`authorization_status=grant_issued` and
`payment_execution=awaiting_merchant_complete`.

Store `POST /api/checkouts/{id}/complete` (charge credential) requires owned,
frozen, bound checkout and posts the reserved event id to
`{WEBHOOK_URL}/local/authorize`. Approved → `completed`; declined → 409;
unreachable/unknown → 503 without a new event id. MCP Store complete uses
`STORE_CHARGE_TOKEN`, not the browse token.

Migration `0011_payment_authorization.sql` allows `prepared → authorized` and
approved payment_attempt rows with grant/instrument; evidence may be
`merchant_owned_frozen` with `financial_authority=true`.

## Durability, retries and controls

| Situation | Implemented result |
|---|---|
| Crash after preparation | Retry resumes; bind+seed once; state `authorized` |
| Concurrent identical retries | One operation/outcome; seed/bind once |
| Concurrent changed merchant facts | First observation retained; different source hash → 409 |
| Different checkout/run while prepared/reconciling/authorized | 409 |
| Historical approved attempt | Blocks new checkout until reconciled; no reissue |
| Run Stop | Cancels prepared ops; Valkey run latch via `stop_rail_run` → `pending_rail_ack` |
| Emergency Kill | Account rail latch + prepared cancel (unchanged) |
| Unknown rail outcome on complete | 503; do not mint a new authorization_event_id |

## Exact remaining work

1. Lithic SINGLE_USE issuance + ASA correlation (not local-rail only).
2. Provider read-back / reconciliation worker for unknown outcomes.
3. Aditya bounded Graph + clean recovery under unchanged mandate.
4. Mission Control / full SSE product surfaces for the live path.
5. Deployed Secret values + LKE rollout of migration `0011`.

## Evidence

Local: API unit + disposable PostgreSQL (`LEASH_TEST_DATABASE_URL`), store unit,
webhook (incl. real Valkey), mcp-store pytest. No claim of live Lithic, genuine
model injection, or deployed acceptance from this handoff alone.
