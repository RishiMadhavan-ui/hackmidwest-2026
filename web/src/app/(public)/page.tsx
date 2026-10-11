"use client";

import Link from "next/link";
import { Check, X } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";

const POINTS = [
  {
    title: "You confirm the intent",
    body: "Your agent can draft a mandate. Only you can confirm it, and you see every term before you do: category, total, quantity, subscriptions, expiry.",
  },
  {
    title: "Checkout is verified independently",
    body: "Leash pulls the checkout from the merchant, not from the agent, and checks each fact in code. A model can recommend a block. It can never approve.",
  },
  {
    title: "You keep the kill switch",
    body: "One control revokes every mandate and invalidates unused grants on the payment rail. Agents have no route to it.",
  },
];

function ExampleRow({
  label,
  expected,
  actual,
  ok,
}: {
  label: string;
  expected: string;
  actual: string;
  ok: boolean;
}) {
  return (
    <tr>
      <td className="py-2 pr-3 text-muted-foreground">{label}</td>
      <td className="py-2 pr-3">{expected}</td>
      <td className="py-2 text-right">
        <span className={ok ? "inline-flex items-center gap-1 text-success" : "inline-flex items-center gap-1 font-medium text-danger"}>
          {ok ? <Check className="size-4" aria-hidden /> : <X className="size-4" aria-hidden />}
          {actual}
        </span>
      </td>
    </tr>
  );
}

export default function Home() {
  const { user } = useAuth();
  return (
    <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
      <section className="grid grid-cols-1 gap-12 py-16 lg:grid-cols-[minmax(0,1fr)_minmax(0,28rem)] lg:items-center lg:py-24">
        <div>
          <p className="text-sm font-medium text-primary">Intent-aware payment authorization</p>
          <h1 className="mt-3 max-w-xl text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
            The firewall between what you tell your AI to buy and what it tries to purchase.
          </h1>
          <p className="mt-5 max-w-lg text-base text-muted-foreground text-pretty">
            A checkout can match the merchant, the amount and the currency and still be the
            wrong thing. Leash compares every attempt against the purchase you confirmed and
            blocks it before any money moves.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            {user ? (
              <Link href="/overview" className={buttonVariants({ size: "lg" })}>
                Open Mission Control
              </Link>
            ) : (
              <>
                <Link href="/signup" className={buttonVariants({ size: "lg" })}>
                  Create account
                </Link>
                <Link href="/signin" className={buttonVariants({ size: "lg", variant: "outline" })}>
                  Sign in
                </Link>
              </>
            )}
          </div>
        </div>

        <figure className="rounded-lg border border-border bg-card">
          <figcaption className="flex items-center justify-between border-b border-border px-5 py-3">
            <span className="text-sm font-semibold">Example</span>
            <span className="text-xs text-muted-foreground">Illustration, not live data</span>
          </figcaption>
          <div className="px-5 py-4">
            <p className="text-xs text-muted-foreground">You confirmed</p>
            <p className="mt-1 text-sm font-medium">
              “Buy a USB-C laptop charger for under $40. No subscriptions.”
            </p>
            <p className="mt-4 text-xs text-muted-foreground">Agent attempted</p>
            <p className="mt-1 text-sm font-medium">
              Protection plan · $29.99 / month · same merchant
            </p>
            <table className="mt-4 w-full text-sm">
              <tbody className="divide-y divide-border">
                <ExampleRow label="Merchant" expected="Any" actual="Pass" ok />
                <ExampleRow label="Total" expected="≤ $39.99" actual="Pass" ok />
                <ExampleRow label="Category" expected="Laptop charger" actual="Mismatch" ok={false} />
                <ExampleRow label="Subscription" expected="Not allowed" actual="Monthly" ok={false} />
              </tbody>
            </table>
          </div>
          <div className="border-t border-border bg-danger-soft px-5 py-3 text-sm font-medium text-danger">
            Blocked before payment
          </div>
        </figure>
      </section>

      <section className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-3">
        {POINTS.map((point, i) => (
          <div key={point.title} className="bg-card p-6">
            <p className="font-mono text-xs text-muted-foreground">0{i + 1}</p>
            <h2 className="mt-2 text-base font-semibold">{point.title}</h2>
            <p className="mt-2 text-sm text-muted-foreground text-pretty">{point.body}</p>
          </div>
        ))}
      </section>
      <div className="h-16" />
    </div>
  );
}
