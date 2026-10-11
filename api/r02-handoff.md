# R02: persisted purchase authority

**Current implementation follow-up:** see [alignment-fixes-handoff.md](alignment-fixes-handoff.md) for identity-only signup, provenance/SSE, strict local rail, durable stop/provider control and remaining merchant/payment/Graph work. Earlier captures/test counts below describe their named revisions, not current deployed behavior.

R02 implements mandate proposal, exact human confirmation, read/list/history,
replacement, revocation and agent-run registration. It preserves Cameron's
UUID-based signup/login/profile API and leaves the frozen R01 contracts unchanged.
Shared models come from the existing source tree; installable shared packaging
remains Cameron's C01 task.

## Ownership and credentials

Existing account UUIDs map deterministically to `usr_` plus their UUID hex.
`GET /identity` returns this LEASH identity for a human JWT. `/auth/me` continues
to return the existing UUID. The migration backfills existing users; newly created
users get the same mapping on their first authenticated LEASH request.

The optional demo `USER_TOKEN` authenticates only its configured `DEMO_USER_ID`
(default `usr_demo`). It must be a distinct, random secret of at least 32 characters.
Normal browser users use their existing JWT, not a frontend demo token.

An agent credential has an explicit, operator-provisioned user, agent ID and one
allowed mode (`live` or `scripted`). No agent HTTP payload can choose its owner.
Only a SHA-256 credential fingerprint is stored. Use a random credential, supplied
through an environment variable/Kubernetes Secret. Rebinding an agent can rotate
its token/mode but cannot transfer it to another human. Old tokens stop working.
Mode is an authorized execution label; registration alone does not prove that
inference or tool execution occurred.

Operator commands run from `api/` with server environment configured:

```text
python manage.py migrate
python manage.py demo-user
python manage.py bind-agent --user-id usr_demo --agent-id agt_shopper --token-env AGENT_TOKEN_SHOPPER --mode live
python manage.py bind-agent --user-id usr_demo --agent-id agt_shopper_scripted --token-env AGENT_TOKEN_SHOPPER_SCRIPTED --mode scripted
```

For a real account, use its `GET /identity` result instead of `usr_demo`.
Alternatively, `python manage.py map-user --auth-user-id <existing UUID>` creates
that mapping. `--token-env` defaults to `AGENT_TOKEN_SHOPPER`; it never accepts a
token on the command line. For scripted fixtures, use the separate scripted agent/token above. Each agent
requires its own human-confirmed mandates; a scripted agent cannot use the live
agent's mandate. Bind both to the same intended human, never label a fixture live.

## Routes and request bodies

| Route | Caller | Result |
|---|---|---|
| `POST /mandates/propose` | Bound agent | 201 proposed `PurchaseMandate`; raw original description and all semantic fields retained |
| `GET /mandates?status=active` | Human or bound agent | `{items: [...]}`; agents see only mandates assigned to them, within the validity window |
| `GET /mandates/{id}` | Owner human or assigned agent | Current version; expired records report `expired` |
| `GET /mandates/{id}/versions` | Owner human | Immutable version history and effective lifecycle statuses |
| `POST /mandates/{id}/approve` | Owner human | Confirm exact version/hash; sign; become active |
| `PATCH /mandates/{id}` | Owner human | Supersede old version and create a new proposed version; fresh approval required |
| `POST /mandates/{id}/revoke` | Owner human | Revoke current version; no reactivation |
| `POST /agent-runs` | Assigned agent | 201 committed `AgentRun` with exact ID/mode echoed and server-derived owner/version/hash |
| `GET /health`, `GET /healthz` | Public | Process liveness |
| `GET /readyz` | Public | 200 only after successful migrations and a live database check; otherwise 503 |

Proposal uses R01 `MandateProposal` exactly. If expiry is omitted, the API supplies
30 minutes from the resolved validity start and returns that explicit bound for
human review. Expired proposals fail. Amounts/quantity/booleans and UTC remain strict.

Approval requires the values displayed from the current draft:

```json
{"version":1,"canonical_payload_hash":"<draft's 64-character hash>","confirmed":true}
```

Replacement uses the same current-version binding plus a complete new proposal:

```json
{
  "version":1,
  "canonical_payload_hash":"<current hash>",
  "proposal":{"description":"Buy a USB-C charger. No subscriptions.","category":"laptop_charger","max_cents":3999}
}
```

Revocation uses `{version, canonical_payload_hash}`. Stale version/hash returns
409; cross-owner or cross-agent mandate access returns 404. Missing/wrong role
credentials return 401/403. Validation returns 422 and outages return 503. Error
bodies are `{"detail":"plain string"}`, without input values, SQL or credentials.

Registration matches Aditya's current `{id, mandate_id, agent_mode, model, provider}`.
It requires a signed current active mandate within its validity window. An identical
retry returns the originally committed run; altered content/ID collisions return
409, and unauthorized mode returns 403. Replacement/revocation/expiry makes old
registrations unusable. The record's model/provider are agent-reported metadata.

## Signing, history and transactions

`MANDATE_SIGNING_KEY` is a base64 32-byte Ed25519 seed held by the server. Missing
or malformed configuration returns 503 without confirming anything. This is a
demo server signature, not a device passkey or AP2 claim. The signed canonical
envelope binds `purpose: leash.mandate-confirmation.v1`, R01 `mandate_payload()`,
the canonical payload hash and `approved_at`. Stored confirmation public keys
permit verification of historical versions after signing-key rotation.

SQL migrations preserve the existing users table and add identity/agent bindings,
mandate heads, immutable draft versions, confirmations, lifecycle transitions,
registered runs and audit records. Database triggers reject UPDATE/DELETE of
historical records. This is application/database integrity under the API-only
writer assumption, not protection against a malicious database administrator.

Migrations are serialized with a transaction-scoped advisory lock; checksums
detect edits to already-applied files. All pending migrations commit together.
Mandate changes lock the current head; confirmations recheck expiry after taking
the lock. An identical confirmation retry has one signature/event. Competing
replacements cannot both consume the same old version. A run is bound while holding
the same head lock. HTTP responses occur after transaction commit.

Each authority change and its sanitized audit event commit in the same SQL
transaction. `audit_deliveries` keeps pending transport work separately from the
append-only record. R06 still supplies Valkey/SSE delivery and provenance ingestion.
No successful delivery or dashboard stream is claimed by this SQL outbox.

## Deployment handoff to Cameron

Rishi's API Dockerfile now includes every API module, the shared sources and SQL
migrations. **It requires repository-root build context.** Cameron must change
the API build line in `scripts/deploy_lke.sh` to:

```bash
"$BUILDX" build --platform "$PLATFORM" -f "$REPO/api/Dockerfile" -t "$API_IMAGE" --load "$REPO"
```

Equivalent manual build: `docker build -f api/Dockerfile -t leash-api .`.
The Dockerfile-specific ignore file allowlists only required sources/locks/migrations;
it excludes `.env`, credentials, tests and local environments from the build context.
Use `/readyz` for the API readiness probe and retain `/health` for liveness.
Ensure existing `DATABASE_URL`, `JWT_SECRET`, `MANDATE_SIGNING_KEY` and agent/demo
credential settings are supplied through Secrets. Apply migrations, bind the
live and scripted agents to the same intended human and their respective mode, then deploy. No changes were made to
Cameron's scripts, manifests or environment template, and no shared database was
migrated by this implementation session.

## Validation and limits

The full API test suite includes 52 R01 regressions, signature/role/error tests,
and real PostgreSQL HTTP/transaction/concurrency tests. Run from the repo root:

```powershell
.\api\.venv\Scripts\python.exe -m unittest discover -s api/tests -v
```

Set `LEASH_TEST_DATABASE_URL` to an explicitly disposable localhost database whose
name begins `leash_test` to run the SQL tests. They create/drop only a generated
test schema; without this test setting, SQL tests are visibly skipped. They never
load the team's `.env`. Test credentials/keys are generated only in memory.

No payment route, grant, card, checkout verification, Valkey rail invalidation,
provenance endpoint or live purchase flow is implemented here. Replacement/revocation
immediately invalidate SQL authority and run registration. Before grants exist,
R04/R05 must coordinate their invalidation with Cameron's atomic Valkey protocol;
asynchronous audit delivery alone cannot invalidate an already-issued rail grant.
No hosted deployment or complete Compose boot is claimed.

Implementation references: [PyNaCl signing](https://pynacl.readthedocs.io/en/latest/signing/) and [Psycopg transaction contexts](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).

## MCP integration and remaining handoff

Main at `9edadab` merges Cameron's two MCP deployments and Aditya's Store tools.
`services/mcp-leash/` and `services/mcp-store/` both expose `/mcp`, on 8002 and
8003; the shopper uses `MCP_LEASH_URL` and `MCP_STORE_URL`. Aditya owns both
services and Cameron owns the underlying merchant/deployment. R02's frozen
contracts remain unchanged. The peer capture helper follows the moved paths and
server-side source evidence; its HTTP, storage and model calls are fixture-only.

Aditya's latest separate mode credentials are pushed on `aditya-mcp` at `ec6b9a9`
but are not in the `9edadab` baseline. Merge them and supply the distinct
`AGENT_TOKEN_SHOPPER_SCRIPTED` through the agents' Secret before exercising
fallbacks. Registration, Leash MCP, trace identity and trace outbox must all use
the run's own credential. Provision with the operator commands above; no shared
credentials, database bindings or environment settings were changed in this merge.

Cameron agreed to apply the build-context/readiness changes after R02 merges.
Until then, the existing deploy script's API build will fail; this is a known
handoff gap, not a claim that main is deployable. Add persistent storage at
`/app/trace-spool` for traces to survive pod replacement. The current public MCP
web rewrites also remain a team reconciliation item against the earlier
internal-only request. R02 changes neither teammate implementation nor deployment.

## Merge verification — October 10

After integrating `9edadab`, the API suite passes 81 tests with all 19 real
PostgreSQL tests enabled. Leash MCP passes 33 locked tests; Store MCP passes 40
locked tests. The merged agents runtime passes 120 tests; the two subprocess
wiring tests initially skipped for missing `uv` on PATH pass in a targeted rerun
with that path configured, for 122 agent tests validated. Two live-inference
tests remain deselected. The wiring services use stub responses, not real payment enforcement. The refreshed
fixture capture and its contract tests pass. Ruff E4/E7/E9/F, Markdown links,
fences, conflict-marker and whitespace checks pass. Frozen R01 files are unchanged.
No real inference, complete merchant/payment flow, fresh Docker build or hosted
deployment is claimed; Compose is still absent. The disposable localhost test
server is stopped after verification. The shared database remains untouched.

## Current post-merge check — `266a805`

Both teammate handoffs are now merged. Aditya's mode-bound credentials are used
for registration, Leash MCP and isolated trace lanes; fallback mandates belong to
the scripted agent. Cameron's deploy script uses root context and `api/Dockerfile`,
API readiness uses `/readyz`, liveness uses its `/healthz` alias, and the agents
manifest mounts a 5Gi PVC at `/app/trace-spool`. The scripted credential is named
in `.env.example` and supplied through `app-env`; actual values and bindings were
not read or changed. Public API health/readiness returned 200. PVC attachment and
end-to-end purchase behavior were not inspected.

The capture helper now passes an explicit fixture scripted token to registration
and verifies the bearer header. Contract tests use the refreshed `266a805` capture;
prior captures remain historical. Signup regression inputs follow the new fields,
with account/card provider calls mocked. Migration replay expects all three SQL
migrations. No provider, database provisioning or R03 implementation is performed.

Historical issue identified before the card-authority fix in `api/cards.py`: agent/service tokens may
supply another user's UUID and mint a card without a confirmed mandate, trusted
checkout or grant. A fixture-only HTTP probe returned 201 and invoked the mocked
issuer once, without mandate context. Signup also creates an OPEN VIRTUAL card
outside the mandate chain. Coordinate with Cameron before enabling this as a
purchase path; the cleanup deliberately does not redefine the card integration.

Cleanup validation: 81 API tests pass with all 19 PostgreSQL tests enabled and all
three migrations applied. The current merged agents suite passes 130 tests,
including local subprocess wiring; two live inference tests are deselected.
Refreshed peer capture, correctness lint E4/E7/E9/F and documentation/whitespace
checks pass. A redundant SQL f-string prefix in auth was removed without changing
the query. The disposable PostgreSQL instance was stopped; no shared database,
Secret or provisioning changes were made. R03 remains untouched.

## Direct card authority fix

`POST /cards` is deprecated and cannot issue an instrument. Missing/invalid
credentials return 401; configured agent/service credentials return 403. A valid
human JWT is checked against the actual account; another `user_id` returns 403,
and direct issuance for the owner's account returns 409. Correlations or
caller-supplied grants cannot activate issuance. No provider call or card insert
is reachable from this route. Card metadata GET routes use the same human-only
account check and scope SQL to that UUID; details never include PAN/CVV.

Cameron's Lithic wrapper remains unchanged and available to the future internal
verified payment flow. Existing signup/balance integration is preserved; its
sandbox card is not a confirmed purchase grant. No new `/payments` flow, checkout
verification or R03 implementation is included. Existing provider cards were not
paused/revoked, and no shared database, credential or deployed service was changed.
Cameron must deploy the patched API before its HTTP behavior changes in LKE.

Card-fix validation: all 90 API tests pass, including nine new card-authority/
provider-adapter tests and all 19 disposable PostgreSQL regressions. Correctness
lint E4/E7/E9/F, documentation links/fences/conflict markers and whitespace pass.
Frozen shared contracts and teammate services are unchanged. The existing API
Dockerfile copies `api/*.py`, including the changed cards module. No real provider
call, hosted deployment or complete Compose boot is claimed; Compose is absent.
