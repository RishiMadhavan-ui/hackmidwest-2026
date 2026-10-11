"use client";

import { useEffect, useState } from "react";
import { apiFetch, type RunStop } from "@/lib/api";
import { useActivity } from "@/lib/activity";
import { activityView } from "@/lib/activity-view";
import type { PurchaseMandate } from "@/lib/mandates";
import { Button } from "@/components/ui/button";
import { EventList } from "@/components/event-list";

type Draft = { mandate: PurchaseMandate; mode: string; scenario: string };
type History = { attempts: { id: string; run_id: string; checkout_id: string; state: string; reason: string;
    authorization_status: string; result: { reasons: string[] } | null }[];
  runs: { run_id: string; state: string; scenario: string; rail_stopped_at: string | null; graph_ack_at: string | null;
    progress: { node?: string; attempt?: number; outcome?: string; reasons?: string[] } }[] };

export function LabScenarios({ namespaceId, enabled, onReset }: { namespaceId: string; enabled: boolean; onReset: () => void }) {
  const { events } = useActivity();
  const [scenario, setScenario] = useState("signature_attack");
  const [mode, setMode] = useState("live");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [history, setHistory] = useState<History | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [stopResult, setStopResult] = useState<RunStop | null>(null);
  const [page, setPage] = useState(0);
  const [clearedThrough, setClearedThrough] = useState(0);
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
        const launched = await apiFetch<{ run_id: string }>(`${base}/execute`, { method: "POST", body: JSON.stringify({
          mandate_id: draft.mandate.id, version: draft.mandate.version,
          canonical_payload_hash: draft.mandate.canonical_payload_hash, confirmed: true,
        }) });
        setSelectedRunId(launched.run_id); setStopResult(null); setPage(0); setClearedThrough(0);
        setDraft(null); setConfirmed(false);
      } else if (action === "reset") {
        await apiFetch(`${base}/reset`, { method: "POST", body: "{}" });
        setDraft(null); setConfirmed(false); onReset();
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Scenario request failed"); }
    finally { setBusy(false); }
  }
  const runId = selectedRunId ?? history?.runs[0]?.run_id ?? null;
  const run = history?.runs.find((item) => item.run_id === runId);
  const attempts = history?.attempts.filter((item) => item.run_id === runId) ?? [];
  const scopedEvents = events.filter((event) => event.data.lab_namespace_id === namespaceId);
  const labEvents = activityView(scopedEvents, { scope: "run", runId, afterSequence: clearedThrough,
    paymentIds: attempts.map((item) => item.id) });
  const pages = Math.max(1, Math.ceil(labEvents.length / 25));
  const currentPage = Math.min(page, pages - 1);
  const visibleEvents = [...labEvents].reverse().slice(currentPage * 25, (currentPage + 1) * 25);
  const recordedMode = scopedEvents.findLast((event) => event.data.run_id === runId
    && typeof event.data.agent_mode === "string")?.data.agent_mode;
  async function stop(runId: string) {
    setBusy(true); setError(null);
    try { setStopResult(await apiFetch<RunStop>(`${base}/runs/${encodeURIComponent(runId)}/stop`, { method: "POST", body: "{}" })); }
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
    {history && history.runs.length > 0 && <label className="block text-xs text-muted-foreground">Recorded scenario
      <select aria-label="Recorded Lab run" className="mt-1 w-full rounded border bg-background p-2 text-sm" value={runId ?? ""}
        onChange={(event) => { setSelectedRunId(event.target.value); setStopResult(null); setPage(0); setClearedThrough(0); }}>
        {selectedRunId && !run && <option value={selectedRunId}>Launching new run…</option>}
        {history.runs.map((item) => <option key={item.run_id} value={item.run_id}>{item.scenario.replaceAll("_", " ")} · {item.progress.outcome ?? item.state} · {item.run_id.slice(-8)}</option>)}
      </select>
    </label>}
    {runId && <div className="space-y-3 rounded-xl border bg-muted/20 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-semibold">{run?.progress.outcome?.replaceAll("_", " ") ?? "Launching"} · candidate {run?.progress.attempt ?? 0}</h4>
        <span className="rounded border px-2 py-1 text-xs">{recordedMode === "scripted" ? "Scripted shopper fixture" : recordedMode === "live" ? "Live shopper" : "Mode awaiting recorded evidence"}</span>
      </div>
      <p className="break-all font-mono text-[11px] text-muted-foreground">{runId}</p>
      {run && <p className="text-xs">Workflow {run.state} · latest node {run.progress.node ?? "waiting"}</p>}
      {run?.progress.reasons?.map((reason) => <p key={reason} className="text-xs text-warning">{reason.replaceAll("_", " ")}</p>)}
      {run?.rail_stopped_at && <p className="text-xs">Unused spending authority revoked. Earlier authorizations remain unchanged.</p>}
      {run?.progress.outcome === "stopped" && <p role="status" className="text-sm">Purchase stopped · rail {run.rail_stopped_at ? "enforced" : "pending"} · Graph {run.graph_ack_at ? "acknowledged" : "pending"}</p>}
      {stopResult?.run_id === runId && <p role="status" className="text-xs">Stop request · financial revocation {stopResult.financial_revocation} · Graph {run?.graph_ack_at ? "acknowledged" : stopResult.graph_cancellation}. No prior authorization reversed.</p>}
      {run?.state !== "terminal" && <Button variant="outline" disabled={busy} onClick={() => void stop(runId)}>Stop this demo purchase</Button>}
      <div className="grid gap-2 sm:grid-cols-2">
        {attempts.map((attempt) => <div key={attempt.id} className={`rounded-lg border p-3 ${attempt.state === "blocked" ? "border-destructive/40 bg-destructive/5" : "bg-background"}`}>
          <p className="text-sm font-medium">{attempt.state === "blocked" ? "Blocked before payment" : attempt.authorization_status === "authorized" ? "Authorization recorded" : attempt.state.replaceAll("_", " ")}</p>
          <p className="mt-1 break-all font-mono text-[11px] text-muted-foreground">{attempt.checkout_id}</p>
          {(attempt.result?.reasons ?? [attempt.reason]).filter(Boolean).map((reason) => <p key={reason} className="mt-1 text-xs">{reason.replaceAll("_", " ")}</p>)}
          {attempt.authorization_status === "authorized" && <p className="mt-1 text-xs">Local Payment Rail Simulator · authorization is not settlement.</p>}
        </div>)}
      </div>
      {attempts.length === 0 && <p className="text-xs text-muted-foreground">No purchase attempt recorded for this run.</p>}
      <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3">
        <h4 className="text-sm font-semibold">This run&apos;s persisted evidence</h4>
        <div className="flex gap-2"><Button variant="outline" size="sm" onClick={() => { setClearedThrough(events.at(-1)?.sequence ?? 0); setPage(0); }}>Clear view</Button>
          {clearedThrough > 0 && <Button variant="outline" size="sm" onClick={() => { setClearedThrough(0); setPage(0); }}>Restore view</Button>}</div>
      </div>
      <p className="text-xs text-muted-foreground">Clearing hides entries only. Open rows for recorded reasons, product SKUs, source hashes and Graph evidence. Model failures remain visible.</p>
      <EventList events={visibleEvents} />
      {visibleEvents.length === 0 && <p className="text-xs text-muted-foreground">No visible events. History is retained.</p>}
      {pages > 1 && <div className="flex items-center justify-between gap-2 text-xs">
        <Button variant="outline" size="sm" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Newer events</Button>
        <span>{currentPage + 1} / {pages}</span>
        <Button variant="outline" size="sm" disabled={currentPage === pages - 1} onClick={() => setPage(currentPage + 1)}>Older events</Button>
      </div>}
    </div>}
    <Button variant="outline" disabled={busy} onClick={() => void act("reset")}>Stop and reset isolated fixtures</Button>
    <p className="text-xs text-muted-foreground">Reset disables the workspace, revokes demo authority, and preserves evidence. Scenarios expire after 120 seconds; at most three candidates and one active run.</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </div>;
}
