"use client";

import { useEffect, useMemo, useState } from "react";

import { apiFetch, formatUsdFromCents, type ActivityEvent } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { PurchaseMandate } from "@/lib/mandates";
import { cn } from "@/lib/utils";
import { newestPaymentSignal } from "@/lib/activity-view";

type Row = {
  attribute: string;
  authorized: string;
  attempted: string;
  mismatch: boolean;
};

type Evidence = { attempt: { run_id: string; mandate_id: string; state: string;
  authorization_status: string; reason: string | null }; observation: { checkout: {
    total_cents: number; currency: string; merchant: { name: string; descriptor: string };
    items: { sku: string; product_name: string; recurring: boolean; subscription: boolean }[];
  } } | null };

function attemptedFromEvent(event: ActivityEvent | null): {
  item: string;
  amount: string;
  merchant: string;
  recurring: string;
  verdict: string;
  reasons: string;
} {
  if (!event) {
    return {
      item: "—",
      amount: "—",
      merchant: "—",
      recurring: "—",
      verdict: "Waiting for an attempt",
      reasons: "",
    };
  }
  const d = event.data;
  const reasons = Array.isArray(d.reasons)
    ? d.reasons.map(String).join(", ")
    : typeof d.reason === "string"
      ? d.reason
      : "";
  const amount =
    typeof d.amount_cents === "number"
      ? formatUsdFromCents(d.amount_cents)
      : typeof d.total_cents === "number"
        ? formatUsdFromCents(d.total_cents)
        : "—";
  const item =
    typeof d.sku === "string"
      ? d.sku
      : typeof d.product_category === "string"
        ? d.product_category
        : typeof d.checkout_id === "string"
          ? `checkout ${d.checkout_id}`
          : event.type;
  const merchant =
    typeof d.merchant_id === "string"
      ? d.merchant_id
      : typeof d.descriptor === "string"
        ? d.descriptor
        : "—";
  const recurring =
    d.subscription === true || d.recurring === true
      ? "Yes"
      : d.subscription === false || d.recurring === false
        ? "No"
        : "—";
  let verdict = event.type;
  if (event.type === "payment.approved") {
    verdict = "Checkout permitted; authorization pending";
  } else if (event.type === "checkout.verified") {
    verdict = "Checkout verified; authorization pending";
  } else if (
    event.type === "payment.denied" ||
    event.type === "checkout.blocked"
  ) {
    verdict = "BLOCKED";
  } else if (typeof d.result === "string") {
    verdict = String(d.result);
  } else if (typeof d.status === "string") {
    verdict = String(d.status);
  }
  return { item, amount, merchant, recurring, verdict, reasons };
}

export function ComparisonPanel({
  mandate,
  events,
  runId,
}: {
  mandate: PurchaseMandate | null;
  events: ActivityEvent[];
  runId?: string | null;
}) {
  const { user } = useAuth();
  const signal = useMemo(() => newestPaymentSignal(events, mandate?.id ?? null, runId), [events, mandate?.id, runId]);
  const operation = events.findLast((event) => event.type.startsWith("payment.operation.")
    && event.data.mandate_id === mandate?.id && event.data.run_id === runId);
  const paymentId = typeof operation?.data.payment_id === "string" ? operation.data.payment_id : null;
  const key = `${user?.id}:${mandate?.id}:${runId}:${paymentId}:${operation?.sequence}`;
  const [record, setRecord] = useState<{ key: string; evidence?: Evidence; error?: string } | null>(null);
  useEffect(() => {
    if (!paymentId || !runId || !mandate?.id) return;
    let active = true;
    apiFetch<Evidence>(`/purchase-attempts/${encodeURIComponent(paymentId)}`)
      .then((evidence) => { if (active && evidence.attempt.run_id === runId && evidence.attempt.mandate_id === mandate.id) setRecord({ key, evidence }); })
      .catch(() => { if (active) setRecord({ key, error: "Stored checkout evidence is unavailable; no authorization claimed." }); });
    return () => { active = false; };
  }, [key, paymentId, runId, mandate?.id]);
  const evidence = record?.key === key ? record.evidence : undefined;
  const checkout = evidence?.observation?.checkout;
  const attempted = useMemo(() => {
    const fallback = attemptedFromEvent(signal);
    if (!evidence) return fallback;
    return {
      item: checkout?.items.map((item) => `${item.product_name} (${item.sku})`).join(", ") ?? "No stored checkout",
      amount: checkout ? `${(checkout.total_cents / 100).toFixed(2)} ${checkout.currency}` : "—",
      merchant: checkout?.merchant.name ?? "—",
      recurring: checkout ? checkout.items.some((item) => item.subscription || item.recurring) ? "Yes" : "No" : "—",
      verdict: evidence.attempt.authorization_status === "authorized" ? "AUTHORIZED" : evidence.attempt.state === "blocked" ? "BLOCKED" : evidence.attempt.state.replace(/_/g, " "),
      reasons: evidence.attempt.reason ?? "",
    };
  }, [signal, evidence, checkout]);

  const rows: Row[] = useMemo(() => {
    const authorizedItem = mandate
      ? `${mandate.category.replace(/_/g, " ")}${
          mandate.product_constraints?.length
            ? ` (${mandate.product_constraints
                .map((c) => `${c.name}=${String(c.value)}`)
                .join(", ")})`
            : ""
        }`
      : "—";
    const authorizedAmount = mandate
      ? `Maximum ${formatUsdFromCents(mandate.max_cents)}`
      : "—";
    const authorizedMerchant = mandate?.merchant_allowlist?.length
      ? mandate.merchant_allowlist.join(", ")
      : mandate
        ? "Any (no allowlist)"
        : "—";
    const authorizedRecurring = mandate
      ? mandate.allow_subscription || mandate.allow_recurring
        ? "Allowed"
        : "No"
      : "—";

    return [
      {
        attribute: "Item / constraints",
        authorized: authorizedItem,
        attempted: attempted.item,
        mismatch:
          !!mandate &&
          !!signal &&
          (signal.type.includes("denied") || signal.type.includes("blocked")),
      },
      {
        attribute: "Amount",
        authorized: authorizedAmount,
        attempted: attempted.amount,
        mismatch: false,
      },
      {
        attribute: "Merchant",
        authorized: authorizedMerchant,
        attempted: attempted.merchant,
        mismatch: false,
      },
      {
        attribute: "Recurring / subscription",
        authorized: authorizedRecurring,
        attempted: attempted.recurring,
        mismatch:
          !!mandate &&
          !mandate.allow_subscription &&
          attempted.recurring === "Yes",
      },
      {
        attribute: "Verdict",
        authorized: mandate?.status === "active" ? "Authorized to shop" : "—",
        attempted: attempted.verdict,
        mismatch:
          attempted.verdict.includes("BLOCK") ||
          attempted.verdict.includes("DECLINED") ||
          attempted.verdict.includes("denied"),
      },
    ];
  }, [mandate, attempted, signal]);

  return (
    <section className="flex flex-col gap-3">
      <header>
        <h2 className="text-base font-semibold tracking-tight">
          Intent vs attempt
        </h2>
        <p className="text-xs text-muted-foreground">
          Side-by-side comparison from your confirmed mandate and the latest
          payment/checkout event for this mandate and run.
        </p>
      </header>

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full table-fixed text-left text-sm">
          <thead className="border-b border-border bg-muted/40 text-xs uppercase tracking-[0.1em] text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Attribute</th>
              <th className="px-3 py-2 font-medium">You authorized</th>
              <th className="px-3 py-2 font-medium">Agent attempted</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.attribute}
                className="border-b border-border last:border-b-0"
              >
                <td className="px-3 py-2.5 align-top font-medium text-muted-foreground">
                  {row.attribute}
                </td>
                <td className="break-words px-3 py-2.5 align-top">{row.authorized}</td>
                <td
                  className={cn(
                    "break-words px-3 py-2.5 align-top",
                    row.mismatch && "font-medium text-destructive",
                  )}
                >
                  {row.attempted}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {record?.key === key && record.error && <p role="alert" className="text-xs text-destructive">{record.error}</p>}

      {attempted.reasons ? (
        <p className="text-xs text-destructive" role="status">
          Reason: {attempted.reasons}
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          {signal
            ? `Latest signal: ${signal.type}`
            : "No payment or verification events yet — run the shopper against a checkout to populate this."}
        </p>
      )}
    </section>
  );
}
