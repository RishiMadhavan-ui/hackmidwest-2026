"use client";

import { useEffect, useMemo, useState } from "react";
import { Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  ApiError,
  formatUsdFromCents,
} from "@/lib/api";
import {
  DEMO_CHARGER_PROPOSAL,
  approveMandate,
  centsToDollarsInput,
  dollarsToCents,
  draftMandate,
  listMandates,
  mandateToProposal,
  replaceMandate,
  revokeMandate,
  summarizeMandate,
  type MandateProposal,
  type PurchaseMandate,
} from "@/lib/mandates";
import { cn } from "@/lib/utils";

const fieldClass =
  "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

function statusTone(status: string): string {
  if (status === "active") return "bg-emerald-500/15 text-emerald-800 dark:text-emerald-300";
  if (status === "proposed") return "bg-amber-500/15 text-amber-900 dark:text-amber-200";
  if (status === "revoked" || status === "expired") {
    return "bg-destructive/10 text-destructive";
  }
  return "bg-muted text-muted-foreground";
}

function sortMandates(items: PurchaseMandate[]): PurchaseMandate[] {
  const rank = (s: string) =>
    s === "active" ? 0 : s === "proposed" ? 1 : s === "superseded" ? 3 : 2;
  return [...items].sort((a, b) => {
    const byStatus = rank(a.status) - rank(b.status);
    if (byStatus !== 0) return byStatus;
    return b.created_at.localeCompare(a.created_at);
  });
}

function blankProposal(): MandateProposal {
  return {
    description: "",
    category: "laptop_charger",
    max_cents: 3999,
    currency: "USD",
    product_constraints: [],
    max_quantity: 1,
    maximum_purchases: 1,
    allow_subscription: false,
    allow_recurring: false,
    merchant_allowlist: ["mer_volt_supply"],
  };
}

export function AuthorityPanel({
  onMandateChange,
}: {
  onMandateChange?: (mandate: PurchaseMandate | null) => void;
}) {
  const [mandates, setMandates] = useState<PurchaseMandate[]>([]);
  /** null = composing a new mandate */
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<MandateProposal>(blankProposal);
  const [maxDollars, setMaxDollars] = useState(
    centsToDollarsInput(blankProposal().max_cents),
  );
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selected = useMemo(
    () => (selectedId ? mandates.find((m) => m.id === selectedId) ?? null : null),
    [mandates, selectedId],
  );
  const composing = selectedId === null;

  const liveMandates = useMemo(
    () => mandates.filter((m) => m.status === "active" || m.status === "proposed"),
    [mandates],
  );
  const otherMandates = useMemo(
    () =>
      mandates.filter((m) => m.status !== "active" && m.status !== "proposed"),
    [mandates],
  );

  function applyProposalToForm(proposal: MandateProposal) {
    setDraft(proposal);
    setMaxDollars(centsToDollarsInput(proposal.max_cents));
  }

  function startNew() {
    setSelectedId(null);
    applyProposalToForm(blankProposal());
    setNotice(null);
    setError(null);
    onMandateChange?.(null);
  }

  function selectMandate(m: PurchaseMandate) {
    setSelectedId(m.id);
    applyProposalToForm(mandateToProposal(m));
    setNotice(null);
    setError(null);
    onMandateChange?.(m);
  }

  async function refreshList(options?: { quiet?: boolean }) {
    if (!options?.quiet) setLoading(true);
    setError(null);
    try {
      const res = await listMandates();
      const items = sortMandates(res.items);
      setMandates(items);
      if (selectedId) {
        const still = items.find((m) => m.id === selectedId) ?? null;
        if (still) {
          onMandateChange?.(still);
        } else {
          setSelectedId(null);
          onMandateChange?.(null);
        }
      }
      return items;
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not load mandates",
      );
      onMandateChange?.(null);
      return [];
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await listMandates();
        if (cancelled) return;
        setMandates(sortMandates(res.items));
        // Stay in compose mode on first load so Create is obvious.
        setSelectedId(null);
        applyProposalToForm(blankProposal());
        onMandateChange?.(null);
      } catch (err) {
        if (cancelled) return;
        setError(
          err instanceof ApiError ? err.message : "Could not load mandates",
        );
        onMandateChange?.(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [onMandateChange]);

  function updateDraft(patch: Partial<MandateProposal>) {
    setDraft((prev) => ({ ...prev, ...patch }));
    setNotice(null);
  }

  function buildProposal(): MandateProposal {
    return {
      ...draft,
      max_cents: dollarsToCents(maxDollars),
      currency: "USD",
    };
  }

  async function createDraft() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await draftMandate(buildProposal());
      setNotice("Draft created. Select it in the list to confirm, or create another.");
      await refreshList({ quiet: true });
      startNew();
      applyProposalToForm(blankProposal());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Draft failed");
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const active = await approveMandate(selected);
      setNotice("Mandate confirmed. Agents may shop under this authority.");
      await refreshList({ quiet: true });
      selectMandate(active);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Confirm failed");
    } finally {
      setBusy(false);
    }
  }

  async function applyReplacement() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await replaceMandate(selected, buildProposal());
      setNotice(
        "Saved as a new draft version. Confirm explicitly to activate.",
      );
      await refreshList({ quiet: true });
      selectMandate(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed");
    } finally {
      setBusy(false);
    }
  }

  async function revoke() {
    if (!selected) return;
    if (
      !window.confirm(
        "Revoke this mandate version? Unused grants should stop with Kill Switch separately.",
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await revokeMandate(selected);
      setNotice("Mandate revoked.");
      await refreshList({ quiet: true });
      startNew();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Revoke failed");
    } finally {
      setBusy(false);
    }
  }

  function MandateRow({ m }: { m: PurchaseMandate }) {
    const isSelected = selectedId === m.id;
    return (
      <li>
        <button
          type="button"
          onClick={() => selectMandate(m)}
          className={cn(
            "flex w-full flex-col gap-1 rounded-lg border px-3 py-2.5 text-left transition-colors",
            isSelected
              ? "border-foreground/25 bg-muted/50"
              : "border-border bg-background hover:bg-muted/30",
          )}
        >
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "rounded-md px-1.5 py-0.5 text-[11px] font-medium capitalize",
                statusTone(m.status),
              )}
            >
              {m.status}
            </span>
            <span className="text-[11px] text-muted-foreground">v{m.version}</span>
            <span className="truncate font-mono text-[11px] text-muted-foreground">
              {m.id}
            </span>
          </div>
          <p className="line-clamp-2 text-sm font-medium leading-snug">
            {m.description}
          </p>
          <p className="truncate text-[11px] text-muted-foreground">
            {summarizeMandate(m)}
          </p>
        </button>
      </li>
    );
  }

  return (
    <section className="flex flex-col gap-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold tracking-tight">Authority</h2>
          <p className="text-xs text-muted-foreground">
            Create drafts from your intent, confirm to activate, and switch
            between mandates in the list.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void refreshList()}
          disabled={loading || busy}
        >
          Refresh
        </Button>
      </header>

      <div className="grid gap-4 lg:grid-cols-[minmax(16rem,0.9fr)_minmax(0,1.35fr)]">
        <div className="flex flex-col gap-3 rounded-xl border border-border bg-background px-4 py-4 md:px-5">
          <div className="flex items-center justify-between gap-2">
            <div>
              <p className="text-sm font-semibold tracking-tight">Mandates</p>
              <p className="text-xs text-muted-foreground">
                Proposed and active first; select one to edit.
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              size="icon-sm"
              onClick={startNew}
              disabled={busy}
              aria-label="Create new mandate"
              title="New mandate"
            >
              <Plus />
            </Button>
          </div>

          {loading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : null}

          {!loading && mandates.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border bg-muted/30 px-3 py-4 text-sm text-muted-foreground">
              No mandates yet. Use the form to create your first draft.
            </div>
          ) : null}

          {liveMandates.length > 0 ? (
            <ul className="flex flex-col gap-2">
              {liveMandates.map((m) => (
                <MandateRow key={m.id} m={m} />
              ))}
            </ul>
          ) : null}

          {otherMandates.length > 0 ? (
            <div className="mt-1 flex flex-col gap-2">
              <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
                Inactive
              </p>
              <ul className="flex flex-col gap-2 opacity-80">
                {otherMandates.map((m) => (
                  <MandateRow key={m.id} m={m} />
                ))}
              </ul>
            </div>
          ) : null}
        </div>

        <div className="flex flex-col gap-3 rounded-xl border border-border bg-background px-4 py-4 md:px-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-sm font-semibold tracking-tight">
                {composing ? "New mandate" : "Selected mandate"}
              </p>
              <p className="text-xs text-muted-foreground">
                {composing
                  ? "Compose intent, then create a draft."
                  : "Confirm, revise, or revoke this mandate."}
              </p>
            </div>
            {selected ? (
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span
                  className={cn(
                    "rounded-md px-2 py-0.5 font-medium capitalize",
                    statusTone(selected.status),
                  )}
                >
                  {selected.status}
                </span>
                <span className="text-muted-foreground">v{selected.version}</span>
              </div>
            ) : (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => applyProposalToForm(DEMO_CHARGER_PROPOSAL)}
                disabled={busy}
              >
                Load demo charger
              </Button>
            )}
          </div>

          <div className="grid gap-3">
            <label className="grid gap-1.5">
              <span className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                Original instruction
              </span>
              <textarea
                className={cn(fieldClass, "min-h-20 resize-y")}
                value={draft.description}
                onChange={(e) => updateDraft({ description: e.target.value })}
              />
            </label>

            <div className="grid gap-3 sm:grid-cols-2">
              <label className="grid gap-1.5">
                <span className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                  Category
                </span>
                <input
                  className={fieldClass}
                  value={draft.category}
                  onChange={(e) => updateDraft({ category: e.target.value })}
                />
              </label>
              <label className="grid gap-1.5">
                <span className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                  Max total (USD)
                </span>
                <input
                  className={fieldClass}
                  inputMode="decimal"
                  value={maxDollars}
                  onChange={(e) => setMaxDollars(e.target.value)}
                />
                <span className="text-[11px] text-muted-foreground">
                  Stored as {formatUsdFromCents(dollarsToCents(maxDollars))} (
                  {dollarsToCents(maxDollars)} cents). “Under $40” → 3999.
                </span>
              </label>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <label className="grid gap-1.5">
                <span className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                  Max quantity
                </span>
                <input
                  className={fieldClass}
                  type="number"
                  min={1}
                  max={99}
                  value={draft.max_quantity ?? 1}
                  onChange={(e) =>
                    updateDraft({ max_quantity: Number(e.target.value) || 1 })
                  }
                />
              </label>
              <label className="grid gap-1.5">
                <span className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                  Max purchases
                </span>
                <input
                  className={fieldClass}
                  type="number"
                  min={1}
                  max={99}
                  value={draft.maximum_purchases ?? 1}
                  onChange={(e) =>
                    updateDraft({
                      maximum_purchases: Number(e.target.value) || 1,
                    })
                  }
                />
              </label>
            </div>

            <fieldset className="grid gap-2 rounded-lg border border-border px-3 py-3">
              <legend className="px-1 text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                Recurrence
              </legend>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={!!draft.allow_subscription}
                  onChange={(e) =>
                    updateDraft({ allow_subscription: e.target.checked })
                  }
                />
                Allow subscriptions
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={!!draft.allow_recurring}
                  onChange={(e) =>
                    updateDraft({ allow_recurring: e.target.checked })
                  }
                />
                Allow recurring charges
              </label>
            </fieldset>

            <label className="grid gap-1.5">
              <span className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                Merchant allowlist
              </span>
              <input
                className={fieldClass}
                value={(draft.merchant_allowlist ?? []).join(", ")}
                onChange={(e) => {
                  const parts = e.target.value
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean);
                  updateDraft({
                    merchant_allowlist: parts.length ? parts : null,
                  });
                }}
                placeholder="mer_volt_supply"
              />
            </label>

            <div className="rounded-lg border border-border bg-muted/20 px-3 py-3">
              <p className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                Product constraints
              </p>
              <ul className="mt-2 flex flex-col gap-1 text-sm">
                {(draft.product_constraints ?? []).length === 0 ? (
                  <li className="text-muted-foreground">None</li>
                ) : (
                  (draft.product_constraints ?? []).map((c, i) => (
                    <li key={`${c.name}-${i}`} className="font-mono text-xs">
                      {c.name} {c.operator ?? "equals"} {String(c.value)}
                    </li>
                  ))
                )}
              </ul>
              <p className="mt-2 text-[11px] text-muted-foreground">
                Demo charger defaults include USB-C + 65W minimum when you load
                them from New mandate.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            {composing ? (
              <Button
                type="button"
                onClick={() => void createDraft()}
                disabled={
                  busy || !draft.description.trim() || !draft.category.trim()
                }
              >
                {busy ? "Working…" : "Create draft"}
              </Button>
            ) : (
              <>
                <Button
                  type="button"
                  onClick={() => void confirm()}
                  disabled={
                    busy || !selected || selected.status !== "proposed"
                  }
                >
                  Confirm mandate
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => void applyReplacement()}
                  disabled={
                    busy ||
                    !selected ||
                    (selected.status !== "proposed" &&
                      selected.status !== "active")
                  }
                >
                  Save as new version
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void revoke()}
                  disabled={
                    busy ||
                    !selected ||
                    (selected.status !== "proposed" &&
                      selected.status !== "active")
                  }
                >
                  Revoke
                </Button>
              </>
            )}
          </div>
        </div>
      </div>

      {notice ? (
        <p className="text-xs text-emerald-700 dark:text-emerald-400" role="status">
          {notice}
        </p>
      ) : null}
      {error ? (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}
