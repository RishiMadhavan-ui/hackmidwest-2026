"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

/** Display dollars on the form; API receives integer cents. */
const DEFAULT_SPEND_LIMIT_DOLLARS = "500";
const MIN_SPEND_LIMIT_DOLLARS = 10;
const MAX_SPEND_LIMIT_DOLLARS = 100_000;

export default function SignupPage() {
  const { signup, user, loading } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [postalCode, setPostalCode] = useState("");
  const [spendLimitDollars, setSpendLimitDollars] = useState(DEFAULT_SPEND_LIMIT_DOLLARS);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!loading && user) {
      router.replace("/");
    }
  }, [loading, user, router]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    const dollars = Number(spendLimitDollars);
    if (
      !Number.isFinite(dollars) ||
      dollars < MIN_SPEND_LIMIT_DOLLARS ||
      dollars > MAX_SPEND_LIMIT_DOLLARS
    ) {
      setError(
        `Credit limit must be between $${MIN_SPEND_LIMIT_DOLLARS.toLocaleString("en-US")} and $${MAX_SPEND_LIMIT_DOLLARS.toLocaleString("en-US")}`,
      );
      return;
    }
    // Whole dollars only → exact cents (avoid float money math).
    const wholeDollars = Math.round(dollars);
    if (wholeDollars !== dollars) {
      setError("Credit limit must be a whole dollar amount");
      return;
    }
    const spend_limit_cents = wholeDollars * 100;

    setSubmitting(true);
    try {
      await signup({
        email,
        password,
        first_name: firstName,
        last_name: lastName,
        postal_code: postalCode,
        spend_limit_cents,
      });
      router.replace("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Signup failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center px-4 py-16">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Create account</CardTitle>
          <CardDescription>
            Sign up with email and password. Name, zip, and credit limit are used for
            Lithic sandbox card setup.
          </CardDescription>
        </CardHeader>
        <form onSubmit={onSubmit}>
          <CardContent className="flex flex-col gap-3">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1.5 text-sm">
                <span className="text-muted-foreground">First name</span>
                <input
                  type="text"
                  required
                  autoComplete="given-name"
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                  className="h-9 rounded-lg border border-border bg-background px-3 outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                />
              </label>
              <label className="flex flex-col gap-1.5 text-sm">
                <span className="text-muted-foreground">Last name</span>
                <input
                  type="text"
                  required
                  autoComplete="family-name"
                  value={lastName}
                  onChange={(e) => setLastName(e.target.value)}
                  className="h-9 rounded-lg border border-border bg-background px-3 outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                />
              </label>
            </div>
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="text-muted-foreground">Email</span>
              <input
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="h-9 rounded-lg border border-border bg-background px-3 outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              />
            </label>
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="text-muted-foreground">ZIP / postal code</span>
              <input
                type="text"
                required
                autoComplete="postal-code"
                minLength={3}
                maxLength={12}
                value={postalCode}
                onChange={(e) => setPostalCode(e.target.value)}
                className="h-9 rounded-lg border border-border bg-background px-3 outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              />
            </label>
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="text-muted-foreground">Password</span>
              <input
                type="password"
                required
                minLength={8}
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="h-9 rounded-lg border border-border bg-background px-3 outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              />
            </label>
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="text-muted-foreground">
                Card credit limit (USD)
              </span>
              <div className="relative">
                <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-muted-foreground">
                  $
                </span>
                <input
                  type="number"
                  required
                  inputMode="numeric"
                  min={MIN_SPEND_LIMIT_DOLLARS}
                  max={MAX_SPEND_LIMIT_DOLLARS}
                  step={1}
                  value={spendLimitDollars}
                  onChange={(e) => setSpendLimitDollars(e.target.value)}
                  className="h-9 w-full rounded-lg border border-border bg-background py-1 pr-3 pl-7 outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                />
              </div>
              <span className="text-xs text-muted-foreground">
                Forever spend limit on your Lithic sandbox virtual card ($
                {MIN_SPEND_LIMIT_DOLLARS.toLocaleString("en-US")}–$
                {MAX_SPEND_LIMIT_DOLLARS.toLocaleString("en-US")}
                ).
              </span>
            </label>
            {error ? (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            ) : null}
          </CardContent>
          <CardFooter className="flex flex-col items-stretch gap-3">
            <Button type="submit" disabled={submitting}>
              {submitting ? "Creating…" : "Sign up"}
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              Already have an account?{" "}
              <Link href="/signin" className="text-foreground underline-offset-4 hover:underline">
                Sign in
              </Link>
            </p>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
