"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useActivity } from "@/lib/activity";
import type { PurchaseMandate } from "@/lib/mandates";
import { Button } from "@/components/ui/button";

type Draft = { mandate: PurchaseMandate; mode: string; scenario: string };
type History = { attempts: { id: string; checkout_id: string; state: string; reason: string; authorization_status: string }[];
  runs: { run_id: string; state: string; scenario: string; progress: { node?: string; attempt?: number; outcome?: string } }[] };

export function LabScenarios({ namespaceId, enabled, onReset }: { namespaceId: string; enabled: boolean; onReset: () => void }) {
  const { events } = useActivity();
  const [scenario, setScenario] = useState("signature_attack");
  const [mode, setMode] = useState("live");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [history, setHistory] = useState<History | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const base = `/attack-lab/namespaces/${encodeURIComponent(namespaceId)}`;
  useEffect(() => {
    let active = true;
    const update = async () => {
      try { const next = await apiFetch<History>(`${base}/history`); if (active) setHistory(next); }
      catch { /* Action errors are shown separately; persisted stream remains available. */ }
    };
    void update(); const timer = setInterval(() => void update(), 2000);
    return () => { active = false; clearInterval(timer); };
  }, [base]);
  async function act(action: "draft" | "execute" | "reset") {
    setBusy(true); setError(null);
    try {
      if (action === "draft") {
        setConfirmed(false);
        setDraft(await apiFetch<Draft>(`${base}/draft`, { method: "POST", body: JSON.stringify({ scenario, mode }) }));
      } else if (action === "execute" && draft && confirmed) {
        await apiFetch(`${base}/execute`, { method: "POST", body: JSON.stringify({
          mandate_id: draft.mandate.id, version: draft.mandate.version,
          canonical_payload_hash: draft.mandate.canonical_payload_hash, confirmed: true,
        }) });
        setDraft(null); setConfirmed(false);
      } else if (action === "reset") {
        await apiFetch(`${base}/reset`, { method: "POST", body: "{}" });
        setDraft(null); setConfirmed(false); onReset();
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Scenario request failed"); }
    finally { setBusy(false); }
  }
  const labEvents = events.filter((event) => event.data.lab_namespace_id === namespaceId).slice(-20);
  async function stop(runId: string) {
    setBusy(true);
    try { await apiFetch(`${base}/runs/${encodeURIComponent(runId)}/stop`, { method: "POST", body: "{}" }); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Stop enforcement pending"); }
    finally { setBusy(false); }
  }
  return <div className="mt-4 space-y-3 border-t pt-4">
    <h3 className="text-sm font-semibold">Isolated scenarios · Local Payment Rail Simulator</h3>
    <p className="text-xs text-muted-foreground">Real Graph, MCP, checkout verification and atomic rail policy. Live mode uses configured inference; scripted mode uses a labeled model fixture. No real-money or unrestricted Lithic operations.</p>
    <div className="flex flex-wrap gap-2">
      <select aria-label="Lab scenario" className="rounded border bg-background p-2 text-sm" value={scenario} onChange={(e) => { setScenario(e.target.value); setDraft(null); }}>
        <option value="signature_attack">Poisoned listing → containment → clean recovery</option><option value="legitimate_charger">Legitimate charger</option>
      </select>
      <select aria-label="Lab model mode" className="rounded border bg-background p-2 text-sm" value={mode} onChange={(e) => { setMode(e.target.value); setDraft(null); }}>
        <option value="live">Live Strands shopper</option><option value="scripted">Scripted model fixture (labeled)</option>
      </select>
      <Button disabled={busy || !enabled} onClick={() => void act("draft")}>Prepare demo mandate</Button>
    </div>
    {draft && <div className="space-y-2 rounded border p-3 text-sm">
      <p>{draft.mandate.description}</p>
      <p>USB-C charger · ceiling ${(draft.mandate.max_cents/100).toFixed(2)} USD · 1 item · 1 purchase · no subscription/recurrence · expires {new Date(draft.mandate.valid_until).toLocaleTimeString()}</p>
      <p className="text-xs">{draft.mode === "live" ? "Live inference" : "Scripted model fixture"} · isolated identity {draft.mandate.user_id}</p>
      <label className="flex gap-2"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />I confirm these exact demo terms.</label>
      <Button disabled={busy || !enabled || !confirmed} onClick={() => void act("execute")}>Confirm and run scenario</Button>
    </div>}
    {history?.runs.map((run) => <div key={run.run_id}><p className="break-all text-xs">{run.scenario} · {run.state} · {run.progress.node ?? "waiting"} · candidate {run.progress.attempt ?? 0} · {run.progress.outcome ?? "pending"}</p>
      {run.state !== "terminal" && <Button variant="outline" disabled={busy} onClick={() => void stop(run.run_id)}>Stop this demo purchase</Button>}</div>)}
    {history?.attempts.map((attempt) => <p key={attempt.id} className="text-xs">{attempt.checkout_id} · {attempt.state} · {attempt.reason} · authorization {attempt.authorization_status}</p>)}
    {labEvents.map((event) => <p key={event.event_id} className="text-xs text-muted-foreground">{event.type} · {String(event.data.phase ?? event.data.reported_outcome ?? "persisted event")}</p>)}
    <Button variant="outline" disabled={busy} onClick={() => void act("reset")}>Stop and reset isolated fixtures</Button>
    <p className="text-xs text-muted-foreground">Reset disables the workspace, revokes demo authority, and preserves evidence. Scenarios expire after 120 seconds; at most three candidates and one active run.</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </div>;
}
