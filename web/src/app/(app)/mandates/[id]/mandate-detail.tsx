"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { ArrowLeft } from "lucide-react";

import { EventList } from "@/components/event-list";
import { useKillSwitch } from "@/components/kill-switch";
import {
  CheckoutComparison,
  MandateIdentity,
  MandateStatusBadge,
  MandateTerms,
} from "@/components/mandate";
import { EmptyState, ErrorNote, Mono, PageHeader, Panel, Section } from "@/components/page";
import { RunList } from "@/components/run-list";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  approveMandate,
  getMandate,
  getMandateVersions,
  revokeMandate,
  type Mandate,
} from "@/lib/api";
import { useActivity } from "@/lib/activity";
import { formatWhen, mandateIdOf, reasonsOf, shortId } from "@/lib/events";
import { errorMessage, useNow, useResource } from "@/lib/use-resource";

import { EditMandateForm } from "./edit-mandate-form";

function ConfirmPanel({ mandate, onDone }: { mandate: Mandate; onDone: (m: Mandate) => void }) {
  const { state } = useKillSwitch();
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const now = useNow(5_000);
  const expired = new Date(mandate.valid_until).getTime() <= now;
  const blocked = !!state?.on || expired;

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      onDone(await approveMandate(mandate));
    } catch (err) {
      setError(errorMessage(err, "Confirmation failed. Nothing was activated."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel className="border-primary/30 bg-accent/40 p-5">
      <h2 className="text-sm font-semibold">Confirm this mandate</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Your agent drafted the terms above. Confirming signs this exact version; any later change
        becomes a new version that needs your confirmation again.
      </p>
      <label className="mt-4 flex cursor-pointer items-start gap-3 text-sm">
        <input
          type="checkbox"
          className="mt-0.5 size-4 shrink-0 cursor-pointer accent-(--primary)"
          checked={checked}
          disabled={blocked}
          onChange={(e) => setChecked(e.target.checked)}
        />
        <span>
          I authorize purchases only within these terms: version {mandate.version}, hash{" "}
          <Mono className="text-xs">{mandate.canonical_payload_hash?.slice(0, 12)}…</Mono>
        </span>
      </label>
      {state?.on ? (
        <p className="mt-3 text-sm text-danger">Shopping is stopped on this account; mandates can no longer be confirmed.</p>
      ) : expired ? (
        <p className="mt-3 text-sm text-danger">This draft has expired. Ask your agent for a new one.</p>
      ) : null}
      {error ? <div className="mt-3"><ErrorNote>{error}</ErrorNote></div> : null}
      <Button className="mt-4" size="lg" disabled={!checked || busy || blocked} onClick={() => void confirm()}>
        {busy ? "Confirming…" : "Confirm mandate"}
      </Button>
    </Panel>
  );
}

function RevokeButton({
  mandate,
  onDone,
}: {
  mandate: Mandate;
  onDone: (m: Mandate) => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const draft = mandate.status === "proposed";

  async function revoke() {
    setBusy(true);
    setError(null);
    try {
      onDone(await revokeMandate(mandate));
      setOpen(false);
    } catch (err) {
      setError(errorMessage(err, "Revocation outcome unknown. Refresh and retry."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button variant={draft ? "outline" : "destructive"} onClick={() => setOpen(true)}>
        {draft ? "Decline draft" : "Revoke mandate"}
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{draft ? "Decline this draft?" : "Revoke this mandate?"}</DialogTitle>
          <DialogDescription>
            {draft
              ? "The draft is marked revoked and can never be confirmed."
              : "Purchases under this mandate stop being authorized. Payments already authorized are not reversed. To also invalidate grants already on the payment rail, use the Kill Switch."}
          </DialogDescription>
        </DialogHeader>
        {error ? <ErrorNote>{error}</ErrorNote> : null}
        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
          <Button variant="danger" onClick={() => void revoke()} disabled={busy}>
            {busy ? "Revoking…" : draft ? "Decline" : "Revoke"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function MandateDetail() {
  const params = useParams<{ id: string }>();
  const id = decodeURIComponent(params.id);
  const mandate = useResource(() => getMandate(id), `mandate:${id}`);
  const versions = useResource(() => getMandateVersions(id), `versions:${id}`);
  const { events } = useActivity();
  const [editing, setEditing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const related = useMemo(
    () => events.filter((e) => mandateIdOf(e) === id).reverse(),
    [events, id],
  );
  const attempts = related.filter((e) => e.type === "payment.denied" || e.type === "payment.approved");
  const latestAttempt = attempts[0];

  function updated(next: Mandate, message: string) {
    mandate.setData(next);
    void versions.refresh();
    setNotice(message);
    setEditing(false);
  }

  const m = mandate.data;

  return (
    <>
      <Link
        href="/mandates"
        className="mb-4 inline-flex items-center gap-1.5 rounded-md text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/40"
      >
        <ArrowLeft className="size-4" aria-hidden /> Mandates
      </Link>

      {mandate.error ? <ErrorNote>Could not load mandate: {mandate.error}</ErrorNote> : null}
      {!m && mandate.loading ? <p className="py-8 text-sm text-muted-foreground">Loading mandate…</p> : null}

      {m ? (
        <>
          <PageHeader
            title={m.description}
            eyebrow={
              <span className="flex flex-wrap items-center gap-2">
                <MandateStatusBadge status={m.status} />
                <span className="tabular-nums">Version {m.version}</span>
              </span>
            }
            actions={
              m.status === "proposed" || m.status === "active" ? (
                <>
                  {!editing ? (
                    <Button variant="outline" onClick={() => setEditing(true)}>
                      Edit terms
                    </Button>
                  ) : null}
                  <RevokeButton
                    mandate={m}
                    onDone={(next) => updated(next, next.status === "revoked" ? "Mandate revoked." : "Updated.")}
                  />
                </>
              ) : null
            }
          />

          {notice ? (
            <p className="mb-6 rounded-lg bg-muted px-3 py-2 text-sm" role="status">
              {notice}
            </p>
          ) : null}

          <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
            <div className="flex flex-col gap-6">
              {editing ? (
                <EditMandateForm
                  mandate={m}
                  onCancel={() => setEditing(false)}
                  onSaved={(next) =>
                    updated(next, `Version ${next.version} drafted. Review the terms and confirm it to make it usable.`)
                  }
                />
              ) : (
                <Panel className="px-5 py-2">
                  <MandateTerms mandate={m} />
                </Panel>
              )}

              {m.status === "proposed" && !editing ? (
                <ConfirmPanel mandate={m} onDone={(next) => updated(next, "Mandate confirmed and signed.")} />
              ) : null}

              <Section
                title="Checkout checks"
                description="What independent verification found when your agent tried to pay under this mandate."
              >
                {latestAttempt ? (
                  <>
                    <CheckoutComparison mandate={m} reasons={reasonsOf(latestAttempt)} />
                    <p className="text-xs text-muted-foreground">
                      Latest attempt {formatWhen(latestAttempt.at)}
                      {typeof latestAttempt.data.checkout_id === "string"
                        ? ` · checkout ${latestAttempt.data.checkout_id}`
                        : ""}
                      {attempts.length > 1 ? ` · ${attempts.length} attempts in total` : ""}
                    </p>
                  </>
                ) : (
                  <EmptyState title="No payment attempts yet">
                    Checks run when your agent requests payment. Results are recorded here.
                  </EmptyState>
                )}
              </Section>

              <Section title="Activity for this mandate">
                <Panel>
                  {related.length ? (
                    <EventList events={related} />
                  ) : (
                    <div className="p-4">
                      <EmptyState title="No recorded events yet" />
                    </div>
                  )}
                </Panel>
              </Section>
            </div>

            <aside className="flex flex-col gap-6">
              <Section title="Identity">
                <Panel className="p-4">
                  <MandateIdentity mandate={m} />
                </Panel>
              </Section>

              <Section title="Versions" description="Confirmed versions are immutable.">
                <Panel>
                  {versions.data?.length ? (
                    <ol className="divide-y divide-border">
                      {[...versions.data].reverse().map((v) => (
                        <li key={v.version} className="flex items-center justify-between gap-3 px-4 py-3">
                          <div className="min-w-0">
                            <p className="text-sm font-medium tabular-nums">v{v.version}</p>
                            <p className="truncate text-xs text-muted-foreground">
                              {formatWhen(v.created_at)} ·{" "}
                              <Mono className="text-xs">{v.canonical_payload_hash?.slice(0, 10)}</Mono>
                            </p>
                          </div>
                          {v.version === m.version ? (
                            <MandateStatusBadge status={v.status} />
                          ) : (
                            <Badge tone="outline">{v.status === "superseded" ? "Replaced" : v.status}</Badge>
                          )}
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <p className="px-4 py-4 text-sm text-muted-foreground">
                      {versions.error ? `Could not load versions: ${versions.error}` : "Loading…"}
                    </p>
                  )}
                </Panel>
              </Section>

              <Section title="Runs under this mandate">
                <Panel>
                  <RunList mandateId={m.id} />
                </Panel>
              </Section>
            </aside>
          </div>
        </>
      ) : null}
      {m === null && !mandate.loading && !mandate.error ? (
        <EmptyState title="Mandate not found">
          <Mono>{shortId(id, 16)}</Mono>
        </EmptyState>
      ) : null}
    </>
  );
}
