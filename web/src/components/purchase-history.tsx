"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Attempt = { id: string; run_id: string; mandate_id: string; mandate_version: number;
  checkout_id: string; state: string; reason: string | null; created_at: string };
type Evidence = { attempt: Attempt; mandate: { description: string; max_cents: number };
  evidence_status: string; observation: { source_hash: string; checkout: {
    total_cents: number; currency: string; items: { sku: string; product_name: string;
      quantity: number; recurring: boolean }[] } } | null };

export function PurchaseHistory({ revision = 0 }: { revision?: number }) {
  const { user } = useAuth();
  const [rows, setRows] = useState<Attempt[]>([]);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [cursor, setCursor] = useState<string | null>(null);
  const [actor, setActor] = useState<string | null>(null);
  const actorRef = useRef(user?.id);

  useEffect(() => { actorRef.current = user?.id; }, [user?.id]);

  useEffect(() => {
    let active = true;
    apiFetch<{ attempts: Attempt[]; next_cursor: string | null }>("/purchase-attempts")
      .then((result) => { if (active) {
        setRows(result.attempts); setCursor(result.next_cursor); setError(null);
        setEvidence(null); setActor(user?.id ?? null);
      } }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "History unavailable"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [user?.id, revision]);

  async function inspect(id: string) {
    const owner = actorRef.current;
    setError(null);
    try {
      const result = await apiFetch<Evidence>(`/purchase-attempts/${encodeURIComponent(id)}`);
      if (owner === actorRef.current) setEvidence(result);
    } catch (cause) { if (owner === actorRef.current) {
      setEvidence(null); setError(cause instanceof Error ? cause.message : "Evidence unavailable");
    } }
  }
  async function more() {
    if (!cursor) return;
    const owner = actorRef.current;
    try {
      const result = await apiFetch<{ attempts: Attempt[]; next_cursor: string | null }>(`/purchase-attempts?before=${encodeURIComponent(cursor)}`);
      if (owner !== actorRef.current) return;
      setRows((previous) => [...previous, ...result.attempts.filter((row) => !previous.some((old) => old.id === row.id))]);
      setCursor(result.next_cursor);
    } catch (cause) { if (owner === actorRef.current) setError(cause instanceof Error ? cause.message : "History unavailable"); }
  }
  const owned = actor === user?.id;
  return <section className="rounded-xl border border-border p-4">
    <h2 className="text-base font-semibold">Purchase attempts</h2>
    <p className="text-xs text-muted-foreground">Persisted checkout observations and decisions. These attempts have no verified payment execution.</p>
    {loading && <p className="mt-3 text-sm">Loading recorded attempts…</p>}
    {owned && rows.length === 0 && !loading && <p className="mt-3 text-sm text-muted-foreground">No recorded purchase attempts.</p>}
    {owned && rows.map((row) => <div key={row.id} className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t pt-3">
      <div><p className="text-sm">{row.state} · {row.checkout_id}</p>
        <p className="text-xs text-muted-foreground">{row.reason ?? "Decision pending"}</p></div>
      <button className="rounded border px-3 py-1 text-xs" onClick={() => void inspect(row.id)}>Inspect evidence</button>
    </div>)}
    {owned && cursor && <button className="mt-3 rounded border px-3 py-1 text-xs" onClick={() => void more()}>Load earlier attempts</button>}
    {owned && evidence && <div className="mt-4 rounded border bg-muted/20 p-3">
      <p className="text-sm font-medium">Original confirmed intent</p>
      <p className="mt-1 text-sm">{evidence.mandate.description}</p>
      <p className="mt-2 text-xs">Evidence: {evidence.evidence_status}. Merchant ownership and checkout freeze are unverified; no payment is authorized.</p>
      {evidence.observation ? <>
        <p className="mt-2 text-sm">Observed total: {(evidence.observation.checkout.total_cents / 100).toFixed(2)} {evidence.observation.checkout.currency}</p>
        {evidence.observation.checkout.items.map((item, index) => <p className="mt-1 text-sm" key={`${item.sku}-${index}`}>
          {item.product_name} · {item.sku} · quantity {item.quantity} · {item.recurring ? "recurring" : "not recurring"}
        </p>)}
        <p className="mt-2 break-all text-xs text-muted-foreground">Source hash: {evidence.observation.source_hash}</p>
      </> : <p className="mt-2 text-sm">No checkout observation was persisted for this attempt.</p>}
    </div>}
    {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
  </section>;
}
