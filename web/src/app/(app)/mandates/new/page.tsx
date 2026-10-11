"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowLeft } from "lucide-react";

import { useKillSwitch } from "@/components/kill-switch";
import { MandateForm, type MandateFormValues } from "@/components/mandate-form";
import { ErrorNote, PageHeader } from "@/components/page";
import { Button } from "@/components/ui/button";
import { DEMO_CHARGER_PROPOSAL, draftMandate } from "@/lib/mandates";

const BLANK: MandateFormValues = {
  description: "",
  category: "",
  max_cents: 0,
  max_quantity: 1,
  maximum_purchases: 1,
  allow_subscription: false,
  allow_recurring: false,
  merchant_allowlist: null,
  product_constraints: [],
  shipping_constraints: null,
  location: null,
};

const DEMO: MandateFormValues = {
  ...BLANK,
  description: DEMO_CHARGER_PROPOSAL.description,
  category: DEMO_CHARGER_PROPOSAL.category,
  max_cents: DEMO_CHARGER_PROPOSAL.max_cents,
  max_quantity: DEMO_CHARGER_PROPOSAL.max_quantity ?? 1,
  maximum_purchases: DEMO_CHARGER_PROPOSAL.maximum_purchases ?? 1,
  merchant_allowlist: DEMO_CHARGER_PROPOSAL.merchant_allowlist ?? null,
  product_constraints: (DEMO_CHARGER_PROPOSAL.product_constraints ?? []).map((c) => ({
    ...c,
    operator: c.operator ?? "equals",
  })),
};

export default function NewMandatePage() {
  const router = useRouter();
  const { state } = useKillSwitch();
  const [preset, setPreset] = useState<{ key: number; values: MandateFormValues }>({ key: 0, values: BLANK });

  return (
    <>
      <Link
        href="/mandates"
        className="mb-4 inline-flex items-center gap-1.5 rounded-md text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/40"
      >
        <ArrowLeft className="size-4" aria-hidden /> Mandates
      </Link>
      <PageHeader
        title="New mandate"
        description="Write the purchase you want your agent to make. Saving creates a draft; nothing can be bought until you review and confirm it on the next page."
        actions={
          <Button variant="outline" onClick={() => setPreset((p) => ({ key: p.key + 1, values: DEMO }))}>
            Use the charger demo
          </Button>
        }
      />
      {state?.on ? (
        <ErrorNote>Shopping is stopped on this account, so new mandates can&apos;t be confirmed.</ErrorNote>
      ) : (
        <div className="max-w-3xl">
          <MandateForm
            key={preset.key}
            initial={preset.values}
            title="Terms"
            intro="Leash checks every checkout against these terms in code before any payment."
            submitLabel="Save draft"
            onSubmit={async (proposal) => {
              const draft = await draftMandate(proposal);
              router.push(`/mandates/${encodeURIComponent(draft.id)}`);
            }}
          />
        </div>
      )}
    </>
  );
}
