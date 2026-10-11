import Link from "next/link";
import { Check, X } from "lucide-react";
import { cn } from "cn";

import { Mono } from "@/components/page";
import { Badge } from "@/components/ui/badge";
import { formatUsdFromCents, type Mandate, type MandateStatus, type ProductConstraint } from "@/lib/api";
import { formatRelative, formatWhen, reasonText, type Tone } from "@/lib/events";

const STATUS: Record<MandateStatus, { label: string; tone: Tone }> = {
  proposed: { label: "Awaiting confirmation", tone: "info" },
  active: { label: "Active", tone: "success" },
  revoked: { label: "Revoked", tone: "danger" },
  expired: { label: "Expired", tone: "neutral" },
  superseded: { label: "Replaced", tone: "neutral" },
};

export function MandateStatusBadge({ status }: { status: MandateStatus }) {
  const { label, tone } = STATUS[status];
  return <Badge tone={tone}>{label}</Badge>;
}

export function humanize(value: string): string {
  return value.replace(/_/g, " ");
}

export function constraintText(c: ProductConstraint): string {
  const value = typeof c.value === "boolean" ? (c.value ? "yes" : "no") : String(c.value);
  const name = humanize(c.name);
  switch (c.operator) {
    case "contains":
      return `${name} contains “${value}”`;
    case "minimum":
      return `${name} at least ${value}`;
    case "maximum":
      return `${name} at most ${value}`;
    default:
      return `${name}: ${value}`;
  }
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

/** The structured interpretation a human reviews before confirming. */
export function MandateTerms({ mandate }: { mandate: Mandate }) {
  const ship = mandate.shipping_constraints;
  const shipping = ship
    ? [
        ship.country,
        ship.postal_code,
        ship.deliver_by ? `by ${formatWhen(ship.deliver_by)}` : null,
        typeof ship.max_shipping_cents === "number"
          ? `shipping at most ${formatUsdFromCents(ship.max_shipping_cents)}`
          : null,
      ].filter(Boolean)
    : [];
  return (
    <dl className="divide-y divide-border">
      <Row label="Instruction">{mandate.description}</Row>
      <Row label="Category">{humanize(mandate.category)}</Row>
      <Row label="Maximum total">
        <span className="font-semibold tabular-nums">
          {formatUsdFromCents(mandate.max_cents)} {mandate.currency}
        </span>
        <span className="text-muted-foreground"> including required charges</span>
      </Row>
      <Row label="Product requirements">
        {mandate.product_constraints.length ? (
          <ul className="flex flex-col gap-0.5">
            {mandate.product_constraints.map((c) => (
              <li key={`${c.name}-${c.operator}-${String(c.value)}`}>{constraintText(c)}</li>
            ))}
          </ul>
        ) : (
          <span className="text-muted-foreground">None beyond the category</span>
        )}
      </Row>
      <Row label="Quantity">
        Up to {mandate.max_quantity} per purchase · {mandate.maximum_purchases} purchase
        {mandate.maximum_purchases === 1 ? "" : "s"} total
      </Row>
      <Row label="Subscriptions">
        <Allowed value={mandate.allow_subscription} />
      </Row>
      <Row label="Recurring charges">
        <Allowed value={mandate.allow_recurring} />
      </Row>
      <Row label="Merchants">
        {mandate.merchant_allowlist?.length
          ? mandate.merchant_allowlist.join(", ")
          : <span className="text-muted-foreground">Any merchant</span>}
      </Row>
      {shipping.length || mandate.location ? (
        <Row label="Shipping">
          {[mandate.location, ...shipping].filter(Boolean).join(" · ")}
        </Row>
      ) : null}
      <Row label="Valid">
        {formatWhen(mandate.valid_from)} – {formatWhen(mandate.valid_until)}
        <span className="text-muted-foreground"> ({expiryText(mandate)})</span>
      </Row>
    </dl>
  );
}

function Allowed({ value }: { value: boolean }) {
  return value ? (
    <span className="inline-flex items-center gap-1.5 text-warning">
      <Check className="size-4" aria-hidden /> Allowed
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5">
      <X className="size-4 text-danger" aria-hidden /> Not allowed
    </span>
  );
}

export function expiryText(mandate: Mandate, now = Date.now()): string {
  const end = new Date(mandate.valid_until).getTime();
  return end <= now ? `ended ${formatRelative(mandate.valid_until, now)}` : `ends ${formatRelative(mandate.valid_until, now)}`;
}

export function MandateIdentity({ mandate }: { mandate: Mandate }) {
  return (
    <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
      <div>
        <dt className="text-xs text-muted-foreground">Mandate</dt>
        <dd><Mono>{mandate.id}</Mono></dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Version</dt>
        <dd className="tabular-nums">v{mandate.version}</dd>
      </div>
      <div className="sm:col-span-2">
        <dt className="text-xs text-muted-foreground">Content hash (SHA-256)</dt>
        <dd><Mono>{mandate.canonical_payload_hash ?? "—"}</Mono></dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Drafted by agent</dt>
        <dd><Mono>{mandate.agent_id}</Mono></dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Confirmation</dt>
        <dd>
          {mandate.approved_at
            ? `${formatWhen(mandate.approved_at)} · signed with the server demo Ed25519 key`
            : "Not confirmed"}
        </dd>
      </div>
    </dl>
  );
}

export function MandateRow({ mandate }: { mandate: Mandate }) {
  return (
    <Link
      href={`/mandates/${encodeURIComponent(mandate.id)}`}
      className="group flex flex-col gap-2 px-4 py-3.5 transition-colors outline-none hover:bg-secondary/50 focus-visible:bg-secondary/60 sm:flex-row sm:items-center sm:gap-4"
    >
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{mandate.description}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {humanize(mandate.category)} · v{mandate.version} · {expiryText(mandate)}
        </p>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-sm font-medium tabular-nums">
          ≤ {formatUsdFromCents(mandate.max_cents)}
        </span>
        <MandateStatusBadge status={mandate.status} />
      </div>
    </Link>
  );
}

type Rule = { label: string; expected: string; codes: string[] };

function rulesFor(mandate: Mandate): Rule[] {
  return [
    { label: "Category", expected: humanize(mandate.category), codes: ["category_mismatch", "unknown_category"] },
    {
      label: "Product requirements",
      expected: mandate.product_constraints.length
        ? mandate.product_constraints.map(constraintText).join("; ")
        : "None beyond the category",
      codes: ["product_constraint_unmet", "product_attribute_unknown"],
    },
    { label: "Total", expected: `≤ ${formatUsdFromCents(mandate.max_cents)}`, codes: ["amount_over_limit"] },
    { label: "Currency", expected: mandate.currency, codes: ["currency_mismatch"] },
    { label: "Subscription", expected: mandate.allow_subscription ? "Allowed" : "Not allowed", codes: ["subscription_prohibited"] },
    { label: "Recurring charge", expected: mandate.allow_recurring ? "Allowed" : "Not allowed", codes: ["recurring_prohibited"] },
    { label: "Quantity", expected: `≤ ${mandate.max_quantity}`, codes: ["quantity_exceeded"] },
    {
      label: "Merchant",
      expected: mandate.merchant_allowlist?.length ? mandate.merchant_allowlist.join(", ") : "Any",
      codes: ["merchant_not_allowed"],
    },
    { label: "Purchases used", expected: `≤ ${mandate.maximum_purchases}`, codes: ["purchase_scope_exhausted"] },
  ];
}

/**
 * Intent vs. checkout, from the verifier's persisted reasons. Every check
 * runs on each attempt; a rule without a failure reason passed.
 */
export function CheckoutComparison({ mandate, reasons }: { mandate: Mandate; reasons: string[] }) {
  const failed = new Set(reasons);
  const rules = rulesFor(mandate);
  const known = new Set(rules.flatMap((r) => r.codes));
  const other = reasons.filter((r) => !known.has(r));
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">Rule</th>
            <th scope="col" className="px-3 py-2 font-medium">You confirmed</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Checkout</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rules.map((rule) => {
            const failure = rule.codes.find((code) => failed.has(code));
            return (
              <tr key={rule.label} className={cn(failure && "bg-danger-soft/60")}>
                <td className="px-3 py-2 align-top text-muted-foreground">{rule.label}</td>
                <td className="px-3 py-2 align-top">{rule.expected}</td>
                <td className="px-3 py-2 text-right align-top">
                  {failure ? (
                    <span className="inline-flex items-center gap-1 font-medium text-danger">
                      <X className="size-4" aria-hidden /> {reasonText(failure)}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-success">
                      <Check className="size-4" aria-hidden /> Pass
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {other.length ? (
        <p className="border-t border-border px-3 py-2 text-xs text-muted-foreground">
          Also: {other.map(reasonText).join("; ")}
        </p>
      ) : null}
    </div>
  );
}
