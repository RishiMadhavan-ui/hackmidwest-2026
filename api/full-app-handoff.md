# Integrated full-app handoff — October 11, 2026

Current main preserves all teammate merges through7033f4b while retaining private shopper ownership, exact agent/mode authority and separate isolated attack lanes. User authorized these cross-lane integration fixes; path ownership and frozen R01 contracts remain unchanged. No deployed environment/shared DB/provider mutation occurred. [Actual test results](../docs/FULL_APP_TEST_RESULTS.md) and [147-case coverage](../docs/LEASH_SECURITY_COVERAGE.md) are the completion boundary.

## What works in source

- Natural instruction generates proposed terms; `under $40` means3999cents. One item/one purchase/one-hour/no-recurring defaults are disclosed for human review. Broader instructions use configured inference or return clarification/error, never hidden spending authority. Edit/save/explicitly confirm exact version/hash.
- New signed-in accounts draft with their own immutable private live shopper, without a global token rebinding. The API dispatches a private ≤180-second credential and launch secret to agents only; browser receives durable run ID/status. Temporary credentials cannot approve/stop/register broader authority.
- Ordinary `POST /shopping/start` runs live clean shopping. Actual SDK Graph uses both MCP services, retrieves independently authenticated owned/frozen checkout facts, deterministically blocks unauthorized candidates, advisory guardian/quarantine/fresh context recovers only safe pre-payment denials, and ends on one actual authorization.
- Protected local financial activation commits operation first, binds original event/checkout/hash/run/lease/epoch and atomically consumes one grant. Legacy unscoped requests cannot create money authority. Every tool/merchant/rail boundary checks current scope; no unrestricted fallback.
- Run Stop and Emergency Kill are separate, owned and durable. Effective rail/Graph/provider statuses reported independently; already authorized transactions are not reversed. Unknown finance blocks another purchase. Expiry/control repair revokes and reads back the original event only.
- Persisted genuine event intake, post-worker-expiry durable evidence delivery, owned SSE/Last-Event-ID, immutable comparison/history and safe original-outcome reconcile survive reads/refresh. Backend requires actual original rail decision to report authorized; never calls it settlement.
- Operator Lab uses real JWT+stable-ID allowlist+server flag; separate namespace/demo identity; fixed3999/no-recurring confirmed authority; scripted fallback or live Graph;120second/three-candidate bound, five successful mutations/minute, one active scenario,64KiB bodies. Cleanup disables/revokes/stops only demo scope and preserves history. Public poison/preview, arbitrary tamper/replay/provider calls remain denied.

## Configuration and deployment — Cameron and API operator

Rebuild/redeploy **API, web, agents, mcp-leash, mcp-store, store and webhook** from the same main SHA. Existing Kubernetes/root build contexts remain; API copies `api/*.py`, shared sources and forward migrations. Forward0013 (Lab),0014 (run credentials),0015 (Lab execution) follow unchanged0001–0012. Startup checks/applies checksummed migrations; explicit `uv run python manage.py migrate` uses the intended operator DB environment. Preserve original signing key/data; diagnose failed migrations before changing anything. Do not re-run tests against the shared DB or wipe deployed Valkey.

Required configured execution:

| Receiver | Settings / trust role |
|---|---|
| API | DATABASE_URL/JWT_SECRET/MANDATE_SIGNING_KEY, `LEASH_EXECUTION_ENABLED=1`, AGENTS_URL/AGENTS_SERVICE_TOKEN, STORE_URL/MERCHANT_BACKEND_TOKEN, WEBHOOK_URL/WEBHOOK_INTERNAL_TOKEN, RAIL_EVENT_TOKEN, exact CORS origins; workshop model env for broad interpretation |
| Agents | API_URL, AGENTS_SERVICE_TOKEN, MCP_LEASH_URL/MCP_STORE_URL, STORE_URL, STORE_MCP_TOKEN, configured workshop OPENAI_BASE_URL/OPENAI_API_KEY/CHAT_MODEL or matched INFERENCE pair; TRACE_SPOOL_DIR on persistent volume |
| Leash MCP | API_URL and allowed cluster host; forwards exact private bearer/scope to API |
| Store MCP | API_URL, STORE_URL, STORE_MCP_TOKEN, STORE_API_TOKEN and distinct STORE_CHARGE_TOKEN for protected completion; optional OBJ settings for truthful snapshot storage |
| Store | LEASH_EXECUTION_ENABLED1, API_URL/MERCHANT_BACKEND_TOKEN, STORE_API_TOKEN/STORE_CHARGE_TOKEN, WEBHOOK_URL/WEBHOOK_CHARGE_TOKEN; scope validated by API |
| Rail | Persistent VALKEY_URL, API_URL/RAIL_EVENT_TOKEN, distinct WEBHOOK_INTERNAL_TOKEN/WEBHOOK_CHARGE_TOKEN; no silent memory fallback |
| Web | build NEXT_PUBLIC_API_URL=/backend, API_ORIGIN=http://api:8000, STORE_ORIGIN=http://store:8000; public MCP proxy stays disabled; exact HMAC-protected ASA rewrite only if configured |

Generate distinct≥32-character random secrets, keep server-side/Kubernetes only; do not echo them. New ordinary-account shopping needs no manually reassigned global AGENT_TOKEN_SHOPPER. Legacy live/scripted operator tokens remain separate and preserve their original owners. Private worker credentials expire and are only hashed in SQL; trace delivery uses the service-only evidence lane after expiry.

Attack Lab additionally requires API `ATTACK_LAB_ENABLED=1` and `ATTACK_LAB_OPERATOR_USER_IDS=usr_<32 hex>,...` from real `/identity` results. Empty/malformed/conflicting aliases deny all. Namespace starts disabled and operator explicitly enables it. Never use provider/static demo token as operator authority. Keep defaults0 in production. Neither ATTACK_LAB_TOKEN, STORE_EVIL_MODE nor frontend flags can re-enable poison.

Actual HTTP demo173.255.199.245 cannot use Secure full-view session cookies. Authorized operators use Mission Control's Bearer-verified Lab section; full `/attack-lab` view requires HTTPS or localhost. Configure TLS rather than weaken cookies. Local frontend talking to hosted API needs build `NEXT_PUBLIC_API_URL=/backend` and server API_ORIGIN pointing to the deployed `/backend` endpoint; local DB variables are unnecessary when only running frontend. Full local backend requires its own DATABASE_URL/JWT/signing/service environments.

## Callable human/operator sequence

1. Human `/auth/login` → `/identity`; `POST /mandates/interpret {instruction}` → structured proposal; `POST /mandates/draft` → proposed record; `POST /mandates/{id}/approve {version,canonical_payload_hash,confirmed:true}`. Edits require saving a replacement before confirmation.
2. `POST /shopping/start {mandate_id,agent_mode:"live",scenario:"charger"}` → queued or dispatch_unverified with stable run ID. Read `/shopping/runs?mandate_id=...` and `/agent-runs/{run}/execution`; inspect ambiguity/stop that original run, never blindly relaunch a timed-out request.
3. Run Stop: `POST /agent-runs/{run}/stop`; account Kill uses `POST /killswitch {on:true}`. Report actual rail/Graph/provider status separately. SQL commit is intent, not atomic financial enforcement acknowledgment.
4. History `/purchase-attempts`, evidence `/purchase-attempts/{id}`, original-outcome readback `POST /purchase-attempts/{id}/reconcile`; refresh/reconcile never buys again. `/activity/stream` with Bearer/Last-Event-ID replays actual owned records.
5. Operator `/attack-lab/access` → POST `/attack-lab/namespaces {}` → POST namespace `/control {enabled:true,expected_revision}` → `/draft {scenario:"signature_attack",mode:"live"}` → explicitly `/execute {mandate_id,version,canonical_payload_hash,confirmed:true}`. Read scoped `/history`; `/runs/{run}/stop`, `/cleanup` or `/reset` only remove demo authority and retain audit. For declared outage fallback choose mode scripted; do not show it as genuine model injection.

## Remaining acceptance work, dependency order

Cameron: deploy same-SHA images/migrations, confirm real Secrets/probes/PVC/TLS/CNI and public poison denial, then isolated restart/epoch-loss/race rehearsal. Rishi: validate two-account natural review/confirmation/launch and browser reload/control/history, remaining P0 identity/financial/UI cases; retain original147 index. Aditya: capture genuine Akamai tool calling/live injected wrong checkout → independent deny → actual clean recovery under unchanged hash, cancellation during inference/tool/guardian/recovery. All: D1–D4 timed rehearsal and truthful local/provider labels.

Lithic sandbox **is not a complete purchase path**: trusted ASA checkout-to-charge correlation, verified SINGLE_USE issuance/idempotent readback/run-card association and actual clearing/closure integration are missing. Keep ASA approvals and unrestricted simulator triggers disabled. No live customer funds. User provided a friend's deployed positive activity trace; it is human-provided evidence of that older run, not proof of latest rollout or live injection/recovery.
