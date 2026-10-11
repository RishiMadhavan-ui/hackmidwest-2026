# R03/R11 execution evidence

Executed October 11, 2026 on main over `11d6696`. The final API/schema changes
are described in [the handoff](../api/r03-r11-handoff.md). No shared database,
deployed service, provider, human account or teammate credential was used.
Tests guard PostgreSQL to localhost/leash_test* with a unique disposable schema.
Redis is an extracted temporary Redis 6 binary on localhost:56379/database 15;
these are not deployed Valkey 8 or Kubernetes restart tests.

| Suite / actual command | Final output | Scope and limits |
|---|---|---|
| Root API: `api/.venv/Scripts/python.exe -m unittest discover -s api/tests -v` with LEASH_TEST_DATABASE_URL=localhost:55432/leash_test_r02, LEASH_TEST_VALKEY_URL=redis://127.0.0.1:56379/15, LEASH_TEST_STACK=1; web built first | [149 passed in 43.789s](test-evidence/R03_R11_API.txt), no skips | 94 unit/mock, 54 real PostgreSQL SQL/HTTP, 1 real local Next/API/store/Redis/rail smoke. Merchant/provider responses mocked in SQL payment tests; stack grants explicitly seeded as fixtures. No usable grant issued by preflight |
| services/webhook: `.venv/Scripts/python.exe -m unittest discover -s tests -v`, same disposable Redis URL | [45 passed in 1.713s](test-evidence/R03_R11_RAIL.txt) | Includes 14 actual Redis Lua/atomic tests, remaining memory/policy/HTTP/mocked ASA. No live provider |
| services/store: `.venv/Scripts/python.exe -m pytest -q` | [19 passed in 2.33s](test-evidence/R03_R11_STORE.txt) | Catalog/TestClient/completion disabled; one httpx/Starlette dependency deprecation warning |
| services/mcp-leash: `.venv/Scripts/python.exe -m pytest -q` | [33 passed in 7.56s](test-evidence/R03_R11_MCP_LEASH.txt) | Local official SDK adapter, mocked backend; no finance or inference proof |
| services/mcp-store: `.venv/Scripts/python.exe -m pytest -q` | [40 passed in 9.23s](test-evidence/R03_R11_MCP_STORE.txt) | Local SDK connector, mocked merchant; no owned freeze/charge proof |
| Root: `services/webhook/.venv/Scripts/python.exe -m unittest discover -s tests -p test_decision_cases.py -v` | [1 runner passed in 0.165s](test-evidence/R03_R11_DECISION.txt), all 16 YAML cases | Existing independent policy/handler fixtures; no full live chain |
| Root: `services/agents/.venv/Scripts/python.exe -m pytest tests/e2e -q` | [6 skipped in 0.11s](test-evidence/R03_R11_E2E.txt) | LEASH_E2E unset; no live model/Graph/purchase acceptance claimed |
| web: `pnpm lint`, `pnpm build` | [Lint exit 0](test-evidence/R03_R11_WEB_LINT.txt), [production build exit 0](test-evidence/R03_R11_WEB_BUILD.txt) | Existing web unchanged; compile/TypeScript/build do not establish browser/deployed acceptance |
| Root: `services/agents/.venv/Scripts/ruff.exe check api --select E9,F63,F7,F82` | [All checks passed](test-evidence/R03_R11_CORRECTNESS_LINT.txt) | Python correctness subset, not a whole-repository formatting claim |

The unchanged agents service was not rerun in this batch; its earlier
131-pass/2-live-skip evidence remains in [V2 results](V2_TEST_RESULTS.md).
No Compose file exists. LKE and live provider/model integrations were not exercised.

## Newly exercised foundation boundaries

The 22 added real SQL/HTTP methods in [test_r02_postgres.py](../api/tests/test_r02_postgres.py)
prove committed identity visible from a separate connection before GET; complete
immutable itemized evidence and blocked result; stable crash/retry references;
conflicting agent claims and merchant observations; one concurrent outcome;
different-checkout/run scope exclusion; commit/transaction failures; durable safe
merchant-error replay; Stop/replace/revoke/expiry races; unrelated prepared run
preservation; unknown-state barriers across versions and both controls; forged
SQL owner/scope rejection; reserved-ID nondisclosure; secret rejection; legacy
approved-grant reconciliation gate; and a blocked subscription followed by a new
blocked charger observation under unchanged authority.

The last scenario is a backend preflight fixture. It does not establish actual
Graph quarantine/recovery, a positive purchase or a live malicious-listing attack.
Unknown state is injected through a private backend function to verify denial;
there is no provider timeout detection/read-back worker. Prepared retries may
duplicate read-only GETs but cannot perform a financial write.

## Diagnostic history and coverage truth

The [initial 48-test SQL run](test-evidence/R03_R11_INITIAL_SQL_DIAGNOSTIC.txt)
found one existing regression: missing store configuration returned 503 ahead
of a committed account Stop's expected 409. Authority gates now run before
configuration checks; all final 149 tests pass. Later hardening added immutable
original-result guards and the legacy-grant compatibility regression, then the
full suite was rerun against the final migration.

The sandboxed store run stalled and was stopped; the final local TestClient run
with required process access passed. Redis temporary binaries had to be restored
after /tmp cleanup; no system package installation/shared service occurred.
Evidence line endings/terminal whitespace were normalized, with results preserved.

The byte-exact supplied 137-case matrix remains unchanged. Its current coverage
index has 19 updated foundation mappings and refreshed actual test locations;
full-case totals remain **35 scoped PASS / 46 NOT_RUN / 51 MISSING /
5 BLOCKED_EXTERNAL**. Related foundation successes do not pass unfinished live
financial, Graph, Kubernetes or demo cases. See
[coverage index](LEASH_SECURITY_COVERAGE.md) and [audit](LEASH_ALIGNMENT_AUDIT.md).
