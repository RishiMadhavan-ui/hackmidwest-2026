# Main integration: V2 and Cameron's checkout/payment merge

**R03/R11 follow-up:** [the current API handoff](../api/r03-r11-handoff.md)
supersedes ledger/snapshot-absence and retry-lock statements below. Private
operations commit before GET, full observations are immutable, scope barriers and
prepared-work cancellation are tested. A merchant bearer still cannot prove
checkout ownership; evidence is observed_unverified and spending remains blocked.
The rest of this file preserves incoming d773079 defects and enablement gates.


Baseline: main fast-forwarded from `f2f50a5` to Cameron's `d773079` (PR #14).
All teammate commits, storefront changes and Kubernetes configuration are retained.
No deployed service, provider, shared database or teammate credential was used.

## Current callable behavior

- `POST /payments` uses the existing frozen PaymentProposal. `run_id` is optional
  in that schema for compatibility, but **required by this endpoint** (422 if
  absent). It must match the authenticated agent, human and mandate (404 otherwise).
  Account Stop and run Stop deny before merchant retrieval. Human credentials
  cannot invoke this agent endpoint.
- The API fetches the requested checkout from configured STORE_URL using
  STORE_API_TOKEN. It validates exact checkout identity, JSON/status, explicit
  USD/quantity/recurrence/product facts, canonical facts hash and item arithmetic.
  Missing facts cannot be replaced by caller proposals or convenient defaults.
- A verified candidate is persisted with `status: blocked`, payment ID,
  verification ID and reason **financial_authority_unavailable**. A subscription
  keeps deterministic category/subscription/recurrence reasons. No grant is seeded,
  instrument issued/returned, merchant bound or charge attempted from either path.
  This operational block is not permission for a human or guardian to bypass controls.
- Identical same-run/agent/mandate-version/checkout preflight returns its persisted
  record. User-row locking serializes preflight with Stop and duplicate requests.
  Old approved grant records require reconciliation; they are not new authority.
- `GET /payments/{id}` checks both human and agent ownership and exposes no card
  token. Its projection says authorization unverified/payment execution unavailable;
  historical `approved` records mean grant permission, not a paid receipt.
- Store catalog/listing/start/create/read and process-memory binding validation
  remain. Completion rejects missing bindings (403) and mismatched claims (409);
  a correctly bound request is still 503 with no rail/provider call. Store health
  explicitly reports disabled_pending_durable_controls. Creating an open checkout
  grants no authority, including through the new public storefront start route.
- Human run Stop is durable but its financial and Graph acknowledgments remain
  pending. Emergency Stop retains account rail invalidation and CLOSED reconciliation.

## Incoming defects contained and exact enablement work

| Priority | Evidence in incoming d773079 | Safe fix still required / owner |
|---|---|---|
| P0 durable operation | api/payment_service.py:request_payment called `_seed_grant` / `_bind_store` before `_persist` / route commit | **Rishi R04/R11:** commit operation identity, request scope, verified snapshot and stable external identities before external writes. Use durable prepare/activate/reconcile states, SQL uniqueness/reservations and a transactional outbox. Crash after any step must retain the original IDs and forbid another purchase. Helpers remain dormant until these gates pass. |
| P0 isolated stop | Payment path ignored body.run_id and run_cancellations; grants have no run/generation binding | **Rishi R13 + Cameron C11 + Aditya A14:** H14 contract-only agreement, scoped run/human launch credential, SQL gate and atomic rail issuance/consume/revocation barrier. Prove Stop-versus-issue/consume races and loss rehydration. New API preflight checks cannot revoke an already activated grant. |
| P0 instrument lifecycle | `_resolve_instrument` reused users/lithic_cards or one per-user simulator token | **Rishi R04 + Cameron C05/C09:** dedicated stable instrument per verified operation; exclusive SINGLE_USE for actual Lithic. No legacy/reusable account-card substitution. Local instruments must be clearly simulated and cannot imply provider issuance. Unsafe resolver/activation path removed. |
| P0 unknown completion | services/store/main.py:complete_checkout used a new evt_store token per call and only memory status | **Cameron C02 + Rishi R11:** API-owned durable checkout/run/payment correlation and original charge event ID before sending. Matching retry replays original decision, altered retry conflicts, timeout becomes reconciling and blocks alternate purchases. Persist outcome via authenticated API ingestion; no merchant direct SQL writes. Completion is gated, not claimed repaired. |
| P0 checkout truth | Mapper defaulted USD, quantity, descriptor/MCC and created owner/session/expiry without merchant proof; bind used shared STORE_API_TOKEN | **Cameron C02 + Rishi R03:** owned caller/session association, revision/expiry/freeze and exact SKU/hash/instrument association; separate backend-only bind authority from Store MCP credential. New strict preflight checks facts but does not establish actual merchant owner/expiry or charge safety. |
| P1 isolation/truth | get_payment checked human only; success counter counted all that human's approvals; approved meant grant issued | Fixed same-user agent read isolation, mandate/version count scope and no instrument disclosure. **Rishi R04/R06:** distinguish verified, grant-issued, authorized, unknown, declined and settlement outcomes based on real persisted events. Successful-purchase count needs actual correlated authorization and atomic mandate reservation. |

Remaining enablement is implementation work. Do not flip an environment flag or
restore removed charge calls to make a demo green. Keep the frozen models/events
unchanged until the separate agreed contract PR. No ownership lane is reassigned.

## Migrations, images and acceptance

Cameron's committed `0007_payment_attempts.sql` is unchanged. Our unpublished
forward migrations are `0008_card_closure_intents.sql` and
`0009_human_session_revocation.sql`. Original 0001–0007 hashes remain intact.
API Dockerfile already copies api/*.py, shared and all migrations; store Dockerfile
copies its affected modules. Incoming store rail configuration is retained, but
configuration is not proof that completion is enabled or that a charge occurred.

Read [V2 stop handoff](../api/v2-stop-handoff.md), [build plan](../Leash-build-plan.md),
[137-case coverage](LEASH_SECURITY_COVERAGE.md) and [test evidence](V2_TEST_RESULTS.md).
The case totals remain 35 scoped PASS / 46 NOT_RUN / 51 MISSING / 5 BLOCKED_EXTERNAL.
New containment tests prove denial, not a successful purchase or complete Graph demo.
