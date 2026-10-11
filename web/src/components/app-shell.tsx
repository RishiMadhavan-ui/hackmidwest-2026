"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Suspense, useEffect, type ReactNode } from "react";
import { Menu } from "@base-ui/react/menu";
import { cn } from "cn";

import { KillSwitchButton, KillSwitchProvider, StoppedBanner } from "@/components/kill-switch";
import { Logo } from "@/components/logo";
import { Dot } from "@/components/ui/badge";
import { ActivityProvider, useActivity } from "@/lib/activity";
import { useAuth } from "@/lib/auth";

const NAV = [
  { href: "/overview", label: "Overview" },
  { href: "/mandates", label: "Mandates" },
  { href: "/activity", label: "Activity" },
  { href: "/incidents", label: "Incidents" },
  { href: "/payments", label: "Payments" },
  { href: "/attack-lab", label: "Attack Lab" },
] as const;

const linkClass =
  "flex h-9 shrink-0 items-center rounded-md px-3 text-sm whitespace-nowrap transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/40";

function NavLinks({ active }: { active: string | null }) {
  return (
    <>
      {NAV.map((item) => {
        const current = active !== null && (active === item.href || active.startsWith(`${item.href}/`));
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={current ? "page" : undefined}
            className={cn(
              linkClass,
              current
                ? "bg-secondary font-medium text-foreground"
                : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </>
  );
}

function ActiveNavLinks() {
  return <NavLinks active={usePathname()} />;
}

function Nav({ className }: { className?: string }) {
  return (
    <nav aria-label="Main" className={className}>
      {/* usePathname suspends on dynamic routes during prerender. */}
      <Suspense fallback={<NavLinks active={null} />}>
        <ActiveNavLinks />
      </Suspense>
    </nav>
  );
}

function StreamIndicator() {
  const { status } = useActivity();
  const tone = status === "live" ? "success" : status === "error" ? "danger" : "neutral";
  const text =
    status === "live" ? "Live" : status === "error" ? "Reconnecting" : "Connecting";
  return (
    <span
      className="hidden items-center gap-1.5 text-xs text-muted-foreground sm:flex"
      title="Persisted activity stream"
    >
      <Dot tone={tone} />
      {text}
    </span>
  );
}

const menuItemClass =
  "flex cursor-pointer items-center rounded-md px-2.5 py-2 text-sm outline-none select-none data-highlighted:bg-secondary";

function AccountMenu() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const initial = (user?.first_name?.[0] ?? user?.email?.[0] ?? "?").toUpperCase();
  return (
    <Menu.Root>
      <Menu.Trigger
        aria-label="Account menu"
        title={user?.email}
        className="flex size-9 cursor-pointer items-center justify-center rounded-full border border-border bg-card text-sm font-medium transition-colors outline-none hover:bg-secondary focus-visible:ring-3 focus-visible:ring-ring/40"
      >
        <span aria-hidden>{initial}</span>
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner sideOffset={6} align="end" className="outline-none">
          <Menu.Popup className="z-50 min-w-48 rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-md outline-none">
            <div className="px-2.5 py-2 text-xs text-muted-foreground">{user?.email}</div>
            <Menu.Item
              className={menuItemClass}
              onClick={() => router.push("/mission-control")}
            >
              Mission Control
            </Menu.Item>
            <Menu.Item className={menuItemClass} onClick={() => router.push("/profile")}>
              Account
            </Menu.Item>
            <Menu.Item
              className={menuItemClass}
              onClick={() => {
                void logout().finally(() => router.push("/"));
              }}
            >
              Sign out
            </Menu.Item>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/signin");
  }, [loading, user, router]);

  if (loading || !user) {
    return (
      <div className="flex flex-1 items-center justify-center px-4 py-24">
        <p className="text-sm text-muted-foreground">
          {loading ? "Checking your session…" : "Redirecting to sign in…"}
        </p>
      </div>
    );
  }

  return (
    <ActivityProvider>
      <KillSwitchProvider>
        <header className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur-sm">
          <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-4 sm:px-6">
            <Logo href="/overview" />
            <Nav className="hidden items-center gap-0.5 lg:flex" />
            <div className="ml-auto flex items-center gap-3">
              <StreamIndicator />
              <KillSwitchButton compact />
              <AccountMenu />
            </div>
          </div>
          <Nav className="no-scrollbar -mb-px flex gap-0.5 overflow-x-auto px-3 pb-2 lg:hidden" />
        </header>
        <StoppedBanner />
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6">{children}</main>
      </KillSwitchProvider>
    </ActivityProvider>
  );
}
