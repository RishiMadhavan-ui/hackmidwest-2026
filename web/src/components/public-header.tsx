"use client";

import Link from "next/link";

import { Logo } from "@/components/logo";
import { buttonVariants } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";

export function PublicHeader() {
  const { user, loading } = useAuth();
  return (
    <header className="border-b border-border">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <Logo />
        <nav className="flex items-center gap-2" aria-label="Account">
          {loading ? null : user ? (
            <Link href="/overview" className={buttonVariants({ size: "sm" })}>
              Open Mission Control
            </Link>
          ) : (
            <>
              <Link href="/signin" className={buttonVariants({ variant: "ghost", size: "sm" })}>
                Sign in
              </Link>
              <Link href="/signup" className={buttonVariants({ size: "sm" })}>
                Create account
              </Link>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
