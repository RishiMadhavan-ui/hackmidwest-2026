"use client";

import { useMemo } from "react";

import { formatUsdFromCents, type ActivityEvent } from "@/lib/api";
import type { PurchaseMandate } from "@/lib/mandates";
import { cn } from "@/lib/utils";

type Row = {
  attribute: string;
  authorized: string;
  attempted: string;
  mismatch: boolean;
};

function latestPaymentSignal(events: ActivityEvent[]): ActivityEvent | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const e = events[i];
    if (
      e.type === "payment.denied" ||
      e.type === "payment.approved" ||
      e.type === "checkout.blocked" ||
      e.type === "checkout.verified" ||
      e.type === "authorization.decided"
    ) {
      return e;
    }
  }
  return null;
}

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
  if (event.type === "payment.approved" || event.type === "checkout.verified") {
    verdict = "APPROVED / VERIFIED";
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
}: {
  mandate: PurchaseMandate | null;
  events: ActivityEvent[];
}) {
  const signal = useMemo(() => latestPaymentSignal(events), [events]);
  const attempted = useMemo(() => attemptedFromEvent(signal), [signal]);

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
      ? `Under ${formatUsdFromCents(mandate.max_cents + 1)} (max ${formatUsdFromCents(mandate.max_cents)})`
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
          payment/checkout activity event.
        </p>
      </header>

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[36rem] text-left text-sm">
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
                <td className="px-3 py-2.5 align-top">{row.authorized}</td>
                <td
                  className={cn(
                    "px-3 py-2.5 align-top",
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
