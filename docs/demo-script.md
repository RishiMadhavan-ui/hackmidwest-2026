# LEASH demo script (draft)

Owner: Aditya (A10). Every `<...>` is a value still to fill in from Cameron's deployment (H11) and Rishi's UI (R08/R09). Rehearse against the real deployment and update this file with what actually happened.

## Deployment (LKE, as of Oct 10)

| What | Where | Status |
|---|---|---|
| Web | `http://173.255.199.245/` (NodeBalancer) | Up |
| api | `http://173.255.199.245/backend/...` (web proxies `/backend/*` to `api:8000`) | Up, starter only: `/backend/health` works, no Leash routes yet |
| agents | cluster-internal `agents:8000` | Manifests exist; confirm Ready pods after deploy |
| mcp-leash, mcp-store | public via web: `http://<NB>/mcp-leash/mcp`, `http://<NB>/mcp-store/mcp` (ClusterIP behind Next rewrites) | Need web image with rewrites + mcp pods Ready |
| store | `<url>` | Not deployed yet |

Plain HTTP, no TLS yet. Lithic needs a public HTTPS responder before the Lithic rail can be selected; until then it's the Local Payment Rail Simulator.

The cluster's kubeconfig is written by `scripts/deploy_lke.sh` as `hackmidwest-kubeconfig.yaml` at the repo root (a credential; it's gitignored).

## What's real and what's simulated

Say this out loud if asked, and keep the labels on screen.

| Piece | In the demo |
|---|---|
| Mandate confirmation | Real. A human confirms it in the Leash UI. Signed with a server-held Ed25519 demo key, not a device passkey. |
| Legitimate purchase (session A) | Real Strands shopper on Akamai inference (`agent_mode: live`). Fallback: scripted run, labeled. |
| Attack (session B) | **Simulated compromised agent (scripted fixture).** The agent's choices are scripted: it checks out the subscription and claims it's the charger. Every action is real: the poisoned listing, the store's checkout, MCP, the api's verification, and the rail. |
| Merchant | Simulated merchant ("Volt Supply Co."), Cameron's controlled store. |
| Payment rail | "Lithic sandbox" only if Cameron verified it; otherwise "Local Payment Rail Simulator". Never live funds. |
| Backup video | Labeled "prerecorded" on screen the whole time. |

Claims we make: within our controlled merchant, Leash ties payment to the exact checkout the human's intent allows, and blocks a same-merchant, same-price, same-currency substitution before any grant exists.

Claims we don't make: card networks show SKUs (they don't; the rail alone can't tell the charger from the subscription), protection against a dishonest merchant, AP2 compliance, passkey signing.

## Preflight (T-30 minutes)

PowerShell, on the presenter laptop:

```powershell
$env:API_URL = "http://173.255.199.245/backend"
$env:STORE_PUBLIC_URL = "<public store url>"
$env:AGENTS_URL = "http://localhost:8001"     # via port-forward below; agents is cluster-internal
$env:AGENTS_SERVICE_TOKEN = "<from the team .env>"
$env:KUBECONFIG = "$PWD\hackmidwest-kubeconfig.yaml"

kubectl -n hackmidwest port-forward svc/agents 8001:8001     # leave running in its own window

Invoke-RestMethod "$env:API_URL/health"
Invoke-RestMethod "$env:AGENTS_URL/healthz"
Invoke-RestMethod "$env:STORE_PUBLIC_URL/healthz"
```

1. Run the full scenario suite against the deployment, on a preflight session (never sessions A or B):
   ```powershell
   $env:LEASH_E2E = "1"; $env:E2E_CHARGER_URL = "$env:STORE_PUBLIC_URL/products/chg-65w"
   uv run --project services/agents pytest tests/e2e -v
   ```
   All six must pass. If any fail, stop and fix or switch to the backup video.
2. Run one live shopper against the clean listing (preflight session) to confirm Akamai inference is up. If it fails, session A uses the scripted fallback below, labeled.
3. Create **session A** and **session B**: the shopper proposes two mandates with the same instruction, "Buy a USB-C laptop charger for under $40. No subscriptions.", and a human confirms each in the UI. Write down both mandate ids:
   ```powershell
   $env:MANDATE_A = "<mnd_...>"; $env:MANDATE_B = "<mnd_...>"
   ```
4. Make sure the attack listing is **off** for session A's run (Attack Lab toggle, C02).
5. Open the screens: phone (mandate view) and big screen (Mission Control).

## Run of show (3:00)

Helper for the commands below:

```powershell
$h = @{ Authorization = "Bearer $env:AGENTS_SERVICE_TOKEN" }
function Start-Run($body) {
  $run = Invoke-RestMethod -Method Post -Uri "$env:AGENTS_URL/runs" -Headers $h `
    -ContentType "application/json" -Body ($body | ConvertTo-Json)
  $run.run_id
}
$task = 'Buy a USB-C laptop charger for under $40. No subscriptions.'
$listing = "$env:STORE_PUBLIC_URL/products/chg-65w"
```

| Time | Presenter | On screen | If it hangs |
|---|---|---|---|
| 0:00-0:20 | Aditya: "You tell your AI to buy a charger. What stops it from buying something else?" Rishi shows session A's confirmed mandate. | Original instruction, USB-C, under $40, no subscriptions, one purchase; human confirmation. | Show the mandate from the phone screenshot. |
| 0:20-0:45 | Start session A: `Start-Run @{ task=$task; mandate_id=$env:MANDATE_A; start_url=$listing; agent_mode="live" }` | Live tool trace, trusted checkout verified, grant, rail approval. Label: "Live Strands shopper". | After 20 s with no result: `Start-Run @{ task=$task; mandate_id=$env:MANDATE_A; start_url=$listing; agent_mode="scripted"; sku="CHG-65W" }` and say "scripted fallback". |
| 0:45-1:30 | Switch visibly to session B. Turn the attack listing **on** in Attack Lab. Start: `Start-Run @{ task=$task; mandate_id=$env:MANDATE_B; start_url=$listing; agent_mode="scripted"; sku="SUB-CARE-MO"; claim_sku="CHG-65W" }` | The poisoned listing's hidden text, then the agent starting a SUB-CARE-MO checkout. Label: "Simulated compromised agent (scripted)". Session B's mandate hash unchanged. | Show the incident from the preflight run of S2. |
| 1:30-2:00 | "Same merchant, same $29.99, same USD. A merchant-and-budget rule approves this." | Intent vs trusted checkout: laptop_charger vs protection_plan, one-time vs monthly. Result: **blocked before payment**, no grant. | Read the block reasons from `GET /payments/{id}`. |
| 2:00-2:35 | Open the incident. | Listing URL and SHA-256, the hidden instruction excerpt, the agent's claim ("charger") vs the checkout (subscription), failed checks, guardian findings, decision source and latency. | Show the run's trace: `Invoke-RestMethod "$env:AGENTS_URL/runs/<run_id>" -Headers $h`. |
| 2:35-3:00 | Aditya: Strands for the shopper and guardian, Akamai inference for the models, the FastAPI policy backend on Akamai compute, the selected rail. Limitation in one sentence. | Blocked incident stays on screen. | |

If timing allows, show S6 in session B after the block: turn the attack off and run `Start-Run @{ task=$task; mandate_id=$env:MANDATE_B; start_url=$listing; agent_mode="scripted"; sku="CHG-65W" }`. It's approved under the same unchanged mandate, and the incident stays in history.

## Resetting between rehearsals

- A mandate allows one purchase. Each rehearsal uses **new** sessions: propose and confirm two new mandates. Never delete or edit a used mandate, grant, or incident to "reset" it.
- Turn the attack listing off after every run.
- Spooled traces deliver on their own. Check nothing is stuck: `kubectl -n hackmidwest exec deploy/agents -- ls /app/trace-spool/pending` should be empty, and `rejected/` should be empty too (anything there means the api refused an event; read the agents log with `kubectl -n hackmidwest logs deploy/agents`).

## Outage fallbacks

| What failed | Do this |
|---|---|
| Akamai inference | Session A uses the scripted fallback (labeled). The guardian reports `model.status: unavailable` and recommends review; enforcement doesn't change. Say so. |
| Agents service | Show the preflight run's incident and trace from the UI history. |
| api or rail | Switch to the backup video, labeled prerecorded. Don't narrate a replay as live. |
| Store | Same as api. |

## Still to fill in after deployment

- The store URL, and whether the agents service stays port-forward only or the api starts runs for the UI.
- Whether the UI starts runs (Attack Lab) or we use the commands above.
- The selected rail and its exact on-screen label.
- Rehearsal timings (target: three full run-throughs at 3:00 or under).
