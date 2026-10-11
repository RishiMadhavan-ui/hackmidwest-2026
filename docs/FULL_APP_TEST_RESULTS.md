# Full-app implementation verification — October 11, 2026

Source on main integrates teammate work, preserves frozen shared models/events and historical migrations 0001–0012, and adds forward 0013–0015. No deployed/shared database, provider, teammate account or cloud service was mutated. Local resource tests use dedicated schemas in localhost PostgreSQL on port 55432 (leash_test_r02) and Redis on port 56379 (DB15); localhost-only guards refuse other targets. Redis is local atomic-engine evidence, not installed Valkey8/PVC proof.

## Actual output and scope

| Check | Actual final result | Environment / limit | Raw output |
|---|---|---|---|
| API full suite |193 tests OK,2 skipped | Real SQL/JWT/HTTP plus unit and mocked provider/rail transports. Gated legacy stack and full Graph acceptance excluded from default run; Graph run separately below. | [API](test-evidence/FULL_APP_API.txt) |
| Execution boundaries |9 tests OK | Real SQL/HTTP, rail doubles: private two-user credentials, audience/run expiry, same-price canonical block, original-event readback, expiry revocation/terminal unclaimed state with no false Graph ack | [Execution](test-evidence/FULL_APP_EXECUTION.txt) |
| Agents |180 passed,4 skipped | Actual SDK Graph/Agent and MCP fixtures; external inference/integration gates skipped. No genuine Akamai injection proof | [Agents](test-evidence/FULL_APP_AGENTS.txt) |
| Leash MCP |33 passed | SDK transport and backend doubles | [Leash MCP](test-evidence/FULL_APP_MCP_LEASH.txt) |
| Store MCP |47 passed | SDK/adaptation/evidence plus direct missing/rejected/expired/outage scope fail-closed tests | [Store MCP](test-evidence/FULL_APP_MCP_STORE.txt) |
| Store |30 passed,17 subtests | Simulated catalog/auth/owned/frozen legacy adapter; HTTP unit/mocked transport, no provider calls | [Store](test-evidence/FULL_APP_STORE.txt) |
| Payment rail |57 tests OK | Memory plus real isolated Redis atomic lease/epoch/stop/replay/quota, signed ASA local fixtures; no real sandbox | [Rail](test-evidence/FULL_APP_RAIL.txt) |
| Independent decision YAML |1 test OK,16 vectors | Pure rail/handler decision matrix; not full merchant/Graph evidence | [Decision](test-evidence/FULL_APP_DECISION.txt) |
| Full protected Graph stack |1 test OK (37.079s at this checkpoint) | Actual SDK Graph + real API/agents/store/rail/both MCP HTTP processes + PostgreSQL/Redis; only model choices scripted | [Graph stack](test-evidence/FULL_APP_GRAPH_STACK.txt) |
| Hosted acceptance |6 skipped | Explicit isolated account/API/operator/model/rollout not configured; updated to protected human/namespace launch, one Graph recovery | [Hosted](test-evidence/FULL_APP_HOSTED_E2E.txt) |
| Web destination/operator/proxy guards |6 passed | Node route tests, mocked backend + actual local HTTP fixture; no browser hydration | [Node](test-evidence/FULL_APP_NODE.txt) |
| Actual Next→API HTTP/proxy smoke |6 scoped assertions pass | Disposable real JWT/SQL test account; sign-in shell,3999 proposal,draft, ordinary operator denial/internal bypass. Authenticated client hydration not tested | [HTTP](test-evidence/FULL_APP_WEB_HTTP.txt) |
| Frontend lint |Exit0, no warnings/errors | ESLint affected/current source | [Lint](test-evidence/FULL_APP_WEB_LINT.txt) |
| Frontend build |Exit0 | Production Next TypeScript/build; Windows directory junction shim for traced dependency symlinks only, no app/dependency source change | [Build](test-evidence/FULL_APP_WEB_BUILD.txt) |
| Python correctness lint |All checks passed | Ruff E9/F63/F7/F82; no unrelated lane reformat | [Correctness](test-evidence/FULL_APP_CORRECTNESS_LINT.txt) |

Counts are individual suite results, not unique security-case counts. Regressions/fixes can change totals; only listed final raw output is authoritative. Initial/second/third FULL_APP_API and FULL_APP_WEB_HTTP_INITIAL and FULL_APP_STORE_INITIAL logs record corrected development failures, not current PASS. INCOMING/RISHI_OPERATOR logs are prior integration checkpoints, not current acceptance. Store/Node emit dependency deprecation/module-type warnings; they do not fail. The isolated unauthenticated Next dev smoke also reports that instant-navigation validation could not render its protected child segment; no client navigation acceptance is claimed, and the production build passes. Early Graph SSE-disconnect socket warnings were corrected by checking disconnect between replay records; final Graph output at this checkpoint is clean.

## What the full Graph test asserted

`api/tests/test_graph_stack.py:test_signature_attack_recovers_and_authorizes_through_real_mcp_and_rail` used a real human JWT, interpreted under40 as3999, saved an ordinary draft using a private shopper, then launched an explicitly confirmed fixed isolated scripted-mode mandate through the operator API. Actual Strands Graph invoked both MCP servers, attempted SUB-CARE-MO while claiming charger, received deterministic independent canonical block with no grant, ran investigation/quarantine, created a fresh context and selected CHG-65W-SAFE. Exactly one actual atomic local approval was persisted; original mandate hash/version retained. Actual tool/source/Graph/recovery/payment events reached durable audit/SSE; Last-Event-ID replay matched records. Ordinary account mandate remained proposed and purchases empty, foreign demo run inaccessible, refresh/history stable. Scoped reset retained original authorization and truthful no-reversal flag. A second real queued Graph stopped before authorization and rail revocation was acknowledged; no nonexistent Graph ack was fabricated.

Model calls were explicitly scripted and labeled; every transport/state/policy/financial decision was real. Do not claim the model was manipulated live, that an actual Lithic card was created, that authorization settled, or that deployed Kubernetes restarted safely.

## Reproduction

Run in each service's locked Python3.12 environment; for Windows use `.venv/Scripts/python.exe`, otherwise `uv run python`. Set LEASH_TEST_DATABASE_URL only to disposable localhost leash_test* DB; tests allocate unique schemas and remove them. Atomic suite accepts only dedicated `redis://127.0.0.1:56379/15`, never shared Valkey. Do not run rail tests (which flush testDB15) concurrently with full Graph acceptance.

- API: `python -m unittest discover -s tests -v`; execution focused: `... -p test_execution_security.py -v`.
- Actual full chain: API directory, set LEASH_TEST_STACK=1 + dedicated SQL/Redis, `python -m unittest discover -s tests -p test_graph_stack.py -v`. Child service environments contain generated test-only secrets, no inherited provider secrets; processes stop afterward.
- Agents: `python -m pytest -q `; MCP services/Store: `python -m pytest -q`; rail: `python -m unittest discover -s tests -v`.
- Root independent matrix: `services/webhook/.venv/Scripts/python.exe -m unittest discover -s tests -p test_decision_cases.py -v`.
- Hosted suite: `services/agents/.venv/Scripts/python.exe -m pytest tests/e2e -q`. Only intentionally enable LEASH_E2E=1 / LEASH_E2E_ISOLATED=1 with owned disposable demo account/API URL/current allowlisted USER_TOKEN; never enable against a shared demo user blindly.
- Web: `pnpm lint`, `pnpm build`; Node guard tests `node --experimental-strip-types --test tests/attack-lab-boundary.test.mjs tests/operator-view.test.mjs tests/mcp-proxy-config.test.mjs`.

## Deployed read-only inspection

After integrating Cameron's #21 connector and #22 catalog, an anonymous read-only check on the supplied HTTP demo address returned health/readyz 200, poison-selector 403 and unauthenticated Leash MCP 401. Its API OpenAPI lacks natural interpretation, durable shopping-run list, private evidence intake and isolated Lab execute routes. `/attack-lab` returns200 for an HTML shell, while the operator access API is 404; that is not backend authorization or current source rollout proof. No credentials, fixture mutation, charge or deployment were used. [Exact HTTP output](test-evidence/FULL_APP_DEPLOYED_READONLY.txt).

## Unverified or incomplete

Local configuration has no inference endpoint/key; live model tests cannot run here. The desktop browser could not attach/navigate reliably, so no interactive form/confirmation/Stop screenshot or accessibility acceptance is claimed. Existing user's dev server was preserved; a separate test-only frontend copy/API were used for HTTP checks. Docker image build/actual runtime/pods, latest source rollout, TLS/CNI/Secret/PVC/rolling restart, genuine Akamai/injection, broader live interpretation, complete Lithic verified-card/ASA correlation/readback/clearing, measured provider p50/p95, all-phase failures and the timed demo are not established by these outputs. Forward migration/source deployment is necessary for the screenshot-era site to show fixes.

All 147 case definitions map individually in [coverage](LEASH_SECURITY_COVERAGE.md):72 scoped PASS,52 NOT_RUN,5 MISSING,18 BLOCKED_EXTERNAL. This report does not waive remaining gates or convert related unit tests into full live cases. [Current handoff](../api/full-app-handoff.md) and [build plan](../Leash-build-plan.md#next-work-in-dependency-order) assign exact next actions.
