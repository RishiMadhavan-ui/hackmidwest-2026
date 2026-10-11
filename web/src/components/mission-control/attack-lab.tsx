"use client";

import Link from "next/link";
import { LabScenarios } from "@/components/lab-scenarios";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { TOKEN_STORAGE_KEY } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { createLabWorkspace, labAccess, labControl, type LabAccess } from "@/lib/attack-lab";

const linkBtn = cn(
  "mt-3 inline-flex h-7 items-center justify-center rounded-lg border px-2.5 text-[0.8rem] font-medium transition-colors",
);

/**
 * Disabled placeholder only. Runtime attacks remain blocked by the web/store
 * server routes until verified operator authorization and isolation exist.
 */
export function AttackLab() {
  const { user } = useAuth();
  const [storedAccess, setAccess] = useState<LabAccess | null>(null);
  const [accessActor, setAccessActor] = useState<string | null>(null);
  const actorRef = useRef(user?.id);
  const [view, setView] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { actorRef.current = user?.id; }, [user?.id]);
  const access = accessActor === user?.id ? storedAccess : null;
  useEffect(() => {
    let active = true;
    labAccess().then((state) => { if (active) { setAccess(state); setAccessActor(user?.id ?? null); } })
      .catch(() => { if (active) { setAccess(null); setView(null); } });
    return () => { active = false; };
  }, [user?.id]);

  async function change(enabled?: boolean) {
    const owner = actorRef.current;
    setBusy(true);
    setError(null);
    setView(null);
    try {
      const next = access?.namespace && enabled !== undefined
        ? await labControl(access.namespace.id, enabled, access.namespace.revision)
        : await createLabWorkspace();
      if (owner === actorRef.current) setAccess(next);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Operator control unavailable");
      try { const next = await labAccess(); if (owner === actorRef.current) setAccess(next); }
      catch { if (owner === actorRef.current) setAccess(null); }
    } finally { setBusy(false); }
  }

  async function openView() {
    const owner = actorRef.current;
    setBusy(true);
    setError(null);
    try {
      const token = localStorage.getItem(TOKEN_STORAGE_KEY);
      if (!token) throw new Error("Sign in again to verify operator access");
      const response = await fetch("/attack-lab/operator-view", {
        headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
      });
      if (!response.ok) { setView(null); throw new Error("Operator access unavailable"); }
      const html = await response.text();
      if (owner === actorRef.current) setView(html);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Operator view unavailable");
    } finally { setBusy(false); }
  }

  return (
    <section id="attack-lab" className="flex flex-col gap-3">
      <header>
        <h2 className="text-base font-semibold tracking-tight">Attack Lab</h2>
        <p className="text-xs text-muted-foreground">
          Verified operators can run bounded scenarios in separate demo identities.
          Clean browsing remains available to ordinary users.
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
            {access?.execution_available ? "Use the isolated scenario controls below" : "Attack scenarios disabled"}
          </p>
        </div>
      </div>

      <p className="text-[11px] text-muted-foreground">
        Listing toggle is not a payment outcome. Blocked/approved results come
        only from trusted checkout verification and the rail.
      </p>
      {access && <div className="rounded-lg border border-border p-3">
        <p className="text-sm font-medium">Operator access verified</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Server controls {access.server_enabled ? "enabled" : "disabled"}.
          Workspace controls {access.namespace?.enabled ? "enabled" : "disabled"}.
          Scenario execution {access.execution_available ? "available in this isolated workspace" : "awaiting enabled workspace and server configuration"}.
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          {!access.namespace && <button className={linkBtn} disabled={busy || !access.server_enabled}
            onClick={() => void change()}>Create isolated workspace</button>}
          {access.namespace && <button className={linkBtn}
            disabled={busy || (!access.namespace.enabled && !access.server_enabled)}
            onClick={() => void change(!access.namespace?.enabled)}>
            {access.namespace.enabled ? "Disable workspace controls" : "Enable workspace controls"}
          </button>}
          <button className={linkBtn} disabled={busy} onClick={() => void openView()}>Open verified operator view</button>
        </div>
        {view && <iframe title="Server-verified operator view" sandbox="" srcDoc={view}
          className="mt-3 h-64 w-full rounded border bg-white text-black" />}
        {access.namespace && <LabScenarios key={access.namespace.id} namespaceId={access.namespace.id}
          enabled={access.execution_available} onReset={() => { void labAccess().then(setAccess); }} />}
      </div>}
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
    </section>
  );
}
