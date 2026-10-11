"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { EventList } from "@/components/event-list";
import { KillSwitchButton } from "@/components/kill-switch";
import { AttackLab } from "@/components/mission-control/attack-lab";
import { AuthorityPanel } from "@/components/mission-control/authority-panel";
import { ComparisonPanel } from "@/components/mission-control/comparison-panel";
import { StartShopping, type RunSelection } from "@/components/mission-control/start-shopping";
import { PurchaseHistory } from "@/components/purchase-history";
import { Button } from "@/components/ui/button";
import { useActivity } from "@/lib/activity";
import { activityView, newestRunId } from "@/lib/activity-view";
import type { PurchaseMandate } from "@/lib/mandates";

const STEPS = ["Mandate", "Live run", "Evidence"] as const;

export default function MissionControlPage() {
  const { events, status } = useActivity();
  const [mandate, setMandate] = useState<PurchaseMandate | null>(null);
  const [run, setRun] = useState<RunSelection | null>(null);
  const [step, setStep] = useState<(typeof STEPS)[number]>("Mandate");
  const [hiddenThrough, setHiddenThrough] = useState(0);
  const onMandateChange = useCallback((next: PurchaseMandate | null) => setMandate(next), []);
  const onRunChange = useCallback((next: RunSelection | null) => setRun(next), []);
  const runId = run?.mandate_id === mandate?.id ? run?.run_id : mandate ? newestRunId(events, mandate.id) : null;
  const current = activityView(events, { scope: "run", runId, mandateId: mandate?.id, afterSequence: hiddenThrough });

  return <div className="mx-auto flex w-full max-w-6xl flex-col gap-5">
    <header className="rounded-2xl border bg-gradient-to-br from-primary/10 via-background to-background p-5 md:p-7">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div><p className="text-xs font-medium uppercase tracking-[0.18em] text-primary">LEASH · Mission Control</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight md:text-3xl">Your intent. Every purchase checked.</h1>
          <p className="mt-2 text-sm text-muted-foreground">Confirm the rules, follow one run, inspect its evidence.</p></div>
        <KillSwitchButton />
      </div>
      {mandate && <div className="mt-5 border-t pt-4">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full border border-primary/30 bg-primary/10 px-3 py-1">{mandate.status} · v{mandate.version}</span>
          <span className="text-muted-foreground">Maximum ${(mandate.max_cents / 100).toFixed(2)} · {mandate.maximum_purchases} purchase · {mandate.allow_recurring ? "recurrence allowed" : "no recurring charges"}</span>
        </div>
        <p className="mt-3 text-base font-medium">{mandate.description}</p>
        <p className="mt-2 break-all font-mono text-[11px] text-muted-foreground">{mandate.id} · {mandate.canonical_payload_hash?.slice(0, 16)}</p>
      </div>}
    </header>
    <nav className="grid grid-cols-3 gap-2" aria-label="Shopping workflow">
      {STEPS.map((name, index) => <button key={name} type="button" aria-current={step === name ? "step" : undefined}
        onClick={() => setStep(name)} className={`rounded-xl border px-3 py-3 text-left text-sm transition-colors ${step === name ? "border-primary/50 bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted"}`}>
        <span className="mr-2 inline-flex size-6 items-center justify-center rounded-full border text-xs">{index + 1}</span>{name}
      </button>)}
    </nav>
    <div className={step === "Mandate" ? "space-y-4 rounded-2xl border p-4 md:p-5" : "hidden"}>
      <AuthorityPanel onMandateChange={onMandateChange} />
      {mandate?.status === "active" && <Button type="button" onClick={() => setStep("Live run")}>Continue to shopping →</Button>}
    </div>
    <div className={step === "Live run" ? "space-y-5" : "hidden"}>
      <section className="rounded-2xl border p-4 md:p-5"><StartShopping mandate={mandate} events={events} onRunChange={onRunChange} /></section>
      <section className="rounded-2xl border p-4 md:p-5"><ComparisonPanel mandate={mandate} events={events} runId={runId} /></section>
      <section className="overflow-hidden rounded-2xl border">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b p-4">
          <div><h2 className="font-semibold">This run’s activity</h2><p className="mt-1 text-xs text-muted-foreground">{status === "live" ? "Connected" : "Reconnecting"} · persisted evidence · latest 30 entries</p></div>
          <div className="flex gap-2"><Button type="button" variant="ghost" size="sm" onClick={() => setHiddenThrough(events.at(-1)?.sequence ?? 0)}>Clear view</Button>
            {hiddenThrough > 0 && <Button type="button" variant="ghost" size="sm" onClick={() => setHiddenThrough(0)}>Restore view</Button>}
            <Link href="/activity" className="self-center text-xs text-primary">Full timeline →</Link></div>
        </header>
        {current.length ? <EventList events={current.slice(-30).reverse()} /> : <p className="p-6 text-sm text-muted-foreground">{runId ? "No visible events for this run. Cleared entries remain in history." : "Start shopping to follow this run’s actual events."}</p>}
      </section>
    </div>
    {step === "Evidence" && <div className="space-y-4"><PurchaseHistory revision={events.filter((event) => event.type.startsWith("payment.")).length} />
      <p className="text-xs text-muted-foreground">Local Payment Rail Simulator · authorization is not settlement. Historic attempts remain available here.</p></div>}
    <details className="rounded-xl border p-4" id="operator-controls"><summary className="cursor-pointer text-sm font-medium">Operator demo controls</summary>
      <div className="mt-4"><AttackLab /></div>
    </details>
  </div>;
}
