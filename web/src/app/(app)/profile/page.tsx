"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { KillSwitchButton, isFullyEnforced, useKillSwitch } from "@/components/kill-switch";
import { Mono, PageHeader, Panel, Section } from "@/components/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fetchBalance, formatUsdFromCents } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useResource } from "@/lib/use-resource";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 px-5 py-3 sm:grid-cols-[10rem_minmax(0,1fr)] sm:gap-4">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

function LegacyHeadroom() {
  const balance = useResource(fetchBalance, "balance");
  const b = balance.data;
  return (
    <Section
      title="Legacy sandbox card"
      description="Limit headroom on an older Lithic sandbox card. It is not a balance of funds and grants no purchase authority."
    >
      <Panel className="p-5">
        {balance.loading && !b ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : b ? (
          <div className="flex flex-col gap-1">
            <p className="text-2xl font-semibold tabular-nums">
              {formatUsdFromCents(b.available_cents)}
              <span className="ml-2 text-sm font-normal text-muted-foreground">headroom</span>
            </p>
            <p className="text-xs text-muted-foreground">
              Limit {formatUsdFromCents(b.limit_cents ?? b.total_cents)} · Spent{" "}
              {formatUsdFromCents(b.spent_cents ?? 0)} · Pending {formatUsdFromCents(b.pending_cents)}
              {b.last_four ? ` · ••${b.last_four}` : ""} · {b.currency} · {b.provider.replace(/_/g, " ")}
            </p>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{balance.error ?? "Unavailable"}</p>
        )}
      </Panel>
    </Section>
  );
}

export default function ProfilePage() {
  const { user, logout } = useAuth();
  const { state } = useKillSwitch();
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);
  if (!user) return null;
  const name = [user.first_name, user.last_name].filter(Boolean).join(" ");

  return (
    <>
      <PageHeader
        title="Account"
        description="Your identity on Leash. Signing up creates no card and no spending authority."
        actions={
          <Button
            variant="outline"
            disabled={signingOut}
            onClick={() => {
              setSigningOut(true);
              void logout().finally(() => router.push("/"));
            }}
          >
            {signingOut ? "Signing out…" : "Sign out"}
          </Button>
        }
      />

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
        <div className="flex flex-col gap-8">
          <Section title="Details">
            <Panel>
              <dl className="divide-y divide-border">
                {name ? <Row label="Name">{name}</Row> : null}
                <Row label="Email">{user.email}</Row>
                {user.postal_code ? <Row label="ZIP / postal code">{user.postal_code}</Row> : null}
                <Row label="User ID"><Mono>{user.id}</Mono></Row>
              </dl>
            </Panel>
          </Section>
          {user.lithic_linked ? <LegacyHeadroom /> : null}
        </div>

        <Section title="Emergency stop">
          <Panel className="flex flex-col gap-3 p-5">
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm font-medium">Shopping</span>
              {state ? (
                state.on ? (
                  <Badge tone="danger">{isFullyEnforced(state) ? "Stopped" : "Stop pending"}</Badge>
                ) : (
                  <Badge tone="success">Allowed</Badge>
                )
              ) : (
                <Badge tone="outline">Unknown</Badge>
              )}
            </div>
            <p className="text-sm text-muted-foreground">
              Revokes every mandate and invalidates unused grants on the payment rail. Authorized
              payments are not reversed, and stopped authority can&apos;t be resumed.
            </p>
            {state?.on ? (
              <ul className="text-xs text-muted-foreground">
                <li>Rail enforcement: {state.rail_enforced ? "confirmed" : "pending"}</li>
                <li>Sandbox card closures: {state.provider_controls_enforced ? "confirmed" : "pending"}</li>
              </ul>
            ) : null}
            <div>
              <KillSwitchButton />
            </div>
          </Panel>
        </Section>
      </div>
    </>
  );
}
