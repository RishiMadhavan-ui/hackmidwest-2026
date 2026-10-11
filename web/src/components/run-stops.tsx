"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";

type RunStop = {
  cancel_requested: boolean;
  financial_revocation: string;
  graph_cancellation: string;
};
type OwnedRun = { id: string; mandate_id: string; agent_mode: string; stop: RunStop };

export function RunStops() {
  const [runs, setRuns] = useState<OwnedRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    try {
      const result = await apiFetch<{ runs: OwnedRun[] }>("/agent-runs");
      setRuns(result.runs);
      setError(null);
    } catch { setError("Could not load your registered purchase runs."); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => {
    let active = true;
    apiFetch<{ runs: OwnedRun[] }>("/agent-runs").then((result) => {
      if (active) { setRuns(result.runs); setLoading(false); }
    }).catch(() => {
      if (active) { setError("Could not load your registered purchase runs."); setLoading(false); }
    });
    return () => { active = false; };
  }, []);

  async function stop(run: OwnedRun) {
    if (!window.confirm(`Request a stop for purchase ${run.id} only? Other purchases and the mandate remain unchanged. Financial revocation and Graph cancellation are not yet integrated.`)) return;
    setBusy(run.id);
    try {
      const result = await apiFetch<RunStop>(`/agent-runs/${encodeURIComponent(run.id)}/stop`, { method: "POST" });
      setRuns((current) => current.map((item) => item.id === run.id ? { ...item, stop: result } : item));
      setError(null);
    } catch { setError("Run stop outcome unknown. Refresh or retry the same run; use Emergency Kill Switch for account-wide enforcement."); }
    finally { setBusy(null); }
  }

  return (
    <section className="flex flex-col gap-3 border-t border-border pt-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium">Stop This Purchase</h3>
        <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={loading || !!busy}>Refresh runs</Button>
      </div>
      <p className="text-xs text-muted-foreground">Stops one run only. Run-level financial revocation and Graph cancellation are pending integration; a request is not a completed financial stop.</p>
      {loading ? <p className="text-sm">Loading registered runs…</p> : null}
      {!loading && !error && !runs.length ? <p className="text-sm text-muted-foreground">No registered purchase runs.</p> : null}
      {runs.map((run) => (
        <div key={run.id} className="flex flex-col gap-2 rounded border border-border p-3">
          <p className="break-all text-xs">{run.id} · {run.agent_mode} · {run.mandate_id}</p>
          <Button variant="destructive" size="sm" onClick={() => void stop(run)} disabled={!!busy || run.stop.cancel_requested}>
            {busy === run.id ? "Requesting stop…" : run.stop.cancel_requested ? "Stop requested — enforcement pending" : "Stop This Purchase"}
          </Button>
          {run.stop.cancel_requested ? <p className="text-xs" role="status">Request persisted. Financial revocation pending; Graph cancellation not acknowledged. Already authorized purchases are not reversed.</p> : null}
        </div>
      ))}
      <p className="text-xs text-muted-foreground">Showing up to 100 registered runs.</p>
      {error ? <p className="text-xs" role="alert">{error}</p> : null}
    </section>
  );
}
