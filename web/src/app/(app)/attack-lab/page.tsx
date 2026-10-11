"use client";

import Link from "next/link";
import { useMemo } from "react";

import { EventList } from "@/components/event-list";
import { EmptyState, PageHeader, Panel, Section } from "@/components/page";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { useActivity } from "@/lib/activity";
import { deriveIncidents, isSuspiciousSource } from "@/lib/events";

const PRODUCT = "chg-65w";

/**
 * Read-only. Runtime attack selection is denied by the web and store routes
 * until server-verified operator access and isolated demo data exist
 * (docs/ATTACK_LAB_SECURITY_AUDIT.md). This page only shows the clean listing
 * and what real runs already recorded.
 */
export default function AttackLabPage() {
  const { events, status } = useActivity();
  const sources = useMemo(() => events.filter(isSuspiciousSource).reverse().slice(0, 8), [events]);
  const blocked = useMemo(
    () => deriveIncidents(events).filter((i) => i.sourceEvent.type === "payment.denied"),
    [events],
  );

  return (
    <>
      <PageHeader
        title="Attack Lab"
        description="How Leash handles a poisoned merchant listing. Attack scenarios can't be run from here; this page shows the clean listing and what real runs recorded."
      />

      <Panel className="mb-8 p-5">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold">The scenario</h2>
          <Badge tone="warning">Attack execution disabled</Badge>
        </div>
        <p className="mt-1.5 max-w-3xl text-sm text-muted-foreground text-pretty">
          You ask for a USB-C laptop charger under $40 with no subscriptions. A poisoned
          listing hides instructions telling shopping agents to check out a monthly protection
          plan instead. Same merchant, same $29.99, same currency, so merchant and amount
          controls alone would let it through. Leash retrieves the checkout from the merchant
          and compares the actual item against your mandate.
        </p>
        <p className="mt-3 max-w-3xl text-xs text-muted-foreground">
          Serving the poisoned listing stays off until server-verified operator access and
          isolated demo data are in place. Signing in does not unlock it.
        </p>
      </Panel>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        <Section title="Clean listing" description="The simulated merchant's page, rendered with scripts disabled.">
          <Panel className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-border px-4 py-2 text-xs text-muted-foreground">
              <span>Simulated merchant · Volt Supply Co.</span>
              <Badge tone="neutral">Clean listing</Badge>
            </div>
            <iframe
              title="Clean merchant listing"
              src={`/store/products/${PRODUCT}`}
              sandbox=""
              loading="lazy"
              className="block h-[26rem] w-full bg-white"
            />
          </Panel>
        </Section>

        <div className="flex flex-col gap-8">
          <Section
            title="Suspicious pages your agent fetched"
            description="Recorded by the agent's provenance hooks during real runs. Page content is untrusted and never instructs Leash."
          >
            <Panel>
              {sources.length ? (
                <EventList events={sources} />
              ) : (
                <div className="p-4">
                  <EmptyState title={status === "live" ? "None recorded yet" : "Loading history…"}>
                    {status === "live" ? "Pages with hidden instructions show up here after a run reads them." : null}
                  </EmptyState>
                </div>
              )}
            </Panel>
          </Section>

          <Section
            title="Outcome"
            description="Checkouts that independent verification blocked before payment."
            actions={
              <Link href="/incidents" className={buttonVariants({ variant: "ghost", size: "sm" })}>
                All incidents
              </Link>
            }
          >
            <Panel className="p-5">
              <p className="text-3xl font-semibold tabular-nums">{status === "idle" ? "—" : blocked.length}</p>
              <p className="mt-1 text-sm text-muted-foreground">
                {blocked.length === 1 ? "checkout blocked" : "checkouts blocked"} by deterministic
                policy in your history.
              </p>
              {blocked[0] ? (
                <p className="mt-3 text-sm">
                  Latest:{" "}
                  <Link href="/incidents" className="font-medium underline-offset-2 hover:underline">
                    {blocked[0].title.toLowerCase()}
                  </Link>
                </p>
              ) : null}
            </Panel>
          </Section>
        </div>
      </div>
    </>
  );
}
