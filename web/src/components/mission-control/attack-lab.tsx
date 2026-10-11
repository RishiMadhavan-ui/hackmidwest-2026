"use client";

import Link from "next/link";

import { cn } from "@/lib/utils";

const linkBtn = cn(
  "mt-3 inline-flex h-7 items-center justify-center rounded-lg border px-2.5 text-[0.8rem] font-medium transition-colors",
);

/**
 * Disabled placeholder only. Runtime attacks remain blocked by the web/store
 * server routes until verified operator authorization and isolation exist.
 */
export function AttackLab() {
  return (
    <section className="flex flex-col gap-3">
      <header>
        <h2 className="text-base font-semibold tracking-tight">Attack Lab</h2>
        <p className="text-xs text-muted-foreground">
          Attack execution is disabled pending server-verified operator access
          and isolated demo scenarios. Clean browsing remains available.
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
            Unavailable until the backend authorization and isolation checks
            pass. Ordinary sign-in does not authorize attack execution.
          </p>
          <p className="mt-3 text-xs font-medium text-muted-foreground">
            Attack scenarios disabled
          </p>
        </div>
      </div>

      <p className="text-[11px] text-muted-foreground">
        Listing toggle is not a payment outcome. Blocked/approved results come
        only from trusted checkout verification and the rail.
      </p>
    </section>
  );
}
