"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { ActivityFeed } from "@/components/activity-feed";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  ApiError,
  fetchBalance,
  formatUsdFromCents,
  type Balance,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function ProfilePage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [balance, setBalance] = useState<Balance | null>(null);
  const [balanceError, setBalanceError] = useState<string | null>(null);
  const [balanceLoading, setBalanceLoading] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    if (!loading && !user) {
      router.replace("/signin");
    }
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    setBalanceLoading(true);
    setBalanceError(null);
    fetchBalance()
      .then((b) => {
        if (!cancelled) setBalance(b);
      })
      .catch((err) => {
        if (!cancelled) {
          setBalance(null);
          setBalanceError(
            err instanceof ApiError ? err.message : "Could not load balance",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setBalanceLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

  if (loading || !user) {
    return (
      <div className="flex flex-1 items-center justify-center px-4 py-16">
        <p className="text-sm text-muted-foreground">
          {loading ? "Loading profile…" : "Redirecting to sign in…"}
        </p>
      </div>
    );
  }

  const displayName = [user.first_name, user.last_name].filter(Boolean).join(" ");

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-8 px-4 py-10 md:py-14">
      <header className="flex flex-col gap-1 border-b border-border pb-6">
        <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Profile
        </p>
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
          {displayName || user.email}
        </h1>
        <p className="text-sm text-muted-foreground">
          Account details and a live stream of activity for this user
        </p>
      </header>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)] lg:items-start">
        <Card className="w-full">
          <CardHeader>
            <CardTitle>Account</CardTitle>
            <CardDescription>Your sandbox identity</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <dl className="grid gap-3 text-sm">
              {displayName ? (
                <div className="grid gap-1">
                  <dt className="text-muted-foreground">Name</dt>
                  <dd className="font-medium">{displayName}</dd>
                </div>
              ) : null}
              <div className="grid gap-1">
                <dt className="text-muted-foreground">Email</dt>
                <dd className="font-medium">{user.email}</dd>
              </div>
              {user.postal_code ? (
                <div className="grid gap-1">
                  <dt className="text-muted-foreground">ZIP / postal code</dt>
                  <dd className="font-medium">{user.postal_code}</dd>
                </div>
              ) : null}
              <div className="grid gap-1">
                <dt className="text-muted-foreground">User ID</dt>
                <dd className="break-all font-mono text-xs">{user.id}</dd>
              </div>
              <div className="grid gap-1 border-t border-border pt-3">
                <dt className="text-muted-foreground">
                  Card credit (Lithic sandbox)
                </dt>
                <dd className="font-medium">
                  {balanceLoading
                    ? "Loading…"
                    : balance
                      ? `${formatUsdFromCents(balance.available_cents)} remaining`
                      : "—"}
                </dd>
                {balance ? (
                  <dd className="text-xs text-muted-foreground">
                    Limit{" "}
                    {formatUsdFromCents(balance.limit_cents ?? balance.total_cents)}
                    {" · "}
                    Spent {formatUsdFromCents(balance.spent_cents ?? 0)}
                    {" · "}
                    Pending {formatUsdFromCents(balance.pending_cents)}
                    {balance.last_four || user.lithic_card_last_four
                      ? ` · ••${balance.last_four || user.lithic_card_last_four}`
                      : ""}
                    {" · "}
                    {balance.currency}
                  </dd>
                ) : null}
                {balanceError ? (
                  <dd className="text-xs text-destructive" role="alert">
                    {balanceError}
                  </dd>
                ) : null}
              </div>
            </dl>
            <Button
              type="button"
              variant="outline"
              disabled={signingOut}
              onClick={() => {
                setSigningOut(true);
                void logout().finally(() => {
                  router.push("/");
                });
              }}
            >
              {signingOut ? "Signing out…" : "Sign out"}
            </Button>
          </CardContent>
        </Card>

        <Card className="w-full min-h-[24rem]">
          <CardContent className="pt-6">
            <ActivityFeed />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
