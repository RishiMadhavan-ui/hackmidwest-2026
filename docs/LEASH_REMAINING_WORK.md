# What's left until Leash is done

Snapshot: main `713ddb1`, Graph branch `aditya/strands-graph` at `eea65d2`.
Submission target: Sunday, October 11, 7:30 AM Central.

"Done" means the signature demo runs for real, end to end, on the deployed
cluster: a human confirms the charger mandate and launches the agent from the
web app. The Strands Graph falls for the poisoned listing, gets blocked, and
recovers to the real charger, which is authorized on the local rail. The Kill
Switch then stops everything, and all of it shows up in the UI after a refresh.

Owners follow the `AGENTS.md` lanes: Rishi owns `api/`, `db/` and `web/`;
Cameron owns the store, rail and deployment; Aditya owns the agents and MCP
servers.

## 1. Merge the Graph branch into main (blocks everything else)

- [ ] **Resolve the six conflicting files.** `api/main.py`,
  `api/payment_routes.py`, `api/workflow_control.py`, `services/store/main.py`,
  `services/webhook/decide.py`, `services/webhook/store.py`.
  *Aditya, with Rishi (API) and Cameron (store, rail).*
- [ ] **Keep one charge path.** Main's #17 (`payment_service.request_payment`
  approves and binds) and the branch's `purchase_execution.py` both activate
  local-rail grants. Pick one and put the run-scope check in front of it.
  *Rishi + Cameron + Aditya.*
- [x] **Fix the migration number clash.** The branch's migration is now
  `0012_execution.sql`; it keeps all nine payment states and main's
  `prepared → authorized` transition.
- [ ] **Agree the run financial states.** The Graph client stops on anything
  other than `unspent`. Define how "keep shopping", "reconcile" and "already
  authorized" are reported. *Rishi + Aditya.*
- [ ] **Rerun every suite after the merge.** API with PostgreSQL, agents,
  `mcp-leash`, `mcp-store`, store, webhook with Redis, the decision-case runner,
  web lint and build, and the Attack Lab boundary test. *Whoever merges.*

## 2. Close the end-to-end loop

- [ ] **Dispatch a launch to the agents service.** `POST /agent-runs/launch`
  returns a run ID and launch ID, but nothing then calls the agents service's
  `POST /runs`. The API should make that call itself with the service token,
  since a browser can't hold it. *Rishi, with Aditya.*
- [ ] **Add a "Start purchase" button** on a confirmed mandate in the web app
  that calls the launch and opens the run's timeline. *Rishi (web).*
- [ ] **Give recovery a real compliant alternative.** The Graph's recovery tests
  supply fixture candidates; the store has no separate clean listing for the
  agent to find on its own. Add one, plus a way to discover it.
  *Cameron (store) + Aditya (Graph).*
- [ ] **Turn execution on in config.** `LEASH_EXECUTION_ENABLED=1`, the
  merchant's charge credential, rail tokens and the agents service token where
  each is needed, with Kubernetes Secret allowlists updated to match. *Cameron.*

## 3. Show the live path in the UI

- [ ] **Run timeline.** Render the Graph's `agent.step` events (node, edge,
  investigation, quarantine, recovery) in Activity and on the mandate page.
  *Rishi (web).*
- [ ] **Approved payments.** Show "grant issued" and "authorized on Local
  Payment Rail Simulator" from the real events, with decision source and
  latency. Keep "authorization isn't settlement" visible. *Rishi (web).*
- [ ] **Attack Lab.** Call `/attack-lab/status`. Let allowlisted operators see
  the poisoned preview, and start a scenario once that's enabled. Everyone else
  keeps the read-only view. *Rishi (web).*
- [ ] **Pick one Mission Control.** `/overview` and Cameron's `/mission-control`
  overlap. Keep one, or fold the useful panels in. *Team.*

## 4. Real evidence instead of fixtures

- [ ] **Live Akamai inference.** Run the two skipped live tests with real
  credentials and record one genuine Strands tool-calling round trip. *Aditya.*
- [ ] **Attack Lab scenarios.** Provision isolated demo fixtures and the
  operator allowlist so `POST /attack-lab/scenarios/{id}/start` stops returning
  503. Never re-enable the anonymous poisoned listing. *Cameron + Rishi.*
- [ ] **End-to-end tests.** Update `tests/e2e` (S1 charger, S2/S6 attack and
  recovery, S3–S5 negatives) for human launch and the Graph, add S7 Kill Switch,
  and run them against the deployed stack. *Aditya.*
- [ ] **Stop during a run.** Press Stop and the Kill Switch while the model and
  tools are mid-call, and confirm nothing else is spent. *Aditya + Cameron.*

## 5. Deploy

- [ ] **Roll out main to LKE** with `SKIP_DB=1 bash scripts/deploy_lke.sh`:
  new images, migrations, Secrets. This also closes the poisoned-listing
  exposure still live on the old deployment (`docs/ATTACK_LAB_SECURITY_AUDIT.md`).
  *Cameron.*
- [ ] **Verify on the cluster.** `/backend/readyz`, network policies, Valkey and
  trace-spool volumes, SSE through the NodeBalancer, and history surviving a
  page refresh. *Cameron.*

## 6. Finish

- [ ] **Update the docs.** The "Current implementation" paragraph in
  `AGENTS.md`, the build plan, and `graph-handoff.md` (MCP scope checks now
  exist) are out of date. *Everyone.*
- [ ] **Rehearse the 3-minute demo twice** on the deployed stack, resetting
  fixtures between runs. Keep a clearly labeled backup recording in case the
  model endpoint is down. *Team.*
- [ ] **Record the video.**

## Not required for the hackathon

- Live Lithic sandbox issuance and ASA correlation. The labeled Local Payment
  Rail Simulator is the agreed fallback.
- A provider reconciliation worker for Lithic outcomes.
- HTTPS on the public site, local Docker Compose.
