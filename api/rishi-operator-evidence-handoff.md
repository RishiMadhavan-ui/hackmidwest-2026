# Rishi operator access and purchase evidence handoff

Current work integrates teammate frontend `138d636` without changing the frozen
R01 models/events, Graph/store/rail application code, Kubernetes or shared data.
This is a locally verified control plane and non-spending evidence UI, not a
completed purchase demo. [Test results](../docs/RISHI_OPERATOR_TEST_RESULTS.md)
record actual execution scope. [Spec 29](../docs/LEASH_SPEC.md#29-attack-lab-access-control-p0)
and all 147 security cases still govern enablement.

## Implemented interfaces

- Human `POST /mandates/draft` uses exactly one enabled, operator-provisioned
  live-only shopper already bound to that human. Missing/ambiguous bindings
  return 409; scripted-only agents are excluded. It never claims the shared
  `AGENT_TOKEN_SHOPPER`, creates an agent, confirms a mandate or moves a token.
  Use the existing [R02 provisioning commands](r02-handoff.md) as operator.
- `GET /purchase-attempts?limit=25&before=<owned-payment-id>` returns durable
  preflight operations, newest first, and `next_cursor`. Limit is 1–100; a
  foreign/missing cursor is 404. `GET /purchase-attempts/{id}` returns its original
  immutable mandate version and checked normalized observation/source hash.
  Human ownership is mandatory; agents cannot use this view. Reserved financial
  references are omitted. These are observed/unverified attempts, not receipts,
  grants, authorized payments or settlement. Agent `/payments` wire is unchanged.
- Attack Lab routes require the existing real, unrevoked JWT human session **and**
  a configured stable-identity allowlist. Static demo human tokens, agent/service
  tokens, signed caller role claims and ambient cookies do not authorize them.
  `GET /attack-lab/access` returns actual operator/control state with
  `execution_available: false`. `POST /attack-lab/namespaces {}` creates/idempotently
  returns one isolated empty demo identity per operator; default preference is off.
  `POST /attack-lab/namespaces/{id}/control` accepts only
  `{enabled: <boolean>, expected_revision: <positive integer>}`. Owner substitution
  is 404; stale revision is 409. Successful mutations are transactionally audited.
- Reserved scenario/reset/replay/tamper/simulated-authorization routes enforce
  session, allowlist, ownership and strict body validation, then return 403 while
  disabled or 503 while integrations are missing. They execute **nothing**.
  They cannot select a provider, arbitrary card, URL, ordinary user or real rail.
  No reset helper, fixture mutation or provider call is exposed.

## Server configuration and deployment — Cameron / API operator

API needs forward migration `0011_attack_lab.sql`; all historical migrations
remain unchanged. `/readyz` checks the whole migration set. New modules are
covered by `api/Dockerfile`'s explicit `COPY api/*.py` runtime tree.

Request these two API-only Secret entries through Cameron (do not expose them as
frontend variables or pass them to shopper/MCP pods):

| Name | Default and meaning |
|---|---|
| `ATTACK_LAB_OPERATOR_IDS` | Empty denies everyone. Comma-separated exact `usr_<32 lowercase hex>` IDs returned by authenticated `/identity`; no email, wildcard or frontend role. Malformed configuration fails closed. |
| `ATTACK_LAB_ENABLED` | Missing/invalid/`0` disables control enablement. Exact `1` permits approved operators to create/change isolated preferences, **not scenario execution**. Keep `0` in production. |

Reuse current `CORS_ORIGINS` for explicit Bearer mutation Origin checks and current
`API_ORIGIN` for Next's backend verifier. Roll out API/migration and web together;
no deployment or shared migration has been performed by this change. Verify image
revisions, readiness, anonymous poison denial and ordinary-user operator denial.
`STORE_EVIL_MODE` remains ignored at runtime; no flag enables poisoned pages.

## UI server boundary and session handling

The preserved new `/attack-lab` page is protected **before rendering** by Next
`src/proxy.ts`, including RSC requests. Each request verifies current API session
and allowlist, never a browser role or hidden navigation. Navigation establishes
access with `POST /attack-lab/session` using the existing explicit Bearer. It
copies that verified JWT into a five-minute HttpOnly, SameSite=Strict,
`Path=/attack-lab` view cookie; it creates no new identity or spending authority.
Every cookie view rechecks the API. Logout/allowlist changes invalidate it; frontend
logout also clears it. The cookie cannot authenticate API mutations or session POST.
Cross-origin session POST/DELETE is rejected. Non-loopback cookies are Secure:
**the deployed operator page requires HTTPS**; the current plain-HTTP IP URL is
insufficient for this navigation flow. CLI Bearer tests do not prove browser TLS.

`GET /attack-lab/operator-view` is an additional constant, scriptless status view
requiring explicit verified Bearer (no ambient cookie). Mission Control offers
verified operators control preferences/status only; all execute buttons remain
unavailable. The new design and recorded source/incident evidence are retained.

The shared SSE provider deduplicates replay/effect restarts and remounts with the
human identity so prior-user history cannot survive an account switch. Purchase
attempt evidence is visible on both Mission Control and Payments, refreshed from
real persisted payment-event sequences and REST after reload.

## Enforced bounds versus remaining gates

SQL row locks enforce **five successful control mutations per operator/minute**
across API connections/replicas; streamed payloads are capped at 64 KiB before
parsing. Preference revisions reject stale updates. Namespace identity/rail and
history cannot be reassigned/deleted. The namespace contains no mandate, run,
grant, card or merchant fixture. Its empty identity is not proof of downstream
fixture/rail isolation.

One active scenario, three candidates, 120-second execution, bounded replay,
timeout cancellation and 15-minute scoped cleanup are **required but unimplemented**
because no executor is enabled. Disabling preferences has no worker to cancel;
responses state that explicitly. Full LAB-001–010 acceptance remains incomplete.

## Dependencies and exact owner next steps

1. **Cameron C02/C11:** return authoritative checkout owner/session, immutable
   revision, expiry/freeze; protect exact checkout-to-charge binding with separate
   credentials. Implement run/account generation barriers, atomic stop/issue/
   consume and loss recovery. Isolate demo fixtures/rail credentials; scoped reset
   must preserve audit and unresolved payment operations. Never expose global reset.
2. **All three H14:** agree the additive scopes/generations/worker acknowledgments
   in [the protocol proposal](../docs/H14_SCOPE_PROTOCOL_PROPOSAL.md). A contract-only
   PR remains required; no joint agreement or frozen schema change is claimed.
3. **Rishi R03/R04/R11/R12/R13:** consume trusted checkout proof, implement scoped
   human launch/delegation and durable financial worker/reconciliation only after
   those interfaces are agreed/tested. Current ledger is blocked preflight; private
   references confer no authority and a new retry cannot clear unknown state.
4. **Aditya A11/A12/A13/A14:** real bounded Graph with verified decisions, clean
   recovery and owning-worker fencing/cancel acknowledgment; persist genuine events.
   For Lab, accept only a scoped authenticated namespace/scenario command, obey
   limits/Stop and label live, local simulation and recorded replay accurately.
5. **All three:** negative destination bypass/race/restart tests, genuine positive
   authorized isolated scenario and selected-rail live evidence before activation.
   Cameron verifies HTTPS/CNI/PVC/Secret scope and rollout; no ordinary browser or
   model approval may bypass any missing gate.
