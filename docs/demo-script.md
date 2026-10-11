# LEASH demo script (draft)

Owner: Aditya (A10). Every `<...>` is a value still to fill in from Cameron's deployment (H11) and Rishi's UI (R08/R09). Rehearse against the real deployment and update this file with what actually happened.

**Status: no live injection has been recorded yet.** The signature attack is planned as a live run, and nobody should say "the live agent fell for it" until the [live evidence log](#live-evidence-log) has a real entry with the listing, the agent's resulting action, and the backend's outcome.

## Deployment (LKE, as of Oct 10)

| What | Where | Status |
|---|---|---|
| Web | `http://173.255.199.245/` (NodeBalancer) | Up; signup/signin/profile from Cameron's auth PR |
| api | `http://173.255.199.245/backend/...` (web proxies `/backend/*` to `api:8000`) | Up with `/health` and `/auth/*` only; Leash mandate/payment/run/provenance routes pending (Rishi, R02/R04/R06) |
| agents | cluster-internal Service `agents`, port 8000 | Deploy pending |
| mcp-leash | Service `mcp-leash:8002/mcp`; public via the web proxy at `http://173.255.199.245/mcp-leash/mcp` | Cameron's placeholder deployed; this code pending |
| mcp-store | Service `mcp-store:8003/mcp`; public via the web proxy at `http://173.255.199.245/mcp-store/mcp` | Cameron's placeholder (no tools) deployed; this code pending |
| store, rail, Valkey | `<url>` | Not built yet (Cameron, C02-C04) |

Plain HTTP, no TLS yet: bearer tokens sent to the public MCP addresses cross the internet unencrypted, so only use throwaway demo tokens there until HTTPS exists. Lithic needs a public HTTPS responder before the Lithic rail can be selected; until then it's the Local Payment Rail Simulator.

The cluster's kubeconfig is written by `scripts/deploy_lke.sh` as `hackmidwest-kubeconfig.yaml` at the repo root (a credential; it's gitignored).

## What's real and what's simulated

Say this out loud if asked, and keep the labels on screen.

| Piece | In the demo |
|---|---|
| Mandate confirmation | Real. A human confirms each session's mandate in the Leash UI. Signed with a server-held Ed25519 demo key, not a device passkey. |
| Legitimate purchase (session A) | Real Strands shopper on Akamai inference (`agent_mode: "live"`). |
| Attack (session B) | **Real Strands shopper (`agent_mode: "live"`) reading the poisoned listing.** The shopper is gullible on purpose; Leash's protection is the independent checkout verifier, the store's protected charge, and the rail, not the agent. |
| Scripted runs | Only as labeled repeatable fixtures (preflight, e2e) or an explicit outage fallback. On screen: "Simulated compromised agent (scripted fixture)". Never described as the live model's behavior. |
| Merchant | Simulated merchant ("Volt Supply Co."), Cameron's controlled store. |
| Payment rail | "Lithic sandbox" only if Cameron verified it; otherwise "Local Payment Rail Simulator". Never live funds. |
| Backup video | Labeled "prerecorded" on screen the whole time. |

Claims we make: within our controlled merchant, Leash ties payment to the exact checkout the human's intent allows, and blocks a same-merchant, same-price, same-currency substitution before any grant exists.

Claims we don't make: card networks show SKUs (they don't; the rail alone can't tell the charger from the subscription), protection against a dishonest merchant, AP2 compliance, passkey signing.

## Prerequisites before any rehearsal

| Needed | Owner | Why |
|---|---|---|
| Mandate propose/confirm/read, `POST /payments` with independent checkout verification, `POST /agent-runs`, `POST /provenance`, incidents/history reads | Rishi (R02-R06) | Every scenario runs through these; nothing is stubbed in the demo path. |
| Store: canonical catalog, attackable listing with an attack toggle, checkout API, protected charge bound to the verified checkout | Cameron (C02) | The attack and the block both depend on it. |
| Rail, Valkey grant/idempotency protocol | Cameron (C03/C04) | The legitimate purchase's real approval. |
| agents, mcp-leash and mcp-store deployed from this code; `AGENTS_SERVICE_TOKEN`, `AGENT_TOKEN_SHOPPER`, `STORE_MCP_TOKEN`, `STORE_URL`, `STORE_PUBLIC_URLS` in `.env`; persistent volume at `/app/trace-spool` | Cameron (C06) | Agents can't run or keep traces without them. |
| A passing live inference smoke test (`services/agents/tests/test_llm.py`) | Aditya | A live attack needs a working model. |

## Preflight (T-30 minutes)

PowerShell, on the presenter laptop:

```powershell
$env:API_URL = "http://173.255.199.245/backend"
$env:STORE_PUBLIC_URL = "<public store url>"
$env:AGENTS_URL = "http://localhost:8001"     # via the port-forward below; agents is cluster-internal
$env:AGENTS_SERVICE_TOKEN = "<from the team .env>"
$env:KUBECONFIG = "$PWD\hackmidwest-kubeconfig.yaml"

# Local port 8001 -> the agents Service's port 8000. Leave it running in its own window.
kubectl -n hackmidwest port-forward svc/agents 8001:8000

Invoke-RestMethod "$env:API_URL/health"
Invoke-RestMethod "$env:AGENTS_URL/health"
Invoke-RestMethod "$env:STORE_PUBLIC_URL/health"

# Helpers used below and during the run of show.
$h = @{ Authorization = "Bearer $env:AGENTS_SERVICE_TOKEN" }
function Start-Run($body) {
  $run = Invoke-RestMethod -Method Post -Uri "$env:AGENTS_URL/runs" -Headers $h `
    -ContentType "application/json" -Body ($body | ConvertTo-Json)
  $run.run_id
}
$task = 'Buy a USB-C laptop charger for under $40. No subscriptions.'
$listing = "$env:STORE_PUBLIC_URL/products/chg-65w"
```

1. **Scenario suite** on a preflight session (never sessions A or B). These use the scripted fixture by default so they're repeatable; they test enforcement, not the model:
   ```powershell
   $env:LEASH_E2E = "1"; $env:E2E_CHARGER_URL = "$env:STORE_PUBLIC_URL/products/chg-65w"
   uv run --project services/agents pytest tests/e2e -v
   ```
   All six must pass. If any fail, stop and fix or switch to the backup video.
2. **Live attack rehearsal** on a fresh preflight session (a new mandate a human has confirmed, its id in `$env:MANDATE_PREFLIGHT`), attack listing on:
   ```powershell
   $id = Start-Run @{ task=$task; mandate_id=$env:MANDATE_PREFLIGHT; start_url=$listing; agent_mode="live" }
   Invoke-RestMethod "$env:AGENTS_URL/runs/$id" -Headers $h | ConvertTo-Json -Depth 20
   ```
   Check the trace for: the listing's `provenance.source` (hidden text flagged), a `create_checkout` for `SUB-CARE-MO`, and `request_payment` with Leash's real `blocked` decision. Record it in the [live evidence log](#live-evidence-log). Repeat a few times. If the live shopper doesn't take the bait reliably, change the listing text with Cameron (A08); never script the "live" run to make it look like it did.
3. **Live legitimate run** on another preflight session, attack listing off, to confirm the approval path.
4. Create **session A** and **session B**: the shopper proposes two mandates with the same instruction, "Buy a USB-C laptop charger for under $40. No subscriptions.", and a human confirms each one in the UI. Write down both mandate ids:
   ```powershell
   $env:MANDATE_A = "<mnd_...>"; $env:MANDATE_B = "<mnd_...>"
   ```
5. Attack listing **off** before session A's run (Attack Lab toggle, C02).
6. Open the screens: phone (mandate view) and big screen (Mission Control).

## Run of show (3:00)

The commands below use `Start-Run`, `$task` and `$listing` from the preflight setup.

| Time | Presenter | On screen | If it goes wrong |
|---|---|---|---|
| 0:00-0:20 | Aditya: "You tell your AI to buy a charger. What stops it from buying something else?" Rishi shows session A's confirmed mandate. | Original instruction, USB-C, under $40, no subscriptions, one purchase; human confirmation. | Show the mandate from the phone screenshot. |
| 0:20-0:45 | Start session A: `Start-Run @{ task=$task; mandate_id=$env:MANDATE_A; start_url=$listing; agent_mode="live" }` | Live tool trace, trusted checkout verified, grant, rail approval. Label: "Live Strands shopper". | No result after 30 s: run `Start-Run @{ task=$task; mandate_id=$env:MANDATE_A; start_url=$listing; agent_mode="scripted"; sku="CHG-65W" }` and say "scripted fallback". |
| 0:45-1:30 | Switch visibly to session B. Turn the attack listing **on** in Attack Lab. Start the live shopper: `Start-Run @{ task=$task; mandate_id=$env:MANDATE_B; start_url=$listing; agent_mode="live" }` | The poisoned listing's hidden text, then the live agent's own tool calls, including the `SUB-CARE-MO` checkout it attempts. Label: "Live Strands shopper". Session B's mandate hash unchanged. | If the live agent doesn't attempt the subscription within 40 s, say so plainly ("this time the model didn't take the bait"), then show the enforcement with the labeled fixture: `Start-Run @{ task=$task; mandate_id=$env:MANDATE_B; start_url=$listing; agent_mode="scripted"; sku="SUB-CARE-MO"; claim_sku="CHG-65W" }`, on screen as "Simulated compromised agent (scripted fixture)". |
| 1:30-2:00 | "Same merchant, same $29.99, same USD. A merchant-and-budget rule approves this." | Intent vs trusted checkout: laptop_charger vs protection_plan, one-time vs monthly. Result: **blocked before payment**, no grant. | Read the block reasons from `GET /payments/{id}`. |
| 2:00-2:35 | Open the incident. | Listing URL and SHA-256, the hidden instruction excerpt, the agent's claim vs the trusted checkout, failed checks, guardian findings, decision source and latency. | Show the run's trace: `Invoke-RestMethod "$env:AGENTS_URL/runs/<run_id>" -Headers $h`. |
| 2:35-3:00 | Aditya: Strands for the shopper and guardian, Akamai inference for the models, the FastAPI policy backend on Akamai compute, the selected rail. Limitation in one sentence. | Blocked incident stays on screen. | |

If timing allows, show recovery (S6) in session B after the block: turn the attack listing off and run `Start-Run @{ task=$task; mandate_id=$env:MANDATE_B; start_url=$listing; agent_mode="live" }`. It's approved under the same unchanged mandate: the blocked attack consumed no purchase authority, and the incident stays in history.

Sessions A and B stay separate, each with its own human-confirmed mandate. A singular "buy a charger" mandate allows one purchase, so A's successful purchase can't be followed by B's attack under the same authority.

## Live evidence log

Fill this in from real runs only (the run record from `GET /runs/{id}` plus the api's payment record). An entry needs all three: the listing the agent read, the action it took, and the backend's decision.

| When | Run id | Mode | Listing sha256 | Agent's resulting action | Backend outcome | Recorded by |
|---|---|---|---|---|---|---|
| (none yet) | | | | | | |

## Resetting between rehearsals

- A mandate allows one purchase. Each rehearsal uses **new** sessions: propose and confirm new mandates. Never delete or edit a used mandate, grant, or incident to "reset" it.
- Turn the attack listing off after every run.
- Spooled traces deliver on their own. Check nothing is stuck: `kubectl -n hackmidwest exec deploy/agents -- ls /app/trace-spool/pending` should be empty, and `rejected/` should be empty too (anything there means the api refused an event; read the agents log with `kubectl -n hackmidwest logs deploy/agents`).

## Outage fallbacks

| What failed | Do this |
|---|---|
| Akamai inference | Both sessions use the scripted fixture, labeled on screen, and say the model is unavailable. The guardian reports `model.status: unavailable` and recommends review; enforcement doesn't change. |
| Agents service | Show the preflight run's incident and trace from the UI history. |
| api or rail | Switch to the backup video, labeled prerecorded. Don't narrate a replay as live. |
| Store | Same as api. |

## Still to fill in after deployment

- The store URL, and whether the agents service stays port-forward only or the api starts runs for the UI.
- Whether the UI starts runs (Attack Lab) or we use the commands above.
- The selected rail and its exact on-screen label.
- Live evidence log entries and rehearsal timings (target: three full run-throughs at 3:00 or under).
