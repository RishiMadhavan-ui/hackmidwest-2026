# R02: persisted purchase authority

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
python manage.py bind-agent --user-id usr_demo --agent-id agt_shopper --mode live
```

For a real account, use its `GET /identity` result instead of `usr_demo`.
Alternatively, `python manage.py map-user --auth-user-id <existing UUID>` creates
that mapping. `--token-env` defaults to `AGENT_TOKEN_SHOPPER`; it never accepts a
token on the command line. For a scripted fixture, provision scripted mode explicitly
or use a separate agent credential; do not label it live.

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
shopper to the intended human and mode, then deploy. No changes were made to
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

## Concurrent MCP changes to reconcile

At the final refresh, main remains `916e01b`. Aditya's `cc17e79` adds Store
`/store/mcp` alongside Leash `/mcp` in one service. Its financial mandate and
registration payloads remain compatible with R02; its changed hooks are not part
of the earlier R01 wire capture, and this session does not claim its new suite passes.

Cameron's [PR #6](https://github.com/RishiMadhavan-ui/hackmidwest-2026/pull/6)
instead creates separate `mcp-leash`/`mcp-store` deployments/directories and
`MCP_LEASH_URL`/`MCP_STORE_URL`, with a store scaffold. That differs from Aditya's
new implementation and the latest accepted two-endpoint direction. The owners
must reconcile deployment, paths and URLs before merging that integration;
R02 does not choose or rewrite their code. PR #6 still uses `api/` build context,
so the API root-context/probe handoff above is still required whichever MCP layout
they select. Preserve R01/R02 status in docs rather than restoring stale scaffold
claims. Directory renames also require updating Rishi's peer-capture utility at
integration time. No MCP or teammate branch is merged by this R02 task.
