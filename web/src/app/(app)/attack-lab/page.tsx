"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { cn } from "cn";

import { EventList } from "@/components/event-list";
import { EmptyState, ErrorNote, PageHeader, Panel, Section } from "@/components/page";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { useActivity } from "@/lib/activity";
import { deriveIncidents, isSuspiciousSource } from "@/lib/events";

const PRODUCT = "chg-65w";

type HiddenItem = { kind: string; text: string };

/** Content a browser never shows a person: comments, JSON-LD, hidden nodes. */
function hiddenContent(html: string): HiddenItem[] {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const items: HiddenItem[] = [];
  const walker = doc.createTreeWalker(doc, NodeFilter.SHOW_COMMENT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.textContent?.trim();
    if (text) items.push({ kind: "HTML comment", text });
  }
  doc.querySelectorAll('script[type="application/ld+json"]').forEach((el) => {
    const text = el.textContent?.trim();
    if (text) items.push({ kind: "Structured data (JSON-LD)", text });
  });
  doc.querySelectorAll("[hidden], [aria-hidden='true'], [style*='display:none'], [style*='display: none']").forEach((el) => {
    const text = el.textContent?.trim();
    if (text) items.push({ kind: "Hidden element", text });
  });
  return items;
}

async function fetchListing(evil: boolean): Promise<string> {
  const response = await fetch(`/store/products/${PRODUCT}?evil=${evil}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Listing unavailable (${response.status})`);
  return response.text();
}

function useHiddenDiff() {
  const [items, setItems] = useState<HiddenItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    Promise.all([fetchListing(false), fetchListing(true)])
      .then(([clean, poisoned]) => {
        if (!active) return;
        const baseline = new Set(hiddenContent(clean).map((i) => i.text));
        setItems(hiddenContent(poisoned).filter((i) => !baseline.has(i.text)));
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : "Listing unavailable");
      });
    return () => {
      active = false;
    };
  }, []);
  return { items, error };
}

export default function AttackLabPage() {
  const [evil, setEvil] = useState(true);
  const hidden = useHiddenDiff();
  const { events, status } = useActivity();
  const sources = useMemo(() => events.filter(isSuspiciousSource).reverse().slice(0, 8), [events]);
  const blocked = useMemo(
    () => deriveIncidents(events).filter((i) => i.sourceEvent.type === "payment.denied"),
    [events],
  );

  return (
    <>
      <PageHeader
        title="Attack Lab"
        description="See what your agent reads that you don't. The poisoned listing changes page content only; it never changes your mandate or how checkout is verified."
      />

      <Panel className="mb-8 p-5">
        <h2 className="text-sm font-semibold">The scenario</h2>
        <p className="mt-1.5 max-w-3xl text-sm text-muted-foreground text-pretty">
          You ask for a USB-C laptop charger under $40 with no subscriptions. The merchant&apos;s
          listing carries hidden instructions telling shopping agents to check out a monthly
          protection plan instead. Same merchant, same $29.99, same currency, so merchant and
          amount controls alone would let it through. Leash retrieves the checkout from the
          merchant and compares the actual item against your mandate.
        </p>
      </Panel>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        <Section
          title="What you see"
          description="The simulated merchant's listing, rendered with scripts disabled."
          actions={
            <div role="radiogroup" aria-label="Listing version" className="flex rounded-md border border-border p-0.5">
              {[
                { value: false, label: "Clean" },
                { value: true, label: "Poisoned" },
              ].map((option) => (
                <button
                  key={option.label}
                  role="radio"
                  aria-checked={evil === option.value}
                  onClick={() => setEvil(option.value)}
                  className={cn(
                    "h-7 cursor-pointer rounded px-2.5 text-xs transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/40",
                    evil === option.value ? "bg-secondary font-medium" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
          }
        >
          <Panel className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-border px-4 py-2 text-xs text-muted-foreground">
              <span>Simulated merchant · Volt Supply Co.</span>
              <Badge tone={evil ? "warning" : "neutral"}>{evil ? "Poisoned listing" : "Clean listing"}</Badge>
            </div>
            <iframe
              key={String(evil)}
              title={evil ? "Poisoned merchant listing" : "Clean merchant listing"}
              src={`/store/products/${PRODUCT}?evil=${evil}`}
              sandbox=""
              loading="lazy"
              className="block h-[26rem] w-full bg-white"
            />
          </Panel>
          <p className="text-xs text-muted-foreground">
            Apart from the simulator’s mode label, a person sees the same product page. The difference is in the page source.
          </p>
        </Section>

        <Section
          title="What your agent reads"
          description="Hidden content present only in the poisoned version. Shown as plain text; it is untrusted data and never instructs Leash."
        >
          <Panel className="min-h-[26rem]">
            {hidden.error ? (
              <div className="p-4"><ErrorNote>Could not load the listings: {hidden.error}</ErrorNote></div>
            ) : hidden.items === null ? (
              <p className="p-4 text-sm text-muted-foreground">Comparing listings…</p>
            ) : hidden.items.length ? (
              <ul className="divide-y divide-border">
                {hidden.items.map((item, i) => (
                  <li key={i} className="p-4">
                    <p className="text-xs font-medium text-warning">{item.kind}</p>
                    <pre className="mt-2 max-h-56 overflow-auto rounded-md bg-muted px-3 py-2 font-mono text-xs leading-relaxed whitespace-pre-wrap">
                      {item.text}
                    </pre>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="p-4">
                <EmptyState title="No hidden differences">
                  The store returned identical hidden content for both versions.
                </EmptyState>
              </div>
            )}
          </Panel>
        </Section>
      </div>

      <div className="mt-8 grid grid-cols-1 gap-8 lg:grid-cols-2">
        <Section
          title="Suspicious pages your agent fetched"
          description="Recorded by the agent's provenance hooks during real runs."
        >
          <Panel>
            {sources.length ? (
              <EventList events={sources} />
            ) : (
              <div className="p-4">
                <EmptyState title={status === "live" ? "None recorded yet" : "Loading history…"}>
                  {status === "live" ? "Pages with hidden instructions show up here after a run reads them." : null}
                </EmptyState>
              </div>
            )}
          </Panel>
        </Section>

        <Section
          title="Outcome"
          description="Checkouts that independent verification blocked before payment."
          actions={
            <Link href="/incidents" className={buttonVariants({ variant: "ghost", size: "sm" })}>
              All incidents
            </Link>
          }
        >
          <Panel className="p-5">
            <p className="text-3xl font-semibold tabular-nums">{status === "idle" ? "—" : blocked.length}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {blocked.length === 1 ? "checkout blocked" : "checkouts blocked"} by deterministic
              policy in your history.
            </p>
            {blocked[0] ? (
              <p className="mt-3 text-sm">
                Latest:{" "}
                <Link href="/incidents" className="font-medium underline-offset-2 hover:underline">
                  {blocked[0].title.toLowerCase()}
                </Link>
              </p>
            ) : null}
          </Panel>
        </Section>
      </div>
    </>
  );
}
