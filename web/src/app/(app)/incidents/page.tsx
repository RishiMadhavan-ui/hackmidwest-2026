"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { EventList } from "@/components/event-list";
import { CheckoutComparison } from "@/components/mandate";
import { EmptyState, ErrorNote, Mono, PageHeader, Panel } from "@/components/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getMandate, type ActivityEvent, type Mandate } from "@/lib/api";
import { useActivity } from "@/lib/activity";
import { isIsolatedLabEvent } from "@/lib/activity-view";
import {
  deriveIncidents,
  formatWhen,
  reasonText,
  runIdOf,
  shortId,
  type Incident,
} from "@/lib/events";
import { errorMessage } from "@/lib/use-resource";

function Comparison({ incident }: { incident: Incident }) {
  const [mandate, setMandate] = useState<Mandate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (!incident.mandateId) return null;

  async function load() {
    setLoading(true);
    try {
      setMandate(await getMandate(incident.mandateId!));
      setError(null);
    } catch (err) {
      setError(errorMessage(err, "Could not load the mandate."));
    } finally {
      setLoading(false);
    }
  }

  if (mandate) return <CheckoutComparison mandate={mandate} reasons={incident.reasons} />;
  return (
    <div className="flex flex-col gap-2">
      <Button variant="outline" size="sm" className="self-start" onClick={() => void load()} disabled={loading}>
        {loading ? "Loading…" : "Compare with your mandate"}
      </Button>
      {error ? <ErrorNote>{error}</ErrorNote> : null}
    </div>
  );
}

function Evidence({ trace }: { trace: ActivityEvent[] }) {
  const [open, setOpen] = useState(false);
  if (!trace.length) return null;
  return (
    <div>
      <Button variant="ghost" size="sm" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        {open ? "Hide" : "Show"} agent trace ({trace.length})
      </Button>
      {open ? (
        <div className="mt-2 rounded-lg border border-border">
          <EventList events={trace} />
        </div>
      ) : null}
    </div>
  );
}

function IncidentCard({ incident, trace }: { incident: Incident; trace: ActivityEvent[] }) {
  const isolatedLab = isIsolatedLabEvent(incident.sourceEvent);
  const comparable =
    !isolatedLab &&
    incident.reasons.length > 0 &&
    (incident.sourceEvent.type === "payment.denied" || incident.sourceEvent.type.startsWith("checkout."));
  return (
    <Panel className="flex flex-col gap-4 p-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={incident.tone}>{incident.tone === "danger" ? "Blocked" : "Review"}</Badge>
            <h2 className="text-sm font-semibold">{incident.title}</h2>
          </div>
          <p className="mt-1.5 text-sm text-muted-foreground text-pretty">{incident.explanation}</p>
        </div>
        <time dateTime={incident.at} className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {formatWhen(incident.at)}
        </time>
      </div>

      {incident.reasons.length && !comparable ? (
        <ul className="flex flex-wrap gap-1.5">
          {incident.reasons.map((r) => (
            <li key={r}>
              <Badge tone="outline" className="font-normal">{reasonText(r)}</Badge>
            </li>
          ))}
        </ul>
      ) : null}

      {comparable ? <Comparison incident={incident} /> : null}

      {isolatedLab ? (
        <p className="text-sm text-muted-foreground">
          Isolated demo evidence uses a separate demo mandate. Review its run in{" "}
          <Link href="/mission-control#attack-lab" className="underline underline-offset-2">Attack Lab</Link>.
        </p>
      ) : null}

      <dl className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
        {incident.mandateId ? (
          <div>
            <dt className="inline">Mandate </dt>
            <dd className="inline">
              {isolatedLab ? (
                <Mono className="text-xs">{shortId(incident.mandateId, 10)}</Mono>
              ) : (
                <Link href={`/mandates/${encodeURIComponent(incident.mandateId)}`} className="underline-offset-2 hover:text-foreground hover:underline">
                  <Mono className="text-xs">{shortId(incident.mandateId, 10)}</Mono>
                </Link>
              )}
            </dd>
          </div>
        ) : null}
        {incident.runId ? (
          <div>
            <dt className="inline">Run </dt>
            <dd className="inline"><Mono className="text-xs">{shortId(incident.runId, 10)}</Mono></dd>
          </div>
        ) : null}
        {incident.checkoutId ? (
          <div>
            <dt className="inline">Checkout </dt>
            <dd className="inline"><Mono className="text-xs">{incident.checkoutId}</Mono></dd>
          </div>
        ) : null}
        <div>
          <dt className="inline">Event </dt>
          <dd className="inline"><Mono className="text-xs">#{incident.sourceEvent.sequence}</Mono></dd>
        </div>
      </dl>

      <Evidence trace={trace} />
    </Panel>
  );
}

export default function IncidentsPage() {
  const { events, status } = useActivity();
  const incidents = useMemo(() => deriveIncidents(events), [events]);

  // Agent tool calls and fetched pages from the same run, newest first.
  const traceByRun = useMemo(() => {
    const map = new Map<string, ActivityEvent[]>();
    for (const e of events) {
      const run = runIdOf(e);
      if (!run || !(e.type.startsWith("agent.tool") || e.type === "provenance.source")) continue;
      map.set(run, [...(map.get(run) ?? []), e]);
    }
    for (const list of map.values()) list.reverse();
    return map;
  }, [events]);

  return (
    <>
      <PageHeader
        title="Incidents"
        description="Attempts that broke a confirmed mandate, guardian findings and pages with hidden instructions. Each one links to the evidence the backend recorded."
      />
      {incidents.length ? (
        <div className="flex flex-col gap-4">
          {incidents.map((incident) => (
            <IncidentCard
              key={incident.id}
              incident={incident}
              trace={incident.runId ? traceByRun.get(incident.runId) ?? [] : []}
            />
          ))}
        </div>
      ) : (
        <EmptyState title={status === "live" ? "No incidents" : "Loading history…"}>
          {status === "live"
            ? "Nothing your agent attempted has broken a mandate. Blocked checkouts and suspicious pages appear here."
            : null}
        </EmptyState>
      )}
    </>
  );
}
