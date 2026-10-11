"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { apiFetch, startShopping, type StartShoppingResult, type ActivityEvent } from "@/lib/api";
import type { PurchaseMandate } from "@/lib/mandates";

type Execution = { run_id: string; state: string; financial_state: string; cancel_requested: boolean;
  graph_acknowledged: boolean; rail_stopped: boolean; progress: {
    node?: string; attempt?: number; outcome?: string; reasons?: string[]; exclusions?: Record<string, string[]> } };

export type RunSelection = { run_id: string; mandate_id: string };
const NODES = ["authority", "shopping", "verification", "investigation", "recovery", "payment", "terminal"];
const NODE_NAMES = ["Permission", "Shopping", "Verify", "Investigate", "Recover", "Authorize", "Finish"];

export function StartShopping({ mandate, onRunChange, events = [] }: {
  mandate: PurchaseMandate | null; onRunChange?: (run: RunSelection | null) => void; events?: ActivityEvent[];
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<StartShoppingResult | null>(null);
  const [storedExecution, setExecution] = useState<Execution | null>(null);
  const selectedRun = last?.mandate_id === mandate?.id ? last : null;
  const execution = storedExecution?.run_id === selectedRun?.run_id ? storedExecution : null;
  const mandateId = mandate?.id;
  const consumed = execution?.financial_state === "authorized" && mandate?.maximum_purchases === 1;
  const uncertain = execution?.financial_state === "reconciling" || execution?.financial_state === "reserved";
  const canStart = mandate?.status === "active" && !consumed && !uncertain
    && (!selectedRun || execution?.state === "terminal");
  useEffect(() => {
    if (!mandateId) return;
    let active = true;
    apiFetch<{ runs: StartShoppingResult[] }>(`/shopping/runs?mandate_id=${encodeURIComponent(mandateId)}`)
      .then(({ runs }) => { if (active) {
        const run = runs[0] ?? null; setLast(run); setExecution(null); onRunChange?.(run);
      } })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "Run history unavailable"); });
    return () => { active = false; };
  }, [mandateId, onRunChange]);
  useEffect(() => {
    if (!selectedRun) return;
    let active = true;
    const update = async () => {
      try {
        const result = await apiFetch<Execution>(`/agent-runs/${selectedRun.run_id}/execution`);
        if (active) { setExecution(result); setError(null); }
      } catch (cause) { if (active) setError(cause instanceof Error ? cause.message : "Run status unavailable"); }
    };
    void update();
    const timer = setInterval(() => void update(), 2000);
    return () => { active = false; clearInterval(timer); };
  }, [selectedRun]);
  async function start() {
    if (!mandate) return;
    setBusy(true); setError(null);
    try {
      const run = await startShopping({ mandate_id: mandate.id, agent_mode: "live", scenario: "charger" });
      setLast(run); onRunChange?.(run);
      setExecution(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not start shopping"); }
    finally { setBusy(false); }
  }
  async function stop() {
    if (!selectedRun) return;
    setBusy(true);
    try { await apiFetch(`/agent-runs/${selectedRun.run_id}/stop`, { method: "POST" }); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Stop acknowledgement pending"); }
    finally { setBusy(false); }
  }
  return <div className="space-y-3">
    <h2 className="font-semibold">Live Strands shopping</h2>
    <p className="text-sm text-muted-foreground">A bounded Graph shops through MCP, verifies the checkout, investigates rejected candidates, and safely searches for alternatives.</p>
    <Button disabled={!canStart || busy} onClick={() => void start()}>{busy ? "Working…" : "Start shopping"}</Button>
    {!mandate || mandate.status !== "active" ? <p className="text-xs">Select and confirm a mandate first.</p> : null}
    {consumed && <p className="text-xs">This mandate&apos;s purchase permission was used. Confirm a new mandate for another purchase.</p>}
    {uncertain && <p className="text-xs">Resolve the original payment outcome in Payments before starting another purchase.</p>}
    {selectedRun && <div className="space-y-3 rounded-xl border bg-muted/20 p-4 text-sm">
      <p className="break-all font-mono text-xs text-muted-foreground">{selectedRun.run_id}</p>
      <div className="grid grid-cols-4 gap-2 sm:grid-cols-7" aria-label="Recorded Graph progress">
        {NODES.map((node, index) => {
          const completed = events.some((event) => event.data.run_id === selectedRun.run_id
            && event.data.phase === "node.completed" && (event.data.reported as Record<string, unknown> | undefined)?.node === node);
          const current = execution?.state !== "terminal" && execution?.progress.node === node;
          return <div key={node} className={`rounded-lg border px-2 py-3 text-center text-[11px] transition-colors ${current ? "border-primary bg-primary/10 text-primary" : completed ? "border-primary/30" : "text-muted-foreground"}`}>
            <span className={`mx-auto mb-2 block size-2 rounded-full ${current && execution?.state !== "terminal" ? "bg-primary motion-safe:animate-pulse" : completed ? "bg-primary" : "bg-muted-foreground/30"}`} />{NODE_NAMES[index]}
          </div>;
        })}
      </div>
      <p className="font-medium">{execution?.state ?? selectedRun.status} · candidate {execution?.progress.attempt ?? 0}</p>
      <p>Financial state: {execution?.financial_state ?? "awaiting backend status"} · Local Payment Rail Simulator</p>
      {execution?.progress.outcome && <p>Execution outcome: {execution.progress.outcome}</p>}
      {execution?.progress.reasons?.map((reason) => <p key={reason} className="rounded bg-destructive/10 p-2 text-destructive">{reason.replaceAll("_", " ")}</p>)}
      {execution?.progress.outcome === "authority_ended" && <p className="text-amber-500">The worker stopped renewing its execution lease. No authorization is shown for this run; inspect its recorded startup/error events.</p>}
      {execution?.progress.exclusions && Object.entries(execution.progress.exclusions).map(([kind, items]) => items.length > 0 && <p className="break-all text-xs" key={kind}>Quarantined {kind}: {items.join(", ")}</p>)}
      {execution?.cancel_requested && <p>{execution.financial_state === "authorized" && execution.state === "terminal" ? "Workflow cleanup: unused authority closed" : "Spending stop"} · rail {execution.rail_stopped ? "enforced" : "pending"} · Graph {execution.graph_acknowledged ? "acknowledged" : "pending"}. Earlier authorization is unchanged.</p>}
      <Button variant="outline" disabled={busy || (execution?.state === "terminal" && execution.rail_stopped)} onClick={() => void stop()}>Stop this purchase</Button>
    </div>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </div>;
}
