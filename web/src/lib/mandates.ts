import { apiFetch, formatUsdFromCents } from "@/lib/api";

export type MandateStatus =
  | "proposed"
  | "active"
  | "revoked"
  | "expired"
  | "superseded";

export type ProductConstraint = {
  name: string;
  operator?: "equals" | "contains" | "minimum" | "maximum";
  value: string | number | boolean;
};

export type MandateProposal = {
  description: string;
  category: string;
  max_cents: number;
  currency?: "USD";
  product_constraints?: ProductConstraint[];
  max_quantity?: number;
  maximum_purchases?: number;
  allow_subscription?: boolean;
  allow_recurring?: boolean;
  merchant_allowlist?: string[] | null;
  valid_until?: string | null;
  location?: string | null;
};

export type PurchaseMandate = {
  id: string;
  user_id: string;
  agent_id: string;
  description: string;
  category: string;
  max_cents: number;
  currency: string;
  product_constraints: ProductConstraint[];
  max_quantity: number;
  maximum_purchases: number;
  allow_subscription: boolean;
  allow_recurring: boolean;
  merchant_allowlist: string[] | null;
  valid_from: string;
  valid_until: string;
  version: number;
  created_at: string;
  status: MandateStatus;
  approved_at: string | null;
  signature: string | null;
  canonical_payload_hash: string | null;
  location?: string | null;
};

export type MandateList = {
  items: PurchaseMandate[];
};

/** Default charger demo intent — mirrors the signature mandate. */
export const DEMO_CHARGER_PROPOSAL: MandateProposal = {
  description: "Buy a USB-C laptop charger for under $40. No subscriptions.",
  category: "laptop_charger",
  max_cents: 3999,
  currency: "USD",
  product_constraints: [
    { name: "connector", operator: "equals", value: "USB-C" },
    { name: "wattage", operator: "minimum", value: 65 },
  ],
  max_quantity: 1,
  maximum_purchases: 1,
  allow_subscription: false,
  allow_recurring: false,
  merchant_allowlist: ["mer_volt_supply"],
};

export async function listMandates(
  status?: MandateStatus,
  token?: string | null,
) {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiFetch<MandateList>(`/mandates${qs}`, {}, token);
}

export async function getMandate(mandateId: string, token?: string | null) {
  return apiFetch<PurchaseMandate>(
    `/mandates/${encodeURIComponent(mandateId)}`,
    {},
    token,
  );
}

/** Human Mission Control draft — does not activate until approveMandate. */
export async function draftMandate(
  proposal: MandateProposal,
  token?: string | null,
) {
  return apiFetch<PurchaseMandate>(
    "/mandates/draft",
    {
      method: "POST",
      body: JSON.stringify(proposal),
    },
    token,
  );
}

export async function approveMandate(
  mandate: Pick<PurchaseMandate, "id" | "version" | "canonical_payload_hash">,
  token?: string | null,
) {
  if (!mandate.canonical_payload_hash) {
    throw new Error("Mandate is missing a payload hash");
  }
  return apiFetch<PurchaseMandate>(
    `/mandates/${encodeURIComponent(mandate.id)}/approve`,
    {
      method: "POST",
      body: JSON.stringify({
        version: mandate.version,
        canonical_payload_hash: mandate.canonical_payload_hash,
        confirmed: true,
      }),
    },
    token,
  );
}

export async function replaceMandate(
  mandate: Pick<PurchaseMandate, "id" | "version" | "canonical_payload_hash">,
  proposal: MandateProposal,
  token?: string | null,
) {
  if (!mandate.canonical_payload_hash) {
    throw new Error("Mandate is missing a payload hash");
  }
  return apiFetch<PurchaseMandate>(
    `/mandates/${encodeURIComponent(mandate.id)}`,
    {
      method: "PATCH",
      body: JSON.stringify({
        version: mandate.version,
        canonical_payload_hash: mandate.canonical_payload_hash,
        proposal,
      }),
    },
    token,
  );
}

export async function revokeMandate(
  mandate: Pick<PurchaseMandate, "id" | "version" | "canonical_payload_hash">,
  token?: string | null,
) {
  if (!mandate.canonical_payload_hash) {
    throw new Error("Mandate is missing a payload hash");
  }
  return apiFetch<PurchaseMandate>(
    `/mandates/${encodeURIComponent(mandate.id)}/revoke`,
    {
      method: "POST",
      body: JSON.stringify({
        version: mandate.version,
        canonical_payload_hash: mandate.canonical_payload_hash,
      }),
    },
    token,
  );
}

export function mandateToProposal(m: PurchaseMandate): MandateProposal {
  return {
    description: m.description,
    category: m.category,
    max_cents: m.max_cents,
    currency: "USD",
    product_constraints: m.product_constraints ?? [],
    max_quantity: m.max_quantity,
    maximum_purchases: m.maximum_purchases,
    allow_subscription: m.allow_subscription,
    allow_recurring: m.allow_recurring,
    merchant_allowlist: m.merchant_allowlist,
    location: m.location ?? null,
  };
}

export function dollarsToCents(dollars: string): number {
  const n = Number.parseFloat(dollars);
  if (!Number.isFinite(n) || n < 0) return 0;
  return Math.round(n * 100);
}

export function centsToDollarsInput(cents: number): string {
  return (cents / 100).toFixed(2);
}

export function summarizeMandate(m: PurchaseMandate): string {
  const bits = [
    m.category.replace(/_/g, " "),
    `max ${formatUsdFromCents(m.max_cents)}`,
    m.allow_subscription ? "subscriptions ok" : "no subscriptions",
    m.allow_recurring ? "recurring ok" : "no recurring",
    `qty ≤ ${m.max_quantity}`,
  ];
  return bits.join(" · ");
}
