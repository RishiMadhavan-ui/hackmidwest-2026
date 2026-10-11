"use client";

import { useState } from "react";
import { MandateForm, type MandateFormValues } from "@/components/mandate-form";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/field";
import { apiFetch, type MandateProposal } from "@/lib/api";
import { draftMandate, type PurchaseMandate } from "@/lib/mandates";

type Interpretation = { proposal: MandateProposal; source: string; assumptions: string[] };
const defaults: MandateFormValues = { description: "", category: "", max_cents: 0,
  max_quantity: 1, maximum_purchases: 1, allow_subscription: false, allow_recurring: false,
  merchant_allowlist: null, product_constraints: [], shipping_constraints: null, location: null };

export function NaturalMandate({ onDraft }: { onDraft: (mandate: PurchaseMandate) => void }) {
  const [instruction, setInstruction] = useState("");
  const [interpretation, setInterpretation] = useState<Interpretation | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generate() {
    setBusy(true); setError(null); setInterpretation(null);
    try {
      setInterpretation(await apiFetch<Interpretation>("/mandates/interpret", {
        method: "POST", body: JSON.stringify({ instruction }),
      }));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not interpret the instruction"); }
    finally { setBusy(false); }
  }

  if (interpretation || advanced) {
    const initial = { ...defaults, ...interpretation?.proposal, description: interpretation?.proposal.description ?? instruction };
    return <div className="space-y-3">
      {interpretation && <div className="rounded-lg border p-3 text-sm">
        <p className="font-medium">Generated draft terms — review before saving</p>
        {interpretation.assumptions.map((item) => <p className="mt-1 text-muted-foreground" key={item}>{item}</p>)}
        <p className="mt-2 text-xs text-muted-foreground">{interpretation.source === "model_proposed_interpretation" ? "Model interpretation" : "Supported instruction parser"} · no spending authority yet</p>
      </div>}
      <MandateForm initial={initial} title="Review the interpreted terms"
        intro="Save this draft, then explicitly confirm its exact terms. Saving does not start shopping."
        submitLabel="Save draft for confirmation"
        onCancel={() => { setInterpretation(null); setAdvanced(false); }}
        onSubmit={async (proposal) => { onDraft(await draftMandate(proposal)); }} />
    </div>;
  }
  return <form className="space-y-4 rounded-xl border p-5" onSubmit={(event) => { event.preventDefault(); void generate(); }}>
    <label className="block text-sm font-medium" htmlFor="purchase-instruction">What should your AI buy?</label>
    <Textarea id="purchase-instruction" required minLength={5} maxLength={4000}
      value={instruction} onChange={(event) => setInstruction(event.target.value)}
      placeholder="Buy me a USB-C laptop charger under $40. No subscriptions." />
    <p className="text-sm text-muted-foreground">Leash generates proposed limits from your instruction. You review and confirm them before your agent can shop.</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <div className="flex flex-wrap gap-2">
      <Button disabled={busy || !instruction.trim()}>{busy ? "Interpreting…" : "Generate draft terms"}</Button>
      <Button type="button" variant="outline" disabled={busy} onClick={() => setInstruction("Buy a USB-C laptop charger under $40. No subscriptions.")}>Use charger example</Button>
      <Button type="button" variant="ghost" disabled={busy} onClick={() => setAdvanced(true)}>Advanced form</Button>
    </div>
  </form>;
}
