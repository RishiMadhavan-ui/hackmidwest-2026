"use client";

import { useMemo, useState } from "react";
import { cn } from "cn";

import { EventList } from "@/components/event-list";
import { EmptyState, ErrorNote, PageHeader, Panel } from "@/components/page";
import { Dot } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useActivity } from "@/lib/activity";
import { GROUP_LABELS, groupFor, type EventGroup } from "@/lib/events";
import { activityView, newestRunId, type ActivityScope } from "@/lib/activity-view";

const PAGE = 25;
const GROUPS = Object.keys(GROUP_LABELS) as EventGroup[];

export default function ActivityPage() {
  const { events, status, error } = useActivity();
  const [group, setGroup] = useState<EventGroup | "all">("all");
  const [limit, setLimit] = useState(PAGE);
  const [scope, setScope] = useState<ActivityScope>("run");
  const [hiddenThrough, setHiddenThrough] = useState(0);
  const latestRun = newestRunId(events);
  const visible = useMemo(() => activityView(events, {
    scope: scope === "run" && !latestRun ? "today" : scope, runId: latestRun, afterSequence: hiddenThrough,
  }), [events, scope, latestRun, hiddenThrough]);

  const counts = useMemo(() => {
    const out = Object.fromEntries(GROUPS.map((g) => [g, 0])) as Record<EventGroup, number>;
    for (const e of visible) out[groupFor(e.type)]++;
    return out;
  }, [visible]);

  const filtered = useMemo(
    () => (group === "all" ? visible : visible.filter((e) => groupFor(e.type) === group)).slice().reverse(),
    [visible, group],
  );

  const tone = status === "live" ? "success" : status === "error" ? "danger" : "neutral";

  return (
    <>
      <PageHeader
        title="Activity"
        description="Follow one run’s real events. Clear the display when rehearsing; recorded evidence stays in history."
        actions={
          <span className="flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm">
            <Dot tone={tone} />
            {status === "live" ? `Live · ${visible.length} visible events` : status === "error" ? "Reconnecting…" : "Connecting…"}
          </span>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border bg-muted/20 p-3">
        <label className="text-xs font-medium" htmlFor="activity-scope">Show</label>
        <select id="activity-scope" className="rounded-lg border bg-background px-3 py-2 text-sm" value={scope}
          onChange={(event) => { setScope(event.target.value as ActivityScope); setLimit(PAGE); }}>
          <option value="run">Latest run</option><option value="today">Today</option><option value="all">All recorded history</option>
        </select>
        <Button type="button" variant="outline" size="sm" onClick={() => setHiddenThrough(events.at(-1)?.sequence ?? 0)}>Clear view</Button>
        {hiddenThrough > 0 && <Button type="button" variant="ghost" size="sm" onClick={() => setHiddenThrough(0)}>Restore view</Button>}
        <span className="text-xs text-muted-foreground">Display only · audit records are retained.</span>
      </div>

      <div role="tablist" aria-label="Filter events" className="no-scrollbar mb-4 flex gap-1 overflow-x-auto">
        {(["all", ...GROUPS] as const).map((g) => {
          const selected = g === group;
          const count = g === "all" ? visible.length : counts[g];
          return (
            <button
              key={g}
              role="tab"
              aria-selected={selected}
              onClick={() => {
                setGroup(g);
                setLimit(PAGE);
              }}
              className={cn(
                "flex h-9 shrink-0 cursor-pointer items-center gap-2 rounded-md px-3 text-sm transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/40",
                selected
                  ? "bg-secondary font-medium text-foreground"
                  : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
              )}
            >
              {g === "all" ? "All" : GROUP_LABELS[g]}
              <span className="text-xs tabular-nums text-muted-foreground">{count}</span>
            </button>
          );
        })}
      </div>

      {error && status === "error" ? <div className="mb-4"><ErrorNote>{error}</ErrorNote></div> : null}

      {filtered.length ? (
        <>
          <Panel>
            <EventList events={filtered.slice(0, limit)} />
          </Panel>
          {filtered.length > limit ? (
            <div className="mt-4 flex justify-center">
              <Button variant="outline" onClick={() => setLimit((n) => n + PAGE)}>
                Show older ({filtered.length - limit} more)
              </Button>
            </div>
          ) : null}
        </>
      ) : (
        <EmptyState title={status === "live" ? "No events in this view" : "Loading history…"}>
          {status === "live" ? "Events show up here as soon as the backend records them." : null}
        </EmptyState>
      )}
    </>
  );
}
