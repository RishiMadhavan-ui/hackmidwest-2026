"use client";

import { Fragment, useMemo, useState } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "cn";

import { EmptyState, Mono, PageHeader, Panel } from "@/components/page";
import { PurchaseHistory } from "@/components/purchase-history";
import { Badge } from "@/components/ui/badge";
import { formatUsdFromCents } from "@/lib/api";
import { useActivity } from "@/lib/activity";
import { derivePayments, formatWhen, type PaymentRow } from "@/lib/events";

function Detail({ row }: { row: PaymentRow }) {
  const d = row.sourceEvent.data;
  const fields: [string, unknown][] = [
    ["Payment", d.payment_id],
    ["Checkout", d.checkout_id],
    ["Mandate", d.mandate_id],
    ["Verification", d.verification_id],
    ["Grant", d.grant_id],
    ["Rail event", d.event_id],
    ["MCC", d.mcc],
    ["Decided at", typeof d.decided_at === "string" ? formatWhen(d.decided_at) : null],
  ];
  return (
    <dl className="grid gap-x-6 gap-y-1.5 text-xs sm:grid-cols-2">
      {fields
        .filter(([, v]) => typeof v === "string" && v)
        .map(([label, value]) => (
          <div key={label} className="flex gap-2">
            <dt className="w-24 shrink-0 text-muted-foreground">{label}</dt>
            <dd><Mono className="text-xs">{String(value)}</Mono></dd>
          </div>
        ))}
    </dl>
  );
}

export default function PaymentsPage() {
  const { events, status } = useActivity();
  const rows = useMemo(() => derivePayments(events), [events]);
  const revision = events.filter((event) => event.type.startsWith("payment.")).at(-1)?.sequence ?? 0;
  const [open, setOpen] = useState<string | null>(null);

  return (
    <>
      <PageHeader
        title="Payments"
        description="Every payment request your agent made and every decision from the payment rail. An approved grant is permission, not a payment. An authorization is not settlement."
      />

      <div className="mb-8"><PurchaseHistory revision={revision} /></div>

      {rows.length ? (
        <Panel className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm">
            <thead className="border-b border-border text-left text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-medium">When</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Outcome</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Detail</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Decided by</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Amount</th>
                <th scope="col" className="w-8 px-2"><span className="sr-only">Expand</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((row) => {
                const expanded = open === row.id;
                return (
                  <Fragment key={row.id}>
                    <tr
                      className="cursor-pointer transition-colors hover:bg-secondary/40"
                      onClick={() => setOpen(expanded ? null : row.id)}
                    >
                      <td className="px-4 py-3 align-top text-xs whitespace-nowrap tabular-nums text-muted-foreground">
                        {formatWhen(row.at)}
                      </td>
                      <td className="px-4 py-3 align-top">
                        <Badge tone={row.tone}>{row.title}</Badge>
                      </td>
                      <td className="px-4 py-3 align-top">
                        <p>{row.detail ?? "—"}</p>
                        {row.rail ? <p className="mt-0.5 text-xs text-muted-foreground">{row.rail}</p> : null}
                      </td>
                      <td className="px-4 py-3 align-top text-xs text-muted-foreground">
                        {row.decisionSource ? row.decisionSource.replace(/_/g, " ") : "—"}
                        {row.provider ? <span className="block">{row.provider.replace(/_/g, " ")}</span> : null}
                      </td>
                      <td className="px-4 py-3 text-right align-top font-medium tabular-nums">
                        {row.amountCents !== null ? formatUsdFromCents(row.amountCents) : "—"}
                      </td>
                      <td className="px-2 py-3 align-top">
                        <button
                          type="button"
                          aria-expanded={expanded}
                          aria-label={expanded ? "Hide details" : "Show details"}
                          className="flex size-6 cursor-pointer items-center justify-center rounded outline-none focus-visible:ring-3 focus-visible:ring-ring/40"
                          onClick={(e) => {
                            e.stopPropagation();
                            setOpen(expanded ? null : row.id);
                          }}
                        >
                          <ChevronRight aria-hidden className={cn("size-4 text-muted-foreground transition-transform", expanded && "rotate-90")} />
                        </button>
                      </td>
                    </tr>
                    {expanded ? (
                      <tr className="bg-muted/40">
                        <td colSpan={6} className="px-4 py-3">
                          <Detail row={row} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </Panel>
      ) : (
        <EmptyState title={status === "live" ? "No payment activity yet" : "Loading history…"}>
          {status === "live"
            ? "When your agent requests payment, the verification result and any rail decision are recorded here."
            : null}
        </EmptyState>
      )}

      <p className="mt-4 text-xs text-muted-foreground">
        Rails are labeled as recorded: Local Payment Rail Simulator or Lithic sandbox. No live funds move.
      </p>
    </>
  );
}
