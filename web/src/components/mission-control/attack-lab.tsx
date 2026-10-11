"use client";

import Link from "next/link";

import { cn } from "@/lib/utils";

const linkBtn = cn(
  "mt-3 inline-flex h-7 items-center justify-center rounded-lg border px-2.5 text-[0.8rem] font-medium transition-colors",
);

/**
 * Attack Lab only changes listing content (evil HTML/JSON-LD). It never edits
 * mandates or fabricates payment outcomes — agents must browse the poisoned URL.
 */
export function AttackLab() {
  return (
    <section className="flex flex-col gap-3">
      <header>
        <h2 className="text-base font-semibold tracking-tight">Attack Lab</h2>
        <p className="text-xs text-muted-foreground">
          Toggle the Volt Supply listing the shopper will read. Canonical
          checkout facts stay honest either way.
        </p>
      </header>

      <div className="grid gap-2 sm:grid-cols-2">
        <div className="rounded-lg border border-border px-3 py-3">
          <p className="text-sm font-medium">Clean listing</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Charger page without injection. Use for the happy path.
          </p>
          <Link
            href="/store/products/chg-65w"
            target="_blank"
            className={cn(
              linkBtn,
              "border-border bg-background hover:bg-muted",
            )}
          >
            Open clean charger
          </Link>
        </div>
        <div className="rounded-lg border border-border px-3 py-3">
          <p className="text-sm font-medium">Adversarial listing</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Same page with JSON-LD / HTML comment steering toward VoltCare.
            Mandate stays unchanged.
          </p>
          <Link
            href="/store/products/chg-65w?evil=1"
            target="_blank"
            className={cn(
              linkBtn,
              "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
            )}
          >
            Open poisoned charger
          </Link>
        </div>
      </div>

      <p className="text-[11px] text-muted-foreground">
        Listing toggle is not a payment outcome. Blocked/approved results come
        only from trusted checkout verification and the rail.
      </p>
    </section>
  );
}
