# Historical Attack Lab exposure and containment

This preserves the source/anonymous deployment checkpoint at its stated revision; current audit is [ATTACK_LAB_SECURITY_AUDIT.md](ATTACK_LAB_SECURITY_AUDIT.md). Do not treat the old operator-missing status as current source.

# Attack Lab access-control audit and containment

Inspected October 11, 2026, on main at `3097c6725647eef7709dc3d35b080f61fd421cb8`.
Worktree was clean; fetching origin found no newer main. A separate Cameron
Mission Control branch was not merged or changed. No database, provider,
scenario execution, fixture reset, or deployed configuration was mutated.

During final integration, origin/main advanced to `e52bbde` (Cameron's Mission
Control PR #15). Main was fast-forwarded without stash/reset or conflicts; his
purchase UI and human draft endpoint were preserved. The newly merged
`web/src/components/mission-control/attack-lab.tsx` linked any signed-in user to
`?evil=1`, while `mission-control/page.tsx` uses client-side sign-in gating only.
The card now displays a disabled placeholder and no attack execution link;
the independent server denial remains the security boundary. This is not an
implemented protected operator UI. Rebuilt/retested after this integration.

## Confirmed live exposure

Unauthenticated, read-only HTTP probes of the known demo deployment
`http://173.255.199.245` observed:

| Request | Observed result | Evidence / interpretation |
|---|---|---|
| `/attack-lab` and `/lab` | 404 | Dedicated Lab UI absent at these paths; this does not protect related APIs |
| `/store/products/chg-65w` | 200, clean listing | 12260 bytes; SHA-256 `4de20f1a5c54da772adc2fd56ff53ae97ebf80d6b45c5230be389a95a137eba1` |
| `/store/products/chg-65w?evil=1` | **200, poisoned listing without authentication** | 12775 bytes; visible Evil listing label, VoltCare/JSON-LD injection markers; SHA-256 `85086a11b44703493438ece7dc614922cf1da5c03b2961b4ed71e795361e876f` |
| `/backend/health` | 200 | Confirms API reachable; not authorization evidence |
| `/backend/openapi.json` | 200 | No dedicated Lab routes; older route set lacks current run Stop routes. Actual deployed SHA unknown |

This is a **P0 public attack-content selection exposure**. It selects poison for
that response, not a proven global persistent fixture mutation. It does not prove
unauthenticated payment execution, successful model injection, or real charges.
No financial POST or adversarial run was invoked during inspection.

`kubectl config current-context` returned `current-context is not set`. Actual
image revisions, Secrets, NetworkPolicies, cluster-internal access and a rollout
were not verified. Treat the deployment as exposed until Cameron rolls out the
patched web/store images and repeats negative requests. Source protection alone
cannot change already-running pods. If rollout cannot happen promptly, Cameron
should temporarily deny public `/store/products/*` at the deployed ingress/proxy;
setting the old `STORE_EVIL_MODE=0` alone cannot stop the query override.

## Source paths and narrow fix

| Boundary | Finding / current source behavior | Owner / remaining work |
|---|---|---|
| `web/src/app/store/products/[productId]/route.ts:GET` | Previously forwarded arbitrary anonymous `evil` selectors. Now 403 for all attack/unknown selectors, including duplicates; all clean requests explicitly forward `evil=0` | Rishi; tested handler boundary, rollout Cameron |
| `services/store/main.py:product_page` | Previously enabled poison through query or `STORE_EVIL_MODE`. Now denies attack selectors even with the store service token; renders only clean HTML regardless of environment flags | Cameron lane; urgent user-authorized containment only, not a store redesign |
| `services/store/pages.py:render_product_page` | Offline `evil=True` fixture rendering retained; no runtime HTTP selection | Cameron fixtures; Aditya scenario consumption after isolation exists |
| `services/store/main.py:reset_checkouts` | Process-wide Python test helper, no HTTP reset route; unsuitable for scoped Lab cleanup | Cameron: implement scoped demo namespace cleanup, never expose this helper |
| Store create/read/bind/complete | Service bearer enforced on `/api/checkouts*`; storefront start remains public and creates open process-memory checkouts only. Completion remains 403/503 with no charge | Existing C02 durable ownership/freeze/protected bind work remains; these are not operator APIs |
| `services/webhook/main.py:simulate_lithic_auth` | Internal service authentication, then 503 because durable simulation operation missing. Service auth is not demo/admin authorization | Cameron: only scoped sandbox/local scenario commands from an authorized control plane |
| `web/next.config.ts` and `/backend/internal/[[...path]]/route.ts` | Public rail adapter only signed ASA; internal API routes denied. MCP proxy opt-in, default off | Existing source boundaries preserved; deployed settings unknown |
| Mission Control Lab card/operator API | New ordinary-user attack link contained with disabled placeholder; no verified human demo/admin policy or authorized scenario workflow exists | Rishi: reuse existing backend session/stable identity; no competing auth system |

Runtime attack execution is deliberately **disabled for everyone** until an
authorized scenario path is implemented. `ATTACK_LAB_ENABLED` is a future contract,
not an implemented switch; setting it currently does not enable anything.
The legacy `STORE_EVIL_MODE` variable may remain in manifests but is ignored by
the patched listing path. Only clean-selector values `0`, `false`, `off`, `no`
(case-insensitive) are accepted; all duplicate values are checked.

## Verification actually executed

- Store: from `services/store`, `.venv/Scripts/python.exe -m pytest -q`:
  **22 passed, 12 subtests passed**. HTTP TestClient uses genuinely unauthenticated
  visitors for new negative cases; service-token denial, duplicate selectors,
  environment override resistance, clean browsing and offline poison retained.
  Starlette/httpx deprecation warning remains. No provider/model calls.
- Web: from `web`, `node --experimental-strip-types --test tests/attack-lab-boundary.test.mjs`:
  **2 passed**. Invokes the actual exported server handler and uses real HTTP
  fetch to an isolated legacy merchant double; poison denied and clean forwarding
  forced. Fake credentials test denial only, not real session/role validation.
  Node reported existing unspecified module-type warning.
- Production HTTP smoke: from repo root,
  `services/store/.venv/Scripts/python.exe web/tests/attack_lab_http.py`:
  **1 test passed** using the actual built Next standalone server and real local
  store process, with `STORE_EVIL_MODE=1`. Anonymous clean browsing was 200;
  poison and duplicate-selector requests were 403 at both HTTP boundaries.
  Both owned child processes were stopped; no shared database or rail was used.
- Store MCP: from `services/mcp-store`, `.venv/Scripts/python.exe -m pytest -q`:
  **40 passed**; existing SDK/mock-store adapter tests, not live inference.
- Preserved merge's API auth/signature suite: from `api`,
  `.venv/Scripts/python.exe -m unittest discover -s tests -p test_r02_authority.py -v`:
  **11 passed**. Unit/mocked route tests only; no database provisioning test of
  the new auto-binding path and no full API/PostgreSQL rerun claimed here.
- Web `pnpm build`: **passed before and after `e52bbde`**, including TypeScript
  and production routes. `pnpm lint` passed before the merge but **fails after
  the merge** at `web/src/components/activity-feed.tsx:144`:
  `eventsRef.current = events` mutates a ref during render (`react-hooks/refs`).
  This unrelated merged activity-feed issue is flagged for Rishi/Cameron, not
  rewritten in the security patch. Python correctness lint on changed Python files:
  **passed**. Documentation checks: all local links valid; exactly 147 unique
  case IDs match coverage, original 137-case source prefix SHA-256 unchanged,
  frozen contracts/historical migrations unchanged, 20 Kubernetes YAML documents
  parse. Diff/whitespace checks pass for changes; original matrix whitespace is
  intentionally preserved.
- No live Lithic/Strands/Graph or deployed role checks were performed.

These prove disabled-path containment locally. They do not pass the full
LAB-001–010 acceptance set, which also requires positive authorized execution,
real roles, scoped isolation, rate limiting and session protection.

## Remaining acceptance and safe handoff

Follow [spec section 29](LEASH_SPEC.md#29-attack-lab-access-control-p0) and the
[LAB mapping](LEASH_SECURITY_COVERAGE.md#attack-lab-addendum-lab-001010).
Rishi implements operator authentication/authorization and API/UI; Cameron
implements isolated fixtures/rails, limits at service boundaries and rollout;
Aditya implements genuine bounded Graph/MCP execution and cancellation cleanup.
No owner is reassigned. Existing financial blocks remain until their original
merchant/payment/stop gates also pass. An operator role never approves spending.

Separate newly observed identity issue, outside this Lab patch:
`api/mandate_service.py:draft_agent_for_user` in `e52bbde` can bind an unclaimed
configured shared `AGENT_TOKEN_SHOPPER` to the first human who drafts. This changes
the earlier operator-provisioned identity rule and needs Rishi/Cameron review
before enabling agent/payment execution: ordinary drafting must not claim a
deployment service credential. Existing spending blocks are retained. This path
was flagged, not rewritten or treated as verified provisioning.

Deployment acceptance must prove anonymous and ordinary-user direct requests
cannot select attacks, including internal service bypass and duplicate selectors;
clean storefront access must still succeed. Record actual image SHA and HTTP
results. Full Lab enablement additionally needs authenticated allowed operators,
disabled flag denial, namespace isolation, no real-money rail, reset scope,
rate/concurrency limits, CSRF/session checks and genuine labeled execution.
