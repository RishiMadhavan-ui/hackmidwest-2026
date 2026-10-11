"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

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
    <div className="flex flex-1 items-center justify-center px-4 py-16">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Profile</CardTitle>
          <CardDescription>Your account details</CardDescription>
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
                  Spent{" "}
                  {formatUsdFromCents(balance.spent_cents ?? 0)}
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
            onClick={() => {
              logout();
              router.push("/");
            }}
          >
            Sign out
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
