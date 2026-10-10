# Leash build plan

Oct 10, 2026 · @Aditya Pall

## Who owns what

Three lanes, and each one ends at a contract (a REST route, a Valkey key, or an event), so nobody needs to edit anyone else's files.

| Person | Lane | Owns |
| --- | --- | --- |
| Cameron | Infra and the payment rail | `infra/`, `docker-compose.yml`, `.env.example`, `.github/`, `services/webhook/`, `services/store/`, `shared/leash_shared/lithic.py` |
| Rishi | Product backend and frontend | `services/api/`, `db/`, `web/`, `shared/leash_shared/models.py`, `shared/leash_shared/events.py` |
| Aditya | Agents and MCP | `services/agents/`, `services/mcp/`, `shared/leash_shared/llm.py`, `tests/decision_cases.yaml`, `tests/e2e/`, `docs/demo-script.md` |

Cameron gets the Lithic code on both ends, the store that triggers charges and the webhook that answers them, because it's one rail. Rishi is the only one who writes to Postgres, so there's one schema and one writer. Aditya owns everything that runs a model, plus the MCP door that outside agents use. AGENTS.md has the same table, so each person's coding agent stays in its lane too.

## First 45 minutes, together (done by 2:30 PM)

Before anyone branches, we lock the contracts so every lane can build against stubs instead of waiting on each other.

1. Aditya creates the repo, commits AGENTS.md, and adds Cameron and Rishi.
2. Rishi writes `models.py` and `events.py` from the contracts in AGENTS.md while the other two review on screen. After that, they're frozen.
3. Cameron commits `.env.example` and a `docker-compose.yml` where every service is a stub that answers `/healthz`.
4. Everyone creates their branch and stubs the routes they own, returning fake data that matches the models.
5. In parallel: Cameron signs up for the Lithic sandbox and starts the LKE cluster, Aditya reruns the Strands smoke test, and Rishi sets up Next.js and the migration tool.

## Timeline (Central time)

Happy path by 7:00 PM, the full demo working by 1:00 AM, feature freeze at 5:00 AM, and submission at 7:30 AM Sunday, 30 minutes ahead of the 8:00 AM deadline.

| By | Cameron | Rishi | Aditya | Checkpoint |
| --- | --- | --- | --- | --- |
| 2:30 PM | `.env.example` and compose stubs | `models.py` and `events.py` | Repo and AGENTS.md | Contracts frozen, everyone branched |
| 4:30 PM | LKE up, ingress with TLS, webhook live at a public URL, Lithic ASA enrolled | Schema and migrations, mandate routes, `POST /payments` stub returning a fake card, SSE stream | `llm.py`, guardian v1, MCP server with all four tools against api stubs, decision cases written | Each lane runs on its own against stubs |
| 7:00 PM | Store listings and a checkout that calls simulate authorization, card creation in `lithic.py`, `decide()` passing every decision case | Real `POST /payments` flow, phone approval screen, event consumer | Shopper agent working through MCP, provenance plugin | Happy path end to end locally: propose, approve, shop, pay, approved |
| 10:00 PM | Evil mode and the gift card merchant, every service running on LKE | Dashboard with agent trace, pages read, and the authorization feed with latency, plus the blocked alert | Guardian catches the injection from provenance, reused-card scenario, e2e script | Evil mode blocked twice, on the cluster |
| 1:00 AM | Kill switch pauses cards in Lithic, duplicate-request handling, 2 webhook replicas with readiness probes | Kill switch, `PATCH` mandate for the live rule change, receipts export, notifications | Demo script v1, Claude Desktop connected over MCP, full e2e run on the cluster | Everything in the demo works |
| 4:00 AM | Webhook load test with p95 latency, backup recording setup | UI polish, sandbox and simulated labels, empty and error states | Stretch: attacker swarm with a block-rate counter, guardian prompt tuning | Stretch done or dropped |
| 5:00 AM | Record the backup video | Bug fixes only | Run rehearsals | Feature freeze |
| 7:30 AM |  |  | Submit | Submitted |

## Handoffs between lanes

Everyone builds against stubs first, so a late handoff slows integration but never blocks anyone's own lane.

| What | From | To | Needed by |
| --- | --- | --- | --- |
| `models.py` and `events.py` | Rishi | Everyone | 2:30 PM |
| `.env.example` and compose stubs | Cameron | Everyone | 2:30 PM |
| api stub routes matching the models | Rishi | Aditya (MCP server) | 3:30 PM |
| `tests/decision_cases.yaml` | Aditya | Cameron | 4:00 PM |
| Public webhook URL enrolled with Lithic | Cameron | Everyone | 4:30 PM |
| `POST /guardian/evaluate` (a stub that approves until then) | Aditya | Rishi | 5:00 PM |
| `create_single_use_card()` and `pause_card()` in `lithic.py` | Cameron | Rishi | 5:00 PM |
| Object Storage bucket and keys | Cameron | Aditya | 5:00 PM |
| Store URLs for listings and checkout | Cameron | Aditya | 6:00 PM |
| Evil mode toggle and the gift card merchant | Cameron | Aditya | 9:00 PM |

## Cameron: infra and the payment rail

The infra work is front-loaded, so the public webhook URL and Lithic enrollment come first. Everything else on the rail depends on them.

- [ ] Lithic sandbox account, API key, and ASA enrollment pointing at the deployed webhook URL
- [ ] LKE cluster on the standard tier: 3 Shared CPU 4 GB nodes, autoscaling off so node IPs stay fixed
- [ ] ingress-nginx, cert-manager with Let's Encrypt, and DNS for the Leash subdomain
- [ ] Akamai Managed Postgres with the node IPs on its allow list
- [ ] Object Storage bucket and a Valkey deployment in the cluster
- [ ] GitHub Actions building each service's image to GHCR, one manifest folder per service, Kubernetes Secrets
- [ ] `lithic.py`: `create_single_use_card`, `pause_card`, `simulate_authorization`, `verify_asa_hmac`
- [ ] `services/webhook`: the handler plus the pure `decide()` function, every decision case passing, 2 replicas with readiness probes, latency logged on every decision
- [ ] `services/store`: hotel listings and a checkout that calls simulate authorization with the hotel descriptor and MCC 7011
- [ ] A gift card merchant with its own descriptor and MCC, plus the evil mode toggle that plants hidden text in one listing
- [ ] Kill switch support: pause every one of the user's cards in Lithic
- [ ] Backup demo recording at the 5:00 AM freeze

## Rishi: api, database, and web app

The payment flow in `POST /payments` is the heart of the product, so it gets built right after the contracts. The screens come next.

- [ ] `models.py` and `events.py`, including `canonical_json()` and `cart_hash()`
- [ ] Schema and migrations: users, agents, mandates (with version and signature), carts, payments, authorizations, provenance, events
- [ ] Mandate routes: propose, approve with Ed25519 signing, a `PATCH` that bumps the version and voids unused approvals, revoke
- [ ] `POST /payments`: hard checks, the guardian call, the Lithic card, the pre-approval written to Valkey, card details returned once
- [ ] Payment approve and deny routes, the kill switch route, provenance intake
- [ ] Event consumer: read `leash:events`, save to Postgres, fan out over SSE
- [ ] Receipts: the signed chain as JSON plus a printable page
- [ ] Phone view: pending mandate approvals, pending payment approvals, blocked alerts with the evidence, active mandates, kill switch
- [ ] Dashboard: agent trace, pages read with hidden text highlighted, authorization feed with latency, a mandate and budget header
- [ ] Notifications through web push, with ntfy.sh as the fallback
- [ ] Sandbox and simulated labels everywhere they apply
- [ ] Generate `web/src/lib/api-types.ts` from the api's OpenAPI schema

## Aditya: MCP, agents, tests, and demo

The decision cases go to Cameron early, because the webhook can't be finished without them. The guardian stub goes to Rishi next.

- [ ] Repo and AGENTS.md
- [ ] Strands smoke test passing on `hackathon-chat` (tool call and structured output)
- [ ] `llm.py` model factory with `max_tokens` always set
- [ ] `tests/decision_cases.yaml`, covering the cases in the next section
- [ ] Guardian at `POST /guardian/evaluate`: deterministic checks first, then a structured Verdict with injection signals from provenance
- [ ] MCP server: `propose_mandate`, `list_mandates`, `request_payment`, `check_status`, bearer auth, stateless
- [ ] Shopper: browse and checkout tools plus the Leash tools through Strands' MCP client. Runs from the CLI and `POST /runs`, publishes `agent.step` events
- [ ] Provenance plugin: hash each page, flag hidden text, upload a snapshot to Object Storage, call `POST /provenance`
- [ ] `tests/e2e`: one script that runs the whole demo flow without a browser
- [ ] `docs/demo-script.md` with timings
- [ ] Claude Desktop connected over MCP for the "any agent can plug in" moment
- [ ] Stretch: an attacker agent swarm that generates injection variants, plus a block-rate counter
- [ ] Submit at 7:30 AM

## Webhook decision cases

Every row has to pass before any merge to main. Aditya writes the cases and Cameron makes them pass, so the code isn't grading itself.

| # | Situation | Expected |
| --- | --- | --- |
| 1 | Card, descriptor, and MCC match, amount under the limit | Approve |
| 2 | Amount exactly at the limit | Approve |
| 3 | Amount one cent over the limit | Decline |
| 4 | No pre-approval exists for the card | Decline |
| 5 | Descriptor is the gift card store | Decline |
| 6 | MCC doesn't match | Decline |
| 7 | Pre-approval has expired | Decline |
| 8 | Card was already used once | Decline |
| 9 | Kill switch is on | Decline |
| 10 | Mandate was edited after approval, so its pre-approval was deleted | Decline |
| 11 | Lithic sends the same request twice | Same answer both times |

Case 11 is tested on the request handler, since `decide()` itself has no memory.

## Branch and merge rules

Conflicts mostly come from two people touching the same file, so the rules are about who touches what.

- Branches are named `cameron/*`, `rishi/*`, and `aditya/*`.
- Only edit paths you own. If you need something in another lane, ask in the group chat and let the owner do it.
- Contract changes to `models.py` or `events.py` go in their own tiny PR, and all three of you agree first.
- Merge to main at least every two hours, and pull main before starting each task.
- main always boots with `docker compose up`. If you break it, fixing it is your next task.
- Only Cameron edits `docker-compose.yml` and `.env.example`. Everyone else asks for additions.
- Don't run a formatter over files you don't own.

## Three-minute demo

Three screens: the agent's terminal, the dashboard on the big screen, and a phone. No slides. Aditya owns the final script in `docs/demo-script.md`.

| Time | What judges see |
| --- | --- |
| 0:00 | The hook: "This AI was asked to book a $165 hotel. A website just told it to buy a $400 gift card. Watch the money." |
| 0:15 | The agent proposes a mandate in its terminal, the phone buzzes, and we approve it |
| 0:35 | The shopper books the $165 room, and the dashboard shows the charge approved in milliseconds |
| 1:00 | Evil mode goes on. The shopper reads the poisoned listing and asks for a $400 gift card. The guardian refuses, and the dashboard highlights the hidden text |
| 1:30 | The shopper tries the hotel card at the gift card store, and the webhook declines it at the card |
| 1:50 | We lower the max to $150 on the phone and rerun the same cart. Now it waits for approval |
| 2:15 | Kill switch: every card freezes. Download the receipt |
| 2:40 | Close on Strands agents and hooks, with everything running on Akamai |

## Risks and fallbacks

Each risk has a cutoff time. If it isn't solved by then, we switch to the fallback and move on.

| Risk | Fallback | Decide by |
| --- | --- | --- |
| Structured output from `hackathon-chat` is unreliable | The guardian returns JSON as plain text, validated with the same Pydantic model | 4:30 PM |
| Lithic ASA enrollment fails | Stripe Issuing test mode with the same `decide()`. Last resort: send Lithic-shaped requests to the webhook directly and label it simulated | 5:00 PM |
| The shopper won't reliably fall for the injection | Make the hidden instruction blunter and rehearse until it works every time. Never fake it with a scripted reply | 10:00 PM |
| Kubernetes trouble late at night | Run docker compose on a single Linode | 1:00 AM |
| Running behind | Cut the stretch goals first, then Claude Desktop, then notifications. Never cut either of the two blocks | 1:00 AM |
| Akamai inference slow or down | Bring your own inference: vLLM on a Linode GPU, or another provider for the agents, with the app still on LKE | Whenever it happens |
