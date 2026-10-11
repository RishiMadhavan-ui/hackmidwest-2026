"use client";

import Link from "next/link";
import { useMemo } from "react";
import { ArrowRight } from "lucide-react";

import { EventList } from "@/components/event-list";
import { isFullyEnforced, useKillSwitch } from "@/components/kill-switch";
import { MandateRow, expiryText, humanize } from "@/components/mandate";
import { EmptyState, ErrorNote, PageHeader, Panel, Section } from "@/components/page";
import { RunList } from "@/components/run-list";
import { buttonVariants } from "@/components/ui/button";
import { formatUsdFromCents, listMandates } from "@/lib/api";
import { useActivity } from "@/lib/activity";
import { deriveIncidents } from "@/lib/events";
import { useAuth } from "@/lib/auth";
import { useResource } from "@/lib/use-resource";

function Stat({ label, value, note }: { label: string; value: React.ReactNode; note?: string }) {
  return (
    <div className="bg-card px-5 py-4">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold tabular-nums tracking-tight">{value}</dd>
      {note ? <dd className="mt-0.5 text-xs text-muted-foreground">{note}</dd> : null}
    </div>
  );
}

export default function OverviewPage() {
  const { user } = useAuth();
  const { events, status } = useActivity();
  const killSwitch = useKillSwitch();
  const mandates = useResource(() => listMandates(), "mandates");

  const all = mandates.data ?? [];
  const proposed = all.filter((m) => m.status === "proposed");
  const active = all.filter((m) => m.status === "active");
  const incidents = useMemo(() => deriveIncidents(events), [events]);
  const blocked = incidents.filter((i) => i.sourceEvent.type === "payment.denied").length;
  const recent = useMemo(() => events.slice(-10).reverse(), [events]);

  const stopped = killSwitch.state?.on;
  const shopping = killSwitch.state
    ? stopped
      ? isFullyEnforced(killSwitch.state)
        ? "Stopped"
        : "Stopping"
      : "Allowed"
    : "—";

  return (
    <>
      <PageHeader
        title="Mission Control"
        description={`Signed in as ${user?.first_name ? `${user.first_name} (${user.email})` : user?.email}. Everything here is read from persisted backend records.`}
      />

      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border lg:grid-cols-4">
        <Stat label="Shopping" value={<span className={stopped ? "text-danger" : undefined}>{shopping}</span>} note={stopped ? "Kill Switch engaged" : "Within confirmed mandates"} />
        <Stat label="Active mandates" value={mandates.data ? active.length : "—"} />
        <Stat label="Awaiting your confirmation" value={mandates.data ? proposed.length : "—"} />
        <Stat
          label="Blocked before payment"
          value={<span className={blocked ? "text-danger" : undefined}>{status === "idle" ? "—" : blocked}</span>}
          note="Policy blocks in your history"
        />
      </dl>

      {mandates.error ? (
        <div className="mt-6">
          <ErrorNote>Could not load mandates: {mandates.error}</ErrorNote>
        </div>
      ) : null}

      {proposed.length ? (
        <Section
          className="mt-8"
          title="Needs your confirmation"
          description="Your agent drafted these. Nothing can be bought until you confirm the exact terms."
        >
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {proposed.map((m) => (
              <Panel key={m.id} className="flex flex-col gap-3 p-5">
                <div>
                  <p className="text-sm font-medium">{m.description}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {humanize(m.category)} · up to {formatUsdFromCents(m.max_cents)} ·{" "}
                    {m.allow_subscription ? "subscriptions allowed" : "no subscriptions"} ·{" "}
                    {expiryText(m)}
                  </p>
                </div>
                <Link
                  href={`/mandates/${encodeURIComponent(m.id)}`}
                  className={buttonVariants({ className: "self-start" })}
                >
                  Review and confirm
                  <ArrowRight aria-hidden />
                </Link>
              </Panel>
            ))}
          </div>
        </Section>
      ) : null}

      <div className="mt-8 grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
        <Section
          title="Recent activity"
          description="Persisted events, newest first."
          actions={
            <Link href="/activity" className={buttonVariants({ variant: "ghost", size: "sm" })}>
              Full timeline
            </Link>
          }
        >
          <Panel>
            {recent.length ? (
              <EventList events={recent} expandable={false} />
            ) : (
              <div className="p-4">
                <EmptyState title={status === "error" ? "Activity stream unavailable" : status === "live" ? "No activity yet" : "Loading activity…"}>
                  {status === "live" ? "Events appear here as soon as the backend records them." : null}
                </EmptyState>
              </div>
            )}
          </Panel>
        </Section>

        <div className="flex flex-col gap-8">
          <Section
            title="Active mandates"
            actions={
              <Link href="/mandates" className={buttonVariants({ variant: "ghost", size: "sm" })}>
                All mandates
              </Link>
            }
          >
            <Panel>
              {mandates.loading && !mandates.data ? (
                <p className="px-4 py-6 text-sm text-muted-foreground">Loading…</p>
              ) : active.length ? (
                <div className="divide-y divide-border">
                  {active.slice(0, 4).map((m) => (
                    <MandateRow key={m.id} mandate={m} />
                  ))}
                </div>
              ) : (
                <div className="p-4">
                  <EmptyState title="No active mandates">
                    <Link href="/mandates/new" className="font-medium text-foreground underline-offset-4 hover:underline">
                      Create a mandate
                    </Link>{" "}
                    or ask your shopping agent to draft one. You confirm it before anything can be bought.
                  </EmptyState>
                </div>
              )}
            </Panel>
          </Section>

          <Section title="Agent runs" description="Stop a single run here, or use the Kill Switch for everything.">
            <Panel>
              <RunList limit={5} />
            </Panel>
          </Section>
        </div>
      </div>
    </>
  );
}
