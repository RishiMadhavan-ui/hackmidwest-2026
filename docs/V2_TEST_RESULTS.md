# V2 execution evidence and limits

**Current R03/R11 evidence:** [149-test API and supporting regression results](R03_R11_TEST_RESULTS.md)
supersede the prior integration suite counts below. Full canonical observation,
committed preflight identity, retry/crash/scope barriers and Stop races are tested;
financial activation, provider reconciliation and actual Graph remain unfinished.
Historical outputs below are preserved without modification.

## Latest integration rerun on Cameron d773079

The original f2f50a5 evidence below is retained as history. Current main includes
Cameron's PR #14 and the V2/payment containment fixes described in
[MAIN_INTEGRATION_HANDOFF.md](MAIN_INTEGRATION_HANDOFF.md). Tests used the same
guarded disposable localhost PostgreSQL/Redis setup; no hosted/provider integration
was enabled. Current output artifacts have INTEGRATION_* names.

| Suite / command | Latest observed output | Actual scope |
|---|---|---|
| API, same full unittest command/env as E_API below | [127 passed in 47.367s](test-evidence/INTEGRATION_API.txt), no skips | 94 unit/mock, 32 real PostgreSQL SQL/HTTP, 1 local Next/API/store/Redis/rail smoke. Includes owned run/Stop/payment preflight and same-user cross-agent read isolation. No usable purchase grant is issued. |
| Rail, same unittest command/env as E_RAIL | [45 passed in 1.310s](test-evidence/INTEGRATION_RAIL.txt) | 14 isolated Redis tests plus memory/policy/TestClient/mocked ASA; no live provider callback. |
| Store, same pytest command as E_STORE | [19 passed in 1.89s](test-evidence/INTEGRATION_STORE.txt) | Simulated catalog, storefront/start/bind and explicit completion gate; no merchant charge claimed. |
| Agents, same non-live pytest command as E_AGENTS | [131 passed, 2 skipped in 51.67s](test-evidence/INTEGRATION_AGENTS.txt) | Scripted/mocked model and local MCP transport; both live inference checks skipped. No real Graph or live injection. |
| MCP Leash, same pytest command as E_MCP_LEASH | [33 passed in 8.58s](test-evidence/INTEGRATION_MCP_LEASH.txt) | Real SDK adapter with mocked API. |
| MCP Store, same pytest command as E_MCP_STORE | [40 passed in 10.10s](test-evidence/INTEGRATION_MCP_STORE.txt) | Real SDK adapter with mocked merchant. |
| Policy matrix, same unittest command as E_DECISION | [1 runner passed in 0.098s](test-evidence/INTEGRATION_DECISION.txt), all 16 YAML cases | Pure policy/handler fixtures, not a full live acceptance flow. |
| Gated E2E, same pytest command as E_E2E | [6 skipped in 0.05s](test-evidence/INTEGRATION_E2E.txt) | LEASH_E2E unset; no successful live purchase/recovery/Stop demo claimed. |
| web: pnpm lint / pnpm build | [Lint exit 0](test-evidence/INTEGRATION_WEB_LINT.txt), [production build exit 0](test-evidence/INTEGRATION_WEB_BUILD.txt) | Includes Cameron's storefront checkout-start route and both human controls. No browser/deployed acceptance claim. |

The new methods test security containment. They do not promote missing complete
137-case scenarios. The assessment remains 35 scoped PASS / 46 NOT_RUN /
51 MISSING / 5 BLOCKED_EXTERNAL. Initial isolated Redis startup needed package
runtime restoration; no system packages/shared services were installed. A sandboxed
store run stalled and frontend dependency realpath was denied; reruns with access
to existing dependency links passed. These restrictions were not ignored as passes.
Evidence terminal whitespace/line endings are normalized without changing results.
Staged whitespace checks exclude only the byte-exact supplied case file, whose
two original Markdown hard breaks are intentionally preserved and hash-verified.

## Original pre-integration V2 evidence

Executed October 10, 2026 Central (October 11 UTC) on Windows main after clean
baseline f2f50a5. Raw outputs below carry their collection timestamp and are
preserved with this documentation. No deployed database/cluster, Lithic API,
ASA enrollment, live inference, customer funds or teammate credentials were used.

| Evidence | Actual command / setup | Observed result | Scope |
|---|---|---|---|
| E_API [output](test-evidence/V2_API.txt) | Root: `api/.venv/Scripts/python.exe -m unittest discover -s api/tests -v`; LEASH_TEST_DATABASE_URL=disposable localhost:55432/leash_test_r02, LEASH_TEST_VALKEY_URL=localhost:56379/15, LEASH_TEST_STACK=1; build web first | **117 passed in 31.260s**, no skips | 86 unit/mock cases, 30 real PostgreSQL SQL/HTTP tests, 1 real local Next/API/simulated-store/Redis/rail smoke. Provider responses mocked; rail grants seeded explicitly as backend fixtures. |
| E_RAIL [output](test-evidence/V2_RAIL.txt) | services/webhook: `.venv/Scripts/python.exe -m unittest discover -s tests -v`; LEASH_TEST_VALKEY_URL=redis://127.0.0.1:56379/15 | **45 passed in 1.191s** | 14 real Redis tests, remaining memory/pure/TestClient/mocked ASA. No live signed provider callback or actual merchant charge. |
| E_STORE [output](test-evidence/V2_STORE.txt) | services/store: `.venv/Scripts/python.exe -m pytest -q` | **15 passed in 1.55s** | Simulated catalog and TestClient; owned durable checkout/payment flow still missing. One dependency deprecation warning. |
| E_AGENTS [output](test-evidence/V2_AGENTS.txt) | services/agents: `.venv/Scripts/python.exe -m pytest -q -m 'not live'`; uv on PATH | **131 passed, 2 skipped in 41.86s** | Scripted model/hooks/guardian/credentials/spool and real local MCP SDK transport with fake services. Skipped live inference; no real Graph or live injection. |
| E_MCP_LEASH [output](test-evidence/V2_MCP_LEASH.txt) | services/mcp-leash: `.venv/Scripts/python.exe -m pytest -q` | **33 passed in 6.55s** | SDK client/tool adapter against mocked API; no real payment route. |
| E_MCP_STORE [output](test-evidence/V2_MCP_STORE.txt) | services/mcp-store: `.venv/Scripts/python.exe -m pytest -q` | **40 passed in 7.97s** | SDK client/store-only URL/auth/snapshot/checkout adapter against mocked store. |
| E_DECISION [output](test-evidence/V2_DECISION.txt) | Root: `services/webhook/.venv/Scripts/python.exe -m unittest discover -s tests -p test_decision_cases.py -v` | **1 runner passed in 0.097s**, all **16 rail YAML cases** | Independent policy fixtures and handler cases. Semantic YAML descriptions are not a full live acceptance suite. |
| E_E2E [output](test-evidence/V2_E2E.txt) | Root: `services/agents/.venv/Scripts/python.exe -m pytest tests/e2e -q`; LEASH_E2E unset | **6 skipped in 0.07s** | Actual gated collection; stack/payment/Graph/live credentials missing. No E2E success claimed. |
| Web lint [output](test-evidence/V2_WEB_LINT.txt) | web: `pnpm lint` | Exit 0, no findings | Final two-control frontend source; earlier effect-lifecycle failure corrected before this run. |
| Web build [output](test-evidence/V2_WEB_BUILD.txt) | web: `pnpm build` | Exit 0, production build and TypeScript completed | Built profile controls/SSE proxy; no browser interaction/accessibility or hosted build proof. |

Correctness lint: installed ruff, `check` on changed API/provider/test Python with
`--select E9,F63,F7,F82`, output **All checks passed!** Full repository formatting
was not performed. API's deliberate startup-failure test logs ERROR before passing;
that is injected failure coverage, not a failing suite.

Disposable PostgreSQL uses a new guarded leash_test* database, each SQL/stack test
suite creates/drops its own schema. Redis test guard only permits localhost:56379
database 15 and clears only that isolated DB. Redis 6.0.16 exercises the current
Lua/atomic code; this is not production Valkey-version/cluster compatibility proof.
The local binaries were restored into a test directory from configured Ubuntu
repositories after temporary files disappeared, without installing or changing a
shared service. All test-owned servers were stopped after verification.

The exact [137-case specification](LEASH_SECURITY_TEST_CASES.md) is unchanged. Its
[coverage index](LEASH_SECURITY_COVERAGE.md) assesses **35 PASS, 46 NOT_RUN,
51 MISSING, 5 BLOCKED_EXTERNAL**. Passing 117 API methods does not mean 117 of the
137 acceptance cases pass; several methods test grouped predicates and several
full scenarios need unimplemented services. Related evidence remains explicitly
partial. No failed case was suppressed or marked passed from source inspection.

Final document/source checks passed: 137 unique source cases and exactly matching
137 index IDs; source attachment SHA256 unchanged; all local Markdown file links
resolve; case counts match 35/46/51/5; frozen models/events and migrations 0001–0006
unchanged; Git whitespace diff clean. All 20 existing Kubernetes YAML documents
parse, with no deployment changes; this does not prove live CNI/Secrets/PVC/ingress
behavior. A final origin fetch found no teammate pushes beyond the starting main.

Remaining P0 limits: actual bounded Graph/owning-worker cancellation and clean
recovery, ephemeral run-scoped credentials/human launch, complete verified
merchant retrieval/freeze/charge, durable issuance/payment/reconciliation ledger,
run financial barriers/generations/Valkey loss recovery, full lifecycle SSE/product
UI, sandbox configuration/correlation and existing LKE deployment/rehearsal.
Use [V2 handoff](../api/v2-stop-handoff.md) and the build plan for owner/gates.
