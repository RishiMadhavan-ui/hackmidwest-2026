"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { apiFetch, startShopping, type StartShoppingResult } from "@/lib/api";
import type { PurchaseMandate } from "@/lib/mandates";

type Execution = { state: string; financial_state: string; cancel_requested: boolean;
  graph_acknowledged: boolean; rail_stopped: boolean; progress: {
    node?: string; attempt?: number; outcome?: string; exclusions?: Record<string, string[]> } };

export function StartShopping({ mandate }: { mandate: PurchaseMandate | null }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<StartShoppingResult | null>(null);
  const [execution, setExecution] = useState<Execution | null>(null);
  const mandateId = mandate?.id;
  const consumed = execution?.financial_state === "authorized" && mandate?.maximum_purchases === 1;
  const uncertain = execution?.financial_state === "reconciling" || execution?.financial_state === "reserved";
  const canStart = mandate?.status === "active" && !consumed && !uncertain
    && (!last || execution?.state === "terminal");
  useEffect(() => {
    if (!mandateId) return;
    let active = true;
    apiFetch<{ runs: StartShoppingResult[] }>(`/shopping/runs?mandate_id=${encodeURIComponent(mandateId)}`)
      .then(({ runs }) => { if (active) { setLast(runs[0] ?? null); setExecution(null); } })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "Run history unavailable"); });
    return () => { active = false; };
  }, [mandateId]);
  useEffect(() => {
    if (!last) return;
    let active = true;
    const update = async () => {
      try {
        const result = await apiFetch<Execution>(`/agent-runs/${last.run_id}/execution`);
        if (active) { setExecution(result); setError(null); }
      } catch (cause) { if (active) setError(cause instanceof Error ? cause.message : "Run status unavailable"); }
    };
    void update();
    const timer = setInterval(() => void update(), 2000);
    return () => { active = false; clearInterval(timer); };
  }, [last]);
  async function start() {
    if (!mandate) return;
    setBusy(true); setError(null);
    try {
      setLast(await startShopping({ mandate_id: mandate.id, agent_mode: "live", scenario: "charger" }));
      setExecution(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not start shopping"); }
    finally { setBusy(false); }
  }
  async function stop() {
    if (!last) return;
    setBusy(true);
    try { await apiFetch(`/agent-runs/${last.run_id}/stop`, { method: "POST" }); }
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
    {last && <div className="space-y-2 rounded border p-3 text-sm">
      <p className="break-all text-xs">Run {last.run_id}</p>
      <p>{execution?.state ?? last.status} · {execution?.progress.node ?? "waiting for worker"} · candidate {execution?.progress.attempt ?? 0}</p>
      <p>Financial state: {execution?.financial_state ?? "awaiting backend status"} · Local Payment Rail Simulator</p>
      {execution?.progress.outcome && <p>Execution outcome: {execution.progress.outcome}</p>}
      {execution?.progress.exclusions && Object.entries(execution.progress.exclusions).map(([kind, items]) => items.length > 0 && <p className="break-all text-xs" key={kind}>Quarantined {kind}: {items.join(", ")}</p>)}
      {execution?.cancel_requested && <p>Stop requested · rail {execution.rail_stopped ? "enforced" : "pending"} · Graph {execution.graph_acknowledged ? "acknowledged" : "pending"}</p>}
      <Button variant="outline" disabled={busy || (execution?.state === "terminal" && execution.rail_stopped)} onClick={() => void stop()}>Stop this purchase</Button>
    </div>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </div>;
}
