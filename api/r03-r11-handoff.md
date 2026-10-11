# R03 / R11 durable preflight foundation

Implemented on main over `11d6696`. This is a tested non-spending foundation,
not completed R03/R04/R11 or a purchase demo. No hosted migration, provider call,
deployment or frozen models/events change occurred. Ownership stays unchanged.

## Callable behavior

`POST /payments` retains the frozen agent body `{mandate_id, checkout_id, run_id,
proposal?}`. The API requires an owned registered uncancelled run whose immutable
mandate version/hash still matches current confirmed, unexpired authority.
The account gate is checked first. Human credentials cannot call the tool.

The natural retry identity is human + agent + run + mandate ID/version + checkout
ID. The complete canonical body, including optional agent claims, is hashed.
Same identity/same content returns the original completed response; changed
claims return 409. Optional claims never replace independently fetched facts.
There is no newly required Idempotency-Key header or shared model field.

1. Lock user, then mandate; insert `payment_operations` and its genuine audit
   event. Reserve payment ID, grant reference, instrument reference, provider UUID
   issuance key and UUID authorization event ID. **These are private reservations,
   not a grant/card/provider-issued instrument.** Commit before any merchant GET.
2. Fetch only the configured merchant origin using its service credential.
   Encode the checkout ID as one path segment; disallow redirects, credential/
   query/fragment/path-bearing configured origins and malformed canonical facts.
   No database lock is held during retrieval. No financial network write occurs.
3. Reacquire user/mandate/operation locks and recheck account/run cancellation,
   expiry and current version/hash. If invalidated, commit cancellation and deny.
4. Commit the complete itemized canonical observation, original source facts/hash,
   normalized checkout/hash, human/run/mandate version/hash association,
   deterministic verification, blocked response and audit events together.

The source hash remains Cameron's canonical facts hash over checkout_id, currency,
line_items, MCC, descriptor, recurrence and total. Stored status/hash metadata is
outside that hash. Snapshot identity/hash and observation timestamp are retained
separately. Source records, operation identity and the original blocked result cannot be updated or deleted. SQL forbids issuing authority through a new preflight result.
Sensitive content is rejected before source/snapshot persistence; event payloads
contain only identifiers, hashes, reasons and state, never source text/card details.

**Evidence is observed_unverified.** Current merchant responses do not supply
authenticated user/session ownership, revision, expiry or freeze proof. Snapshot
user/session/revision/expiry are API normalization/observation context, explicitly
marked as such. A service bearer does not establish checkout ownership. The
verifier receives checkout_authenticated=False. A charger therefore returns
blocked with checkout_source_unavailable_or_wrong_owner and
financial_authority_unavailable. Subscription observations additionally retain
category/subscription/recurrence failures. Nothing seeds a grant, issues a card,
binds merchant authority or charges. Do not flip this predicate/restore dormant
helpers until the missing trust and financial protocols are implemented/tested.

`GET /payments/{id}` remains human-and-agent scoped. It reports a safe blocked
projection for a prepared/cancelled/reconciling operation, plus optional operation
state/revision/financial_authority=False. Reserved identities are never disclosed.
Historical grant approvals remain history with authorization unverified and
execution unavailable, never a paid receipt.

## Durability, retries and controls

| Situation | Implemented result | Practical limit |
|---|---|---|
| Crash after preparation | Same retry resumes a read-only GET using all original references | No financial worker/dispatcher exists |
| Final transaction fails | Observation/outcome/events roll back together; committed preparation remains | Same identity may refetch; no provider operation was sent |
| Concurrent identical retries | One operation/observation/outcome; original response replay | Duplicate read-only GETs may occur; financial writes stay disabled |
| Concurrent changed merchant facts | First committed observation retained; different source hash conflicts with 409 | This is not merchant freeze or charge-time revision enforcement |
| Different checkout/run while prepared/reconciling | 409; database partial uniqueness also prevents overlapping scope | Barrier spans mandate versions; no paid-success reservation yet |
| Known GET failure | Persist safe terminal blocked/error status/detail; identical retry replays without fetch | A fresh checkout can be evaluated after this known non-spending failure |
| Run Stop | Cancel only that run's prepared operations in the Stop transaction | Run rail revocation/card closure/Graph acknowledgment remain pending |
| Emergency Kill | Cancel all that human's prepared operations in the account-stop transaction | Existing separate rail/provider acknowledgment semantics preserved |
| Replace/revoke/expiry | Cancel affected prepared operation; stale run cannot finalize | Active grant propagation and atomic financial barrier still required |
| Unknown outcome | Internal reconciling quarantine cannot be cleared by retry/Stop/replacement; alternate purchase blocked | Test injects state. No provider read-back/reconciliation worker exists |

SQL transitions currently permit only prepared -> blocked/cancelled/reconciling,
with revision increment and immutable identity. Reconciling has no public clearing
route. Future financial states require a forward migration and explicit protocol;
do not repurpose blocked/cancelled as successful provider evidence. Unknown
operations are retained even after account Stop; closure does not prove a charge
never occurred. Historic approved/used attempts block fresh candidates until
reconciled. No already-authorized transaction is reversed by these controls.

Migration `0010_payment_operations.sql` adds ledger, immutable observation and
owner/run/version/hash constraints. All previously committed migrations are
unchanged. API Dockerfile already copies api/*.py and all migrations, including
the new payment_operations.py; no infrastructure or service Dockerfile edit is
needed. Schema tests use disposable localhost PostgreSQL only.

## Exact remaining owner work, in dependency order

1. **Cameron C02:** authenticated checkout owner/session, durable revision and
   expiry, freeze/reverify and backend-only bind/charge credential separate from
   Store MCP's browsing/checkout credential. Preserve same merchant/2999/USD SKUs.
2. **All three H14:** dedicated contract-only review for run/attempt/checkout/
   grant/instrument generations, scopes and independent acknowledgment states.
   Rishi proposes API persistence/scope; Cameron atomic rail/merchant protocol;
   Aditya consumes MCP/Graph contracts. This batch changes no frozen shared files.
3. **Rishi R03/R04/R11/R13 + Cameron C04/C11/C05:** replace observation placeholders
   with verified merchant proof; add durable worker leases/fencing, prepare/activate
   outbox protocol, stable external-id execution, provider read-back, correlation,
   atomic success reservation and run/account revocation/loss rehydration. Only
   then issue a usable grant/dedicated SINGLE_USE card and enable protected charge.
4. **Aditya A11/A12/A14:** actual bounded Strands Graph, typed deny/unknown gates,
   independent investigation, quarantine and fresh-context recovery under unchanged
   authority; cooperative cancellation and stale-worker fencing. A terminal blocked
   candidate can permit a new compliant preflight; unresolved finance never can.
5. **Rishi R06–R10 + Aditya A13; Cameron C06/C10:** expose real operation/evidence
   states in product UI/full SSE, verify deployed runtime and rehearse genuine
   attack -> block -> automatic recovery -> authorization plus both Stop controls.

## Evidence and acceptance limits

See [R03/R11 execution evidence](../docs/R03_R11_TEST_RESULTS.md) and the unchanged
[137-case matrix](../docs/LEASH_SECURITY_TEST_CASES.md) with its updated
[coverage mapping](../docs/LEASH_SECURITY_COVERAGE.md). Tests verify local SQL/HTTP,
mocked merchant/provider failures and a local seeded-fixture stack. There is no
claim of live Lithic, genuine model injection, actual Graph or deployed acceptance.
