"use client";

import Link from "next/link";
import { useState } from "react";

import { EmptyState, ErrorNote, Mono } from "@/components/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { listRuns, stopRun, type OwnedRun } from "@/lib/api";
import { shortId } from "@/lib/events";
import { errorMessage, useResource } from "@/lib/use-resource";

export function agentLabel(mode: OwnedRun["agent_mode"]) {
  return mode === "scripted" ? "Simulated compromised agent" : "Live Strands shopper";
}

function StopRunDialog({
  run,
  onStopped,
}: {
  run: OwnedRun;
  onStopped: (run: OwnedRun) => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      const stop = await stopRun(run.id);
      onStopped({ ...run, stop });
      setOpen(false);
    } catch (err) {
      setError(errorMessage(err, "Stop outcome unknown. Retry, or use the Kill Switch."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        Stop run
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Stop this run?</DialogTitle>
          <DialogDescription>
            Records a stop for <Mono>{run.id}</Mono> only. Other runs and the mandate stay
            as they are. Run-level grant revocation and agent cancellation are not wired yet,
            so this is a request, not a completed financial stop. Use the Kill Switch to stop
            all spending.
          </DialogDescription>
        </DialogHeader>
        {error ? <ErrorNote>{error}</ErrorNote> : null}
        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
          <Button variant="danger" onClick={() => void confirm()} disabled={busy}>
            {busy ? "Requesting…" : "Request stop"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function RunList({ limit, mandateId }: { limit?: number; mandateId?: string }) {
  const runs = useResource(listRuns, "runs");
  const all = runs.data?.runs ?? [];
  const filtered = mandateId ? all.filter((run) => run.mandate_id === mandateId) : all;
  const shown = limit ? filtered.slice(0, limit) : filtered;

  if (runs.loading && !runs.data) {
    return <p className="px-4 py-6 text-sm text-muted-foreground">Loading runs…</p>;
  }
  if (runs.error) {
    return (
      <div className="p-4">
        <ErrorNote>Could not load runs: {runs.error}</ErrorNote>
      </div>
    );
  }
  if (!shown.length) {
    return (
      <div className="p-4">
        <EmptyState title="No agent runs yet">
          Runs appear once your agent starts shopping under a confirmed mandate.
        </EmptyState>
      </div>
    );
  }

  return (
    <ul className="divide-y divide-border">
      {shown.map((run) => (
        <li key={run.id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 px-4 py-3">
          <div className="min-w-48 flex-1">
            <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
              <span className={run.agent_mode === "scripted" ? "text-warning" : undefined}>
                {agentLabel(run.agent_mode)}
              </span>
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              <Mono className="text-xs">{shortId(run.id, 10)}</Mono>
              {" · "}
              <Link
                href={`/mandates/${encodeURIComponent(run.mandate_id)}`}
                className="underline-offset-2 hover:text-foreground hover:underline"
              >
                <Mono className="text-xs">{shortId(run.mandate_id, 10)}</Mono>
              </Link>
            </p>
          </div>
          {run.stop.cancel_requested ? (
            <Badge tone="warning">Stop requested · enforcement pending</Badge>
          ) : (
            <StopRunDialog
              run={run}
              onStopped={(next) =>
                runs.setData({
                  ...runs.data!,
                  runs: all.map((item) => (item.id === next.id ? next : item)),
                })
              }
            />
          )}
        </li>
      ))}
    </ul>
  );
}
