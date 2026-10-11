"use client";

import { type FormEvent, type ReactNode, useState } from "react";

import { constraintText } from "@/components/mandate";
import { ErrorNote, Panel } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Field, Input, Textarea, inputClassName } from "@/components/ui/field";
import type { MandateProposal, ProductConstraint, ShippingConstraints } from "@/lib/api";
import { errorMessage } from "@/lib/use-resource";

/** "39.99" -> 3999 without floating-point math; null when invalid. */
export function parseDollarsToCents(input: string): number | null {
  const match = /^\s*\$?(\d{1,7})(?:\.(\d{1,2}))?\s*$/.exec(input);
  if (!match) return null;
  const cents = (match[2] ?? "").padEnd(2, "0");
  return Number(match[1]) * 100 + Number(cents);
}

function centsToInput(cents: number): string {
  return `${Math.floor(cents / 100)}.${String(cents % 100).padStart(2, "0")}`;
}

const EXPIRY_OPTIONS = [
  { minutes: 30, label: "30 minutes" },
  { minutes: 60, label: "1 hour" },
  { minutes: 240, label: "4 hours" },
  { minutes: 1440, label: "24 hours" },
];

export type MandateFormValues = {
  description: string;
  category: string;
  max_cents: number;
  max_quantity: number;
  maximum_purchases: number;
  allow_subscription: boolean;
  allow_recurring: boolean;
  merchant_allowlist: string[] | null;
  product_constraints: ProductConstraint[];
  shipping_constraints: ShippingConstraints | null;
  location: string | null;
};

/**
 * Builds a full MandateProposal. Product requirements, shipping and location
 * are carried over from `initial`; this form doesn't edit them.
 */
export function MandateForm({
  initial,
  title,
  intro,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial: MandateFormValues;
  title: string;
  intro: ReactNode;
  submitLabel: string;
  onSubmit: (proposal: MandateProposal) => Promise<void>;
  onCancel?: () => void;
}) {
  const [description, setDescription] = useState(initial.description);
  const [category, setCategory] = useState(initial.category);
  const [maxTotal, setMaxTotal] = useState(centsToInput(initial.max_cents));
  const [maxQuantity, setMaxQuantity] = useState(String(initial.max_quantity));
  const [maxPurchases, setMaxPurchases] = useState(String(initial.maximum_purchases));
  const [allowSubscription, setAllowSubscription] = useState(initial.allow_subscription);
  const [allowRecurring, setAllowRecurring] = useState(initial.allow_recurring);
  const [merchants, setMerchants] = useState(initial.merchant_allowlist?.join(", ") ?? "");
  const [expiry, setExpiry] = useState("60");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const cents = parseDollarsToCents(maxTotal);
  const quantity = Number.parseInt(maxQuantity, 10);
  const purchases = Number.parseInt(maxPurchases, 10);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (cents === null) return setError("Enter the maximum total as dollars and cents, like 39.99.");
    if (!(quantity >= 1) || !(purchases >= 1)) return setError("Quantity and purchases must be at least 1.");
    const allowlist = merchants
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (new Set(allowlist).size !== allowlist.length) return setError("Merchant names must be unique.");

    const proposal: MandateProposal = {
      description: description.trim(),
      category: category.trim(),
      max_cents: cents,
      currency: "USD",
      location: initial.location,
      valid_from: null,
      valid_until: new Date(Date.now() + Number(expiry) * 60_000).toISOString(),
      product_constraints: initial.product_constraints,
      max_quantity: quantity,
      maximum_purchases: purchases,
      allow_subscription: allowSubscription,
      allow_recurring: allowRecurring,
      shipping_constraints: initial.shipping_constraints,
      merchant_allowlist: allowlist.length ? allowlist : null,
    };
    setBusy(true);
    setError(null);
    try {
      await onSubmit(proposal);
    } catch (err) {
      setError(errorMessage(err, "Could not save the mandate."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel className="p-5">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <div>
          <h2 className="text-sm font-semibold">{title}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{intro}</p>
        </div>
        <Field label="Instruction" htmlFor="description">
          <Textarea id="description" required value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Category" htmlFor="category" hint="As the merchant labels it, e.g. laptop_charger.">
            <Input id="category" required value={category} onChange={(e) => setCategory(e.target.value)} />
          </Field>
          <Field
            label="Maximum total (USD)"
            htmlFor="max-total"
            hint="Including tax, shipping and fees."
            error={maxTotal && cents === null ? "Use dollars and cents, like 39.99." : null}
          >
            <Input
              id="max-total"
              inputMode="decimal"
              required
              value={maxTotal}
              aria-invalid={!!maxTotal && cents === null}
              onChange={(e) => setMaxTotal(e.target.value)}
            />
          </Field>
          <Field label="Max quantity per purchase" htmlFor="max-quantity">
            <Input id="max-quantity" type="number" min={1} required value={maxQuantity} onChange={(e) => setMaxQuantity(e.target.value)} />
          </Field>
          <Field label="Number of purchases" htmlFor="max-purchases">
            <Input id="max-purchases" type="number" min={1} required value={maxPurchases} onChange={(e) => setMaxPurchases(e.target.value)} />
          </Field>
          <Field label="Allowed merchants" htmlFor="merchants" hint="Comma-separated. Leave empty for any merchant.">
            <Input id="merchants" value={merchants} onChange={(e) => setMerchants(e.target.value)} />
          </Field>
          <Field label="Expires in" htmlFor="expiry">
            <select id="expiry" className={inputClassName} value={expiry} onChange={(e) => setExpiry(e.target.value)}>
              {EXPIRY_OPTIONS.map((o) => (
                <option key={o.minutes} value={o.minutes}>
                  {o.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-sm font-medium">Billing</legend>
          <label className="flex cursor-pointer items-center gap-3 text-sm">
            <input type="checkbox" className="size-4 cursor-pointer accent-(--primary)" checked={allowSubscription} onChange={(e) => setAllowSubscription(e.target.checked)} />
            Allow subscriptions
          </label>
          <label className="flex cursor-pointer items-center gap-3 text-sm">
            <input type="checkbox" className="size-4 cursor-pointer accent-(--primary)" checked={allowRecurring} onChange={(e) => setAllowRecurring(e.target.checked)} />
            Allow recurring charges
          </label>
        </fieldset>
        {initial.product_constraints.length ? (
          <div className="text-sm">
            <p className="font-medium">Product requirements</p>
            <p className="mt-0.5 text-muted-foreground">
              {initial.product_constraints.map(constraintText).join("; ")}
            </p>
          </div>
        ) : null}
        {error ? <ErrorNote>{error}</ErrorNote> : null}
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={busy}>
            {busy ? "Saving…" : submitLabel}
          </Button>
          {onCancel ? (
            <Button type="button" variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
          ) : null}
        </div>
      </form>
    </Panel>
  );
}
