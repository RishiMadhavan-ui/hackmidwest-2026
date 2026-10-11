import type { ActivityEvent } from "@/lib/api";

export type ActivityScope = "run" | "today" | "all";

export function newestRunId(events: ActivityEvent[], mandateId?: string): string | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const event = events[i];
    if (event.type !== "agent.run_started" && event.type !== "execution.launched") continue;
    if (mandateId && event.data.mandate_id !== mandateId) continue;
    if (typeof event.data.run_id === "string") return event.data.run_id;
  }
  return null;
}

/** Display filtering only. Audit records, replay cursors and decisions stay intact. */
export function activityView(events: ActivityEvent[], options: {
  scope: ActivityScope; runId?: string | null; mandateId?: string | null;
  afterSequence?: number; now?: Date; paymentIds?: string[];
}): ActivityEvent[] {
  const now = options.now ?? new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  return events.filter((event) => {
    if (event.sequence <= (options.afterSequence ?? 0)) return false;
    // Some durable payment events predate run_id attribution. Only the
    // backend-owned attempt list may establish their link to the selected run.
    if (options.scope === "run") return !!options.runId && (event.data.run_id === options.runId
      || (!event.data.run_id && typeof event.data.payment_id === "string"
        && options.paymentIds?.includes(event.data.payment_id)))
      && (!options.mandateId || !event.data.mandate_id || event.data.mandate_id === options.mandateId);
    if (options.scope === "today") return new Date(event.at).getTime() >= today;
    return true;
  });
}

export function newestPaymentSignal(events: ActivityEvent[], mandateId: string | null, runId?: string | null) {
  if (!mandateId) return null;
  const scoped = events.filter((event) => (runId ? event.data.run_id === runId
    && (!event.data.mandate_id || event.data.mandate_id === mandateId)
    : event.data.mandate_id === mandateId));
  return scoped.findLast((event) => ["payment.denied", "payment.approved", "checkout.blocked",
    "checkout.verified", "authorization.decided"].includes(event.type)) ?? null;
}
