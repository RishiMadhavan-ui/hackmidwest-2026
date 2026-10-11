"use client";

import { useMemo, useState } from "react";
import { cn } from "cn";

import { EventList } from "@/components/event-list";
import { EmptyState, ErrorNote, PageHeader, Panel } from "@/components/page";
import { Dot } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useActivity } from "@/lib/activity";
import { GROUP_LABELS, groupFor, type EventGroup } from "@/lib/events";

const PAGE = 100;
const GROUPS = Object.keys(GROUP_LABELS) as EventGroup[];

export default function ActivityPage() {
  const { events, status, error } = useActivity();
  const [group, setGroup] = useState<EventGroup | "all">("all");
  const [limit, setLimit] = useState(PAGE);

  const counts = useMemo(() => {
    const out = Object.fromEntries(GROUPS.map((g) => [g, 0])) as Record<EventGroup, number>;
    for (const e of events) out[groupFor(e.type)]++;
    return out;
  }, [events]);

  const filtered = useMemo(
    () => (group === "all" ? events : events.filter((e) => groupFor(e.type) === group)).slice().reverse(),
    [events, group],
  );

  const tone = status === "live" ? "success" : status === "error" ? "danger" : "neutral";

  return (
    <>
      <PageHeader
        title="Activity"
        description="Append-only history recorded by the backend: mandates, agent tool calls, fetched pages, checkout decisions and controls. Reloading replays it; it never starts a run."
        actions={
          <span className="flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm">
            <Dot tone={tone} />
            {status === "live" ? `Live · ${events.length} events` : status === "error" ? "Reconnecting…" : "Connecting…"}
          </span>
        }
      />

      <div role="tablist" aria-label="Filter events" className="no-scrollbar mb-4 flex gap-1 overflow-x-auto">
        {(["all", ...GROUPS] as const).map((g) => {
          const selected = g === group;
          const count = g === "all" ? events.length : counts[g];
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
