"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { ActivityFeed } from "@/components/activity-feed";
import { KillSwitch } from "@/components/kill-switch";
import { AttackLab } from "@/components/mission-control/attack-lab";
import { AuthorityPanel } from "@/components/mission-control/authority-panel";
import { ComparisonPanel } from "@/components/mission-control/comparison-panel";
import type { ActivityEvent } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { PurchaseMandate } from "@/lib/mandates";

export default function MissionControlPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [mandate, setMandate] = useState<PurchaseMandate | null>(null);
  const [events, setEvents] = useState<ActivityEvent[]>([]);

  useEffect(() => {
    if (!loading && !user) {
      router.replace("/signin");
    }
  }, [loading, user, router]);

  const onMandateChange = useCallback((next: PurchaseMandate | null) => {
    setMandate(next);
  }, []);

  const onEventsChange = useCallback((next: ActivityEvent[]) => {
    setEvents(next);
  }, []);

  if (loading || !user) {
    return (
      <div className="flex flex-1 items-center justify-center px-4 py-16">
        <p className="text-sm text-muted-foreground">
          {loading ? "Loading Mission Control…" : "Redirecting to sign in…"}
        </p>
      </div>
    );
  }

  const instruction =
    mandate?.description ??
    "Confirm a mandate to lock human purchase authority for the shopper.";

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-8 md:py-10">
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
        <blockquote className="rounded-xl border border-border bg-muted/30 px-4 py-3 text-base leading-snug md:text-lg">
          <span className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
            Original instruction
          </span>
          <p className="mt-1 font-medium text-balance">{instruction}</p>
        </blockquote>
      </header>

      <AuthorityPanel onMandateChange={onMandateChange} />

      <div className="rounded-xl border border-border px-4 py-4 md:px-5">
        <ComparisonPanel mandate={mandate} events={events} />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-border px-4 py-4 md:px-5">
          <div className="mb-3">
            <h2 className="text-base font-semibold tracking-tight">
              Kill Switch
            </h2>
            <p className="text-xs text-muted-foreground">
              Human-only stop. Revokes unused spending authority; does not
              reverse committed authorizations.
            </p>
          </div>
          <KillSwitch />
        </div>

        <div className="rounded-xl border border-border px-4 py-4 md:px-5">
          <AttackLab />
        </div>
      </div>

      <div className="rounded-xl border border-border px-4 py-4 md:px-5">
        <ActivityFeed
          title="Live activity"
          description="Persisted backend events — not client-fabricated agent theater"
          onEventsChange={onEventsChange}
        />
      </div>
    </div>
  );
}
