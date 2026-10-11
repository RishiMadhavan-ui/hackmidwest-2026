"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "cn";

import { Dot } from "@/components/ui/badge";
import type { ActivityEvent } from "@/lib/api";
import { formatWhen, eventTitle, summarize, toneFor } from "@/lib/events";

function EventRow({ event, expandable }: { event: ActivityEvent; expandable: boolean }) {
  const [open, setOpen] = useState(false);
  const summary = summarize(event);
  const tone = toneFor(event);
  const scripted = event.data.agent_mode === "scripted";

  const content = (
    <>
      <Dot tone={tone} className="mt-1.5" />
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-x-2 text-sm font-medium">
          {eventTitle(event)}
          {scripted ? (
            <span className="text-xs font-normal text-warning">Scripted shopper run</span>
          ) : null}
        </p>
        {summary ? (
          <p className="mt-0.5 truncate text-xs text-muted-foreground" title={summary}>
            {summary}
          </p>
        ) : null}
      </div>
      <time dateTime={event.at} className="shrink-0 pt-0.5 text-xs tabular-nums text-muted-foreground">
        {formatWhen(event.at)}
      </time>
      {expandable ? (
        <ChevronRight
          aria-hidden
          className={cn("mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")}
        />
      ) : null}
    </>
  );

  if (!expandable) {
    return <li className="activity-entry flex items-start gap-3 px-4 py-3">{content}</li>;
  }

  return (
    <li className="activity-entry">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full cursor-pointer items-start gap-3 px-4 py-3 text-left transition-colors outline-none hover:bg-secondary/50 focus-visible:bg-secondary/60"
      >
        {content}
      </button>
      {open ? (
        <div className="px-4 pb-4 pl-9">
          <dl className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <div>
              <dt className="inline">Sequence </dt>
              <dd className="inline font-mono">#{event.sequence}</dd>
            </div>
            <div>
              <dt className="inline">Event </dt>
              <dd className="inline font-mono">{event.event_id}</dd>
            </div>
            <div>
              <dt className="inline">Type </dt>
              <dd className="inline font-mono">{event.type}</dd>
            </div>
          </dl>
          <pre className="max-h-80 overflow-auto rounded-md bg-muted px-3 py-2 font-mono text-xs leading-relaxed">
            {JSON.stringify(event.data, null, 2)}
          </pre>
        </div>
      ) : null}
    </li>
  );
}

/** Newest first. Rows show persisted, sanitized backend data only. */
export function EventList({
  events,
  expandable = true,
  className,
}: {
  events: ActivityEvent[];
  expandable?: boolean;
  className?: string;
}) {
  return (
    <ul className={cn("divide-y divide-border", className)}>
      {events.map((event) => (
        <EventRow key={event.event_id} event={event} expandable={expandable} />
      ))}
    </ul>
  );
}
