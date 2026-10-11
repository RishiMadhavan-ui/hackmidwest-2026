"use client";

import { useEffect, useRef, useState } from "react";

import {
  formatUsdFromCents,
  streamActivity,
  type ActivityEvent,
} from "@/lib/api";

type StreamStatus = "connecting" | "live" | "error" | "idle";

const LABELS: Record<string, string> = {
  "account.created": "Account created",
  "account.login": "Signed in",
  "account.logout": "Signed out",
  "card.issued": "Virtual card issued",
  "mandate.proposed": "Mandate proposed",
  "mandate.approved": "Mandate confirmed",
  "mandate.updated": "Mandate updated",
  "mandate.revoked": "Mandate revoked",
  "mandate.expired": "Mandate expired",
  "agent.run_started": "Agent run started",
  "agent.run_completed": "Agent run completed",
  "agent.run_failed": "Agent run failed",
  "agent.step": "Agent step",
  "agent.tool.before": "Agent tool call",
  "agent.tool.after": "Agent tool result",
  "checkout.verified": "Checkout verified",
  "checkout.blocked": "Checkout blocked",
  "checkout.requires_review": "Checkout needs review",
  "payment.requested": "Payment requested",
  "guardian.verdict": "Guardian analysis",
  "payment.pending_user": "Payment pending approval",
  "payment.approved": "Payment approved",
  "payment.denied": "Payment blocked",
  "grant.issued": "Grant issued",
  "grant.consumed": "Grant consumed",
  "grant.expired": "Grant expired",
  "grant.revoked": "Grant revoked",
  "authorization.decided": "Authorization decided",
  "security.incident_recorded": "Security incident",
  "killswitch.changed": "Kill switch changed",
};

function labelFor(type: string): string {
  return LABELS[type] ?? type.replace(/\./g, " · ");
}

function toneFor(type: string): string {
  if (
    type.includes("denied") ||
    type.includes("blocked") ||
    type.includes("failed") ||
    type.includes("incident") ||
    type.includes("revoked")
  ) {
    return "text-destructive";
  }
  if (
    type.includes("approved") ||
    type.includes("verified") ||
    type.includes("created") ||
    type === "card.issued"
  ) {
    return "text-emerald-700 dark:text-emerald-400";
  }
  if (type.includes("guardian") || type.includes("review")) {
    return "text-amber-700 dark:text-amber-400";
  }
  return "text-foreground";
}

function summarize(event: ActivityEvent): string | null {
  const d = event.data;
  const parts: string[] = [];
  if (typeof d.last_four === "string" && d.last_four) {
    parts.push(`••${d.last_four}`);
  }
  if (typeof d.spend_limit_cents === "number") {
    parts.push(`limit ${formatUsdFromCents(d.spend_limit_cents)}`);
  }
  if (typeof d.card_type === "string") {
    parts.push(d.card_type.replace(/_/g, " ").toLowerCase());
  }
  if (typeof d.correlation_id === "string" && d.correlation_id) {
    parts.push(`corr ${d.correlation_id}`);
  }
  if (typeof d.mandate_id === "string") {
    parts.push(d.mandate_id);
  }
  if (typeof d.status === "string") {
    parts.push(String(d.status));
  }
  if (typeof d.provider === "string" && event.type.startsWith("account.")) {
    parts.push(d.provider);
  }
  if (typeof d.source === "string" && event.type === "card.issued") {
    parts.push(d.source);
  }
  return parts.length ? parts.join(" · ") : null;
}

function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function ActivityFeed() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const seen = useRef(new Set<string>());
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    seen.current = new Set();

    const stop = streamActivity({
      after: 0,
      onStatus: (next) => { setStatus(next); if (next === "live") setError(null); },
      onEvent: (event) => {
        if (seen.current.has(event.event_id)) return;
        seen.current.add(event.event_id);
        setEvents((prev) => {
          const next = [...prev, event];
          next.sort((a, b) => a.sequence - b.sequence);
          return next.slice(-500);
        });
      },
      onError: (err) => setError(err.message),
    });

    return stop;
  }, []);

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [events]);

  const newestFirst = [...events].reverse();

  return (
    <section className="flex min-h-[22rem] flex-col">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold tracking-tight">Activity</h2>
          <p className="text-xs text-muted-foreground">
            Live feed of account, card, and LEASH events for this profile
          </p>
        </div>
        <span
          className={
            status === "live"
              ? "text-xs font-medium text-emerald-700 dark:text-emerald-400"
              : status === "error"
                ? "text-xs font-medium text-destructive"
                : "text-xs text-muted-foreground"
          }
        >
          {status === "live"
            ? "Live"
            : status === "connecting"
              ? "Connecting…"
              : status === "error"
                ? "Reconnecting…"
                : ""}
        </span>
      </div>

      <div
        ref={listRef}
        className="flex-1 overflow-y-auto border-t border-border pt-2"
        role="log"
        aria-live="polite"
        aria-relevant="additions"
      >
        {newestFirst.length === 0 && status !== "error" ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            {status === "connecting"
              ? "Loading activity…"
              : "No recorded activity yet."}
          </p>
        ) : null}

        <ul className="flex flex-col gap-0">
          {newestFirst.map((event, index) => {
            const summary = summarize(event);
            const isNew = index === 0 && status === "live";
            return (
              <li
                key={event.event_id}
                className={
                  isNew
                    ? "animate-in fade-in slide-in-from-top-1 border-b border-border py-3 duration-300"
                    : "border-b border-border py-3 last:border-b-0"
                }
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className={`text-sm font-medium ${toneFor(event.type)}`}>
                      {labelFor(event.type)}
                    </p>
                    {summary ? (
                      <p className="mt-0.5 truncate text-xs text-muted-foreground">
                        {summary}
                      </p>
                    ) : null}
                  </div>
                  <time
                    dateTime={event.at}
                    className="shrink-0 text-xs tabular-nums text-muted-foreground"
                  >
                    {formatWhen(event.at)}
                  </time>
                </div>
              </li>
            );
          })}
        </ul>
      </div>

      {error ? (
        <p className="mt-2 text-xs text-destructive" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}
