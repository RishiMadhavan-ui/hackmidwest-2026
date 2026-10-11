"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Menu } from "@base-ui/react/menu";
import { UserRound } from "lucide-react";

import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

const triggerClassName = cn(
  "flex size-8 items-center justify-center rounded-full border border-border text-sm font-medium transition-colors",
  "bg-background text-foreground hover:bg-muted outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
);

const itemClassName = cn(
  "flex cursor-default items-center rounded-md px-2 py-1.5 text-sm outline-none select-none",
  "data-highlighted:bg-muted data-highlighted:text-foreground",
);

export function SiteNav() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const initial = user?.email?.[0]?.toUpperCase() ?? null;

  return (
    <header className="border-b border-border">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-4 px-4">
        <Link href="/" className="text-sm font-semibold tracking-tight">
          LEASH
        </Link>

        {loading ? (
          <span className={cn(triggerClassName, "opacity-50")} aria-hidden />
        ) : user ? (
          <Menu.Root>
            <Menu.Trigger
              className={triggerClassName}
              aria-label="Account menu"
              title={user.email}
            >
              <span aria-hidden>{initial}</span>
            </Menu.Trigger>
            <Menu.Portal>
              <Menu.Positioner className="outline-none" sideOffset={6} align="end">
                <Menu.Popup
                  className={cn(
                    "z-50 min-w-40 origin-(--transform-origin) rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-md outline-none",
                    "data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95",
                    "data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
                  )}
                >
                  <Menu.Item
                    className={itemClassName}
                    onClick={() => router.push("/mission-control")}
                  >
                    Mission Control
                  </Menu.Item>
                  <Menu.Item
                    className={itemClassName}
                    onClick={() => router.push("/profile")}
                  >
                    Profile
                  </Menu.Item>
                  <Menu.Item
                    className={itemClassName}
                    onClick={() => {
                      void logout().finally(() => {
                        router.push("/");
                      });
                    }}
                  >
                    Sign out
                  </Menu.Item>
                </Menu.Popup>
              </Menu.Positioner>
            </Menu.Portal>
          </Menu.Root>
        ) : (
          <Link
            href="/signin"
            aria-label="Sign in"
            title="Sign in"
            className={triggerClassName}
          >
            <UserRound className="size-4" aria-hidden />
          </Link>
        )}
      </div>
    </header>
  );
}
