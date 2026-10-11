"use client";

import { useCallback, useMemo, useState } from "react";

import { EventList } from "@/components/event-list";
import { KillSwitchButton } from "@/components/kill-switch";
import { AttackLab } from "@/components/mission-control/attack-lab";
import { AuthorityPanel } from "@/components/mission-control/authority-panel";
import { ComparisonPanel } from "@/components/mission-control/comparison-panel";
import { PurchaseHistory } from "@/components/purchase-history";
import { EmptyState } from "@/components/page";
import { useActivity } from "@/lib/activity";
import type { PurchaseMandate } from "@/lib/mandates";

// The app shell supplies auth, the shared activity stream and Kill Switch state.
export default function MissionControlPage() {
  const { events, status } = useActivity();
  const [mandate, setMandate] = useState<PurchaseMandate | null>(null);
  const recent = useMemo(() => events.slice(-25).reverse(), [events]);

  const onMandateChange = useCallback((next: PurchaseMandate | null) => {
    setMandate(next);
  }, []);

  const instruction =
    mandate?.description ??
    "Confirm a mandate to lock human purchase authority for the shopper.";
  const purchaseRevision = events.reduce((latest, event) =>
    event.type.startsWith("payment.") ? Math.max(latest, event.sequence) : latest, 0);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-3 border-b border-border pb-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
              Mission Control
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight md:text-3xl">
              LEASH
            </h1>
          </div>
          <p className="max-w-sm text-right text-xs text-muted-foreground">
            Local payment rail simulator · Lithic sandbox labeled separately ·
            Authorization ≠ settlement
          </p>
        </div>
        <blockquote className="rounded-lg border border-border bg-muted/30 px-4 py-3 text-base leading-snug md:text-lg">
          <span className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
            Original instruction
          </span>
          <p className="mt-1 font-medium text-balance">{instruction}</p>
        </blockquote>
      </header>

      <AuthorityPanel onMandateChange={onMandateChange} />
      <PurchaseHistory revision={purchaseRevision} />

      <div className="rounded-lg border border-border px-4 py-4 md:px-5">
        <ComparisonPanel mandate={mandate} events={events} />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-border px-4 py-4 md:px-5">
          <div className="mb-3">
            <h2 className="text-base font-semibold tracking-tight">
              Kill Switch
            </h2>
            <p className="text-xs text-muted-foreground">
              Human-only stop. Revokes unused spending authority; does not
              reverse committed authorizations.
            </p>
          </div>
          <KillSwitchButton />
        </div>

        <div className="rounded-lg border border-border px-4 py-4 md:px-5">
          <AttackLab />
        </div>
      </div>

      <div className="rounded-lg border border-border">
        <div className="px-4 pt-4 md:px-5">
          <h2 className="text-base font-semibold tracking-tight">Live activity</h2>
          <p className="text-xs text-muted-foreground">
            Persisted backend events — not client-fabricated agent theater
          </p>
        </div>
        {recent.length ? (
          <EventList events={recent} className="mt-3 border-t border-border" />
        ) : (
          <div className="p-4">
            <EmptyState title={status === "live" ? "No activity yet" : "Loading activity…"} />
          </div>
        )}
      </div>
    </div>
  );
}
