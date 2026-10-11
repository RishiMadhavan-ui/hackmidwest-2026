"use client";

import Link from "next/link";
import { useEffect, useState, useTransition } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { cn } from "@/lib/utils";

const linkBtn = cn(
  "mt-3 inline-flex h-7 items-center justify-center rounded-lg border px-2.5 text-[0.8rem] font-medium transition-colors",
);

type LabStatus = {
  execution: string;
  operator_authorized: boolean;
  can_run_attacks: boolean;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

/**
 * Operator status from the API. Public store ?evil=1 stays denied; only the
 * authenticated Attack Lab product route can serve poisoned listings.
 */
export function AttackLab() {
  const [status, setStatus] = useState<LabStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  useEffect(() => {
    let cancelled = false;
    startTransition(async () => {
      try {
        const data = await apiFetch<LabStatus>("/attack-lab/status");
        if (!cancelled) setStatus(data);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? err.message
              : "Could not reach Attack Lab status",
          );
        }
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const canAttack = Boolean(status?.can_run_attacks);

  function openAdversarialPreview() {
    setPreviewError(null);
    startTransition(async () => {
      try {
        const token =
          typeof window !== "undefined"
            ? localStorage.getItem("hmw_access_token")
            : null;
        const response = await fetch(`${API_URL}/attack-lab/products/chg-65w`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (response.status === 403) {
          setPreviewError(
            "Attack Lab execution requires an authorized demo operator",
          );
          return;
        }
        if (!response.ok) {
          setPreviewError(`Preview unavailable (${response.status})`);
          return;
        }
        const html = await response.text();
        const url = URL.createObjectURL(
          new Blob([html], { type: "text/html" }),
        );
        window.open(url, "_blank", "noopener,noreferrer");
      } catch {
        setPreviewError("Could not load adversarial preview");
      }
    });
  }

  return (
    <section className="flex flex-col gap-3">
      <header>
        <h2 className="text-base font-semibold tracking-tight">Attack Lab</h2>
        <p className="text-xs text-muted-foreground">
          Runtime attacks require a server-verified demo operator. Ordinary
          sign-in and public listing URLs cannot launch scenarios.
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
            {canAttack
              ? "Authorized operator preview via the Attack Lab API (not public ?evil=1)."
              : "Unavailable without operator allowlist membership. Authenticated non-operators receive 403."}
          </p>
          {canAttack ? (
            <button
              type="button"
              disabled={pending}
              onClick={openAdversarialPreview}
              className={cn(
                linkBtn,
                "border-border bg-background hover:bg-muted disabled:opacity-50",
              )}
            >
              Open adversarial preview
            </button>
          ) : (
            <p className="mt-3 text-xs font-medium text-muted-foreground">
              {error
                ? error
                : status?.operator_authorized
                  ? "Operator recognized; Attack Lab merchant credential not configured"
                  : "Attack scenarios disabled for this account"}
            </p>
          )}
          {previewError ? (
            <p className="mt-2 text-xs text-destructive">{previewError}</p>
          ) : null}
        </div>
      </div>

      <p className="text-[11px] text-muted-foreground">
        Listing toggle is not a payment outcome. Blocked/approved results come
        only from trusted checkout verification and the rail.
      </p>
    </section>
  );
}
