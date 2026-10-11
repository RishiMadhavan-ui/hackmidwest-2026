"use client";

import { useState } from "react";
import { RotateCw } from "lucide-react";
import { cn } from "cn";

import { MandateRow } from "@/components/mandate";
import { EmptyState, ErrorNote, PageHeader, Panel } from "@/components/page";
import { Button } from "@/components/ui/button";
import { listMandates, type Mandate } from "@/lib/api";
import { useResource } from "@/lib/use-resource";

const FILTERS = [
  { id: "all", label: "All", match: () => true },
  { id: "proposed", label: "Awaiting confirmation", match: (m: Mandate) => m.status === "proposed" },
  { id: "active", label: "Active", match: (m: Mandate) => m.status === "active" },
  {
    id: "ended",
    label: "Ended",
    match: (m: Mandate) => m.status === "revoked" || m.status === "expired" || m.status === "superseded",
  },
] as const;

type FilterId = (typeof FILTERS)[number]["id"];

export default function MandatesPage() {
  const mandates = useResource(() => listMandates(), "mandates");
  const [filter, setFilter] = useState<FilterId>("all");
  const all = mandates.data ?? [];
  const current = FILTERS.find((f) => f.id === filter)!;
  const shown = [...all]
    .filter(current.match)
    .sort((a, b) => b.created_at.localeCompare(a.created_at));

  return (
    <>
      <PageHeader
        title="Mandates"
        description="A mandate is the exact purchase authority you confirmed. Agents can draft one; changes create a new version that needs your confirmation again."
        actions={
          <Button variant="outline" onClick={() => void mandates.refresh()} disabled={mandates.loading}>
            <RotateCw aria-hidden />
            Refresh
          </Button>
        }
      />

      <div role="tablist" aria-label="Filter mandates" className="no-scrollbar mb-4 flex gap-1 overflow-x-auto">
        {FILTERS.map((f) => {
          const count = all.filter(f.match).length;
          const selected = f.id === filter;
          return (
            <button
              key={f.id}
              role="tab"
              aria-selected={selected}
              onClick={() => setFilter(f.id)}
              className={cn(
                "flex h-9 shrink-0 cursor-pointer items-center gap-2 rounded-md px-3 text-sm transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/40",
                selected
                  ? "bg-secondary font-medium text-foreground"
                  : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
              )}
            >
              {f.label}
              {mandates.data ? (
                <span className="text-xs tabular-nums text-muted-foreground">{count}</span>
              ) : null}
            </button>
          );
        })}
      </div>

      {mandates.error ? <ErrorNote>Could not load mandates: {mandates.error}</ErrorNote> : null}

      {mandates.loading && !mandates.data ? (
        <p className="py-8 text-sm text-muted-foreground">Loading mandates…</p>
      ) : shown.length ? (
        <Panel className="divide-y divide-border">
          {shown.map((m) => (
            <MandateRow key={m.id} mandate={m} />
          ))}
        </Panel>
      ) : mandates.data ? (
        <EmptyState title={filter === "all" ? "No mandates yet" : "Nothing here"}>
          {filter === "all"
            ? "When your shopping agent drafts a purchase, it appears here for you to review and confirm."
            : "No mandates match this filter."}
        </EmptyState>
      ) : null}
    </>
  );
}
