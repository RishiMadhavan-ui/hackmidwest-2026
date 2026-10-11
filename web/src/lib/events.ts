import { formatUsdFromCents, type ActivityEvent } from "@/lib/api";

export type Tone = "neutral" | "success" | "warning" | "danger" | "info";

export type EventGroup =
  | "account"
  | "mandate"
  | "agent"
  | "checkout"
  | "control";

const LABELS: Record<string, string> = {
  "account.created": "Account created",
  "account.login": "Signed in",
  "account.logout": "Signed out",
  "card.issued": "Sandbox card issued",
  "card.control.requested": "Card closure requested",
  "card.control.outcome": "Card closure outcome",
  "mandate.proposed": "Mandate drafted",
  "mandate.approved": "Mandate confirmed",
  "mandate.updated": "Mandate replaced",
  "mandate.revoked": "Mandate revoked",
  "mandate.expired": "Mandate expired",
  "agent.run_started": "Agent run started",
  "agent.run_completed": "Agent run completed",
  "agent.run_failed": "Agent run failed",
  "agent.step": "Agent step",
  "agent.tool.before": "Tool call",
  "agent.tool.after": "Tool result",
  "provenance.source": "Page fetched",
  "provenance.recorded": "Source recorded",
  "checkout.verified": "Checkout verified",
  "checkout.blocked": "Checkout blocked",
  "checkout.requires_review": "Checkout needs review",
  "payment.requested": "Payment requested",
  "guardian.verdict": "Guardian finding",
  "payment.pending_user": "Payment awaiting you",
  "payment.approved": "Grant approved",
  "payment.denied": "Payment blocked",
  "grant.issued": "Grant issued",
  "grant.consumed": "Grant consumed",
  "grant.expired": "Grant expired",
  "grant.revoked": "Grant revoked",
  "authorization.decided": "Rail decision",
  "security.incident_recorded": "Security incident",
  "killswitch.changed": "Kill switch",
  "run.stop.requested": "Run stop requested",
  "shopping.start.requested": "Shopping start requested",
};

export function labelFor(type: string): string {
  return LABELS[type] ?? type.replace(/[._]/g, " ");
}

export function groupFor(type: string): EventGroup {
  if (type.startsWith("mandate.")) return "mandate";
  if (
    type.startsWith("agent.") ||
    type.startsWith("provenance.") ||
    type.startsWith("run.") ||
    type.startsWith("shopping.")
  ) {
    return "agent";
  }
  if (type.startsWith("killswitch.") || type.startsWith("card.control.")) return "control";
  if (
    type.startsWith("checkout.") ||
    type.startsWith("payment.") ||
    type.startsWith("grant.") ||
    type.startsWith("guardian.") ||
    type === "authorization.decided" ||
    type === "security.incident_recorded"
  ) {
    return "checkout";
  }
  return "account";
}

export const GROUP_LABELS: Record<EventGroup, string> = {
  account: "Account",
  mandate: "Mandates",
  agent: "Agent",
  checkout: "Checkout & payment",
  control: "Controls",
};

/** Human wording for deterministic verifier reason codes. */
const REASONS: Record<string, string> = {
  category_mismatch: "Product category is not what you asked for",
  unknown_category: "Product category could not be established",
  product_constraint_unmet: "Product does not meet your requirements",
  product_attribute_unknown: "A required product attribute is unknown",
  quantity_exceeded: "Quantity is above your limit",
  purchase_scope_exhausted: "This mandate has already been used",
  merchant_not_allowed: "Merchant is not on your allowlist",
  amount_over_limit: "Total is over your limit",
  currency_mismatch: "Currency does not match",
  subscription_prohibited: "Subscriptions are not allowed",
  recurring_prohibited: "Recurring charges are not allowed",
  shipping_constraint_unverified: "Shipping requirements could not be verified",
  mandate_unconfirmed: "Mandate was not confirmed",
  mandate_expired_or_not_started: "Mandate is outside its validity window",
  checkout_source_unavailable_or_wrong_owner: "Checkout could not be retrieved from the merchant",
  checkout_expired_or_future_evidence: "Checkout evidence is stale or inconsistent",
  checkout_price_nonpositive: "Checkout has an invalid price",
  checkout_recurrence_inconsistent: "Checkout billing terms are inconsistent",
  financial_authority_unavailable: "Payment execution is not enabled yet",
};

export function reasonText(code: string): string {
  return REASONS[code] ?? code.replace(/_/g, " ");
}

/** Operational blocks are not attacks; keep them out of the incident list. */
const OPERATIONAL_REASONS = new Set(["financial_authority_unavailable"]);

function str(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

export function reasonsOf(event: ActivityEvent): string[] {
  return strings(event.data.reasons);
}

export function toneFor(event: ActivityEvent): Tone {
  const { type, data } = event;
  if (type === "payment.denied") {
    const reasons = reasonsOf(event);
    return reasons.length && reasons.every((r) => OPERATIONAL_REASONS.has(r))
      ? "warning"
      : "danger";
  }
  if (type === "authorization.decided") {
    return str(data.result)?.toUpperCase() === "APPROVED" ? "success" : "danger";
  }
  if (type === "provenance.source") {
    return isSuspiciousSource(event) ? "warning" : "neutral";
  }
  if (type === "guardian.verdict") {
    const rec = str(data.recommendation);
    if (rec === "block") return "danger";
    if (rec === "review") return "warning";
    return "neutral";
  }
  if (
    type.includes("blocked") ||
    type.includes("failed") ||
    type.includes("incident") ||
    type === "killswitch.changed"
  ) {
    return "danger";
  }
  if (type.includes("revoked") || type.includes("expired") || type.includes("stop")) {
    return "warning";
  }
  if (type.includes("review") || type.includes("pending")) return "warning";
  if (
    type === "mandate.approved" ||
    type === "checkout.verified" ||
    type === "payment.approved" ||
    type === "grant.consumed"
  ) {
    return "success";
  }
  if (type === "mandate.proposed" || type === "mandate.updated") return "info";
  return "neutral";
}

export function isSuspiciousSource(event: ActivityEvent): boolean {
  if (event.type !== "provenance.source") return false;
  const d = event.data;
  return (
    d.hidden_text_detected === true ||
    strings(d.suspicious_phrases).length > 0 ||
    strings(d.hidden_suspicious_phrases).length > 0
  );
}

export function runIdOf(event: ActivityEvent): string | null {
  return str(event.data.run_id);
}

export function mandateIdOf(event: ActivityEvent): string | null {
  return str(event.data.mandate_id);
}

/** One-line description from fields the backend actually persisted. */
export function summarize(event: ActivityEvent): string | null {
  const d = event.data;
  const parts: string[] = [];
  switch (event.type) {
    case "agent.tool.before":
    case "agent.tool.after": {
      const tool = str(d.tool_name);
      if (tool) parts.push(tool);
      const summary = str(d.tool_result_summary) ?? str(d.proposed_action);
      if (summary) parts.push(summary);
      const ms = num(d.duration_ms);
      if (ms !== null) parts.push(`${Math.round(ms)} ms`);
      break;
    }
    case "provenance.source": {
      const url = str(d.url);
      if (url) parts.push(url);
      if (d.hidden_text_detected === true) parts.push("hidden text detected");
      const phrases = strings(d.suspicious_phrases).length;
      if (phrases) parts.push(`${phrases} suspicious phrase${phrases === 1 ? "" : "s"}`);
      break;
    }
    case "payment.approved":
    case "payment.denied": {
      const reasons = reasonsOf(event);
      if (reasons.length) parts.push(reasons.map(reasonText).join("; "));
      const checkout = str(d.checkout_id);
      if (checkout) parts.push(checkout);
      break;
    }
    case "authorization.decided": {
      const result = str(d.result);
      if (result) parts.push(result.toLowerCase());
      const amount = num(d.amount_cents);
      if (amount !== null) parts.push(formatUsdFromCents(amount));
      const descriptor = str(d.descriptor);
      if (descriptor) parts.push(descriptor);
      const reason = str(d.reason);
      if (reason && reason !== "approved") parts.push(reason.replace(/_/g, " "));
      break;
    }
    case "killswitch.changed": {
      const stage = str(d.stage);
      if (stage === "requested") {
        const revoked = num(d.mandates_revoked);
        parts.push(
          `Account stop requested${revoked !== null ? ` · ${revoked} mandate${revoked === 1 ? "" : "s"} revoked` : ""}`,
        );
      } else if (stage === "rail_outcome") {
        parts.push(`Rail ${str(d.status) ?? "outcome"}`);
        const unused = num(d.unused_grants_revoked);
        if (unused !== null) parts.push(`${unused} unused grant${unused === 1 ? "" : "s"} invalidated`);
      }
      break;
    }
    case "run.stop.requested": {
      const run = str(d.run_id);
      if (run) parts.push(run);
      break;
    }
    case "card.control.outcome":
    case "card.control.requested": {
      const state = str(d.requested_state);
      if (state) parts.push(state.toLowerCase());
      const outcome = str(d.outcome);
      if (outcome) parts.push(outcome);
      break;
    }
    default: {
      if (event.type.startsWith("mandate.")) {
        const version = num(d.mandate_version);
        if (version !== null) parts.push(`v${version}`);
        const mandate = str(d.mandate_id);
        if (mandate) parts.push(mandate);
        const source = str(d.source);
        if (source === "human_killswitch") parts.push("by Kill Switch");
        break;
      }
      if (event.type === "agent.run_started") {
        const mode = str(d.agent_mode);
        if (mode) parts.push(mode === "scripted" ? "simulated compromised agent" : "live shopper");
        const run = str(d.run_id);
        if (run) parts.push(run);
        break;
      }
      const amount = num(d.amount_cents);
      if (amount !== null) parts.push(formatUsdFromCents(amount));
      const status = str(d.status);
      if (status) parts.push(status.replace(/_/g, " "));
    }
  }
  return parts.length ? parts.join(" · ") : null;
}

export type Incident = {
  id: string;
  at: string;
  tone: Tone;
  title: string;
  explanation: string;
  reasons: string[];
  mandateId: string | null;
  runId: string | null;
  checkoutId: string | null;
  sourceEvent: ActivityEvent;
};

/**
 * Incidents come only from persisted events: recorded incidents, policy
 * blocks, guardian block/review findings and sources with hidden content.
 */
export function deriveIncidents(events: ActivityEvent[]): Incident[] {
  const incidents: Incident[] = [];
  for (const event of events) {
    const d = event.data;
    const base = {
      id: event.event_id,
      at: event.at,
      mandateId: mandateIdOf(event),
      runId: runIdOf(event),
      checkoutId: str(d.checkout_id),
      sourceEvent: event,
    };
    if (event.type === "security.incident_recorded") {
      incidents.push({
        ...base,
        tone: "danger",
        title: "Security incident recorded",
        explanation: str(d.explanation) ?? "The backend recorded a security incident.",
        reasons: strings(d.violated_checks),
      });
    } else if (event.type === "payment.denied") {
      const reasons = reasonsOf(event).filter((r) => !OPERATIONAL_REASONS.has(r));
      if (!reasons.length) continue;
      incidents.push({
        ...base,
        tone: "danger",
        title: "Checkout blocked before payment",
        explanation:
          "Independent checkout verification found facts that break your confirmed mandate.",
        reasons,
      });
    } else if (event.type === "checkout.blocked" || event.type === "checkout.requires_review") {
      incidents.push({
        ...base,
        tone: event.type === "checkout.blocked" ? "danger" : "warning",
        title: labelFor(event.type),
        explanation: str(d.explanation) ?? "Checkout facts did not satisfy the mandate.",
        reasons: reasonsOf(event),
      });
    } else if (event.type === "guardian.verdict") {
      const rec = str(d.recommendation);
      if (rec !== "block" && rec !== "review") continue;
      incidents.push({
        ...base,
        tone: rec === "block" ? "danger" : "warning",
        title: rec === "block" ? "Guardian recommends blocking" : "Guardian recommends review",
        explanation:
          str(d.explanation) ??
          "Advisory finding. It cannot approve anything; deterministic checks decide.",
        reasons: strings(d.violated_checks),
      });
    } else if (isSuspiciousSource(event)) {
      const phrases = [
        ...strings(d.suspicious_phrases),
        ...strings(d.hidden_suspicious_phrases),
      ];
      incidents.push({
        ...base,
        tone: "warning",
        title: "Suspicious content on a fetched page",
        explanation: str(d.url)
          ? `The agent read ${str(d.url)}. Page content is untrusted and cannot authorize a purchase.`
          : "Page content is untrusted and cannot authorize a purchase.",
        reasons: phrases.slice(0, 6),
      });
    }
  }
  return incidents.reverse();
}

export type PaymentRow = {
  id: string;
  at: string;
  kind: "attempt" | "rail";
  tone: Tone;
  title: string;
  detail: string | null;
  amountCents: number | null;
  rail: string | null;
  decisionSource: string | null;
  provider: string | null;
  sourceEvent: ActivityEvent;
};

const RAIL_LABELS: Record<string, string> = {
  local_simulator: "Local Payment Rail Simulator",
  local_payment_rail_simulator: "Local Payment Rail Simulator",
  lithic_sandbox: "Lithic sandbox",
};

export function railLabel(rail: string | null): string | null {
  if (!rail) return null;
  return RAIL_LABELS[rail] ?? rail.replace(/_/g, " ");
}

export function derivePayments(events: ActivityEvent[]): PaymentRow[] {
  const rows: PaymentRow[] = [];
  for (const event of events) {
    const d = event.data;
    if (event.type === "payment.approved" || event.type === "payment.denied") {
      const reasons = reasonsOf(event);
      rows.push({
        id: event.event_id,
        at: event.at,
        kind: "attempt",
        tone: toneFor(event),
        title: event.type === "payment.approved" ? "Grant approved" : "Blocked before payment",
        detail: reasons.length ? reasons.map(reasonText).join("; ") : null,
        amountCents: num(d.amount_cents),
        rail: null,
        decisionSource: "deterministic_policy",
        provider: null,
        sourceEvent: event,
      });
    } else if (event.type === "authorization.decided") {
      const approved = str(d.result)?.toUpperCase() === "APPROVED";
      rows.push({
        id: event.event_id,
        at: event.at,
        kind: "rail",
        tone: approved ? "success" : "danger",
        title: approved ? "Authorized" : "Declined",
        detail: str(d.reason) && str(d.reason) !== "approved" ? str(d.reason)!.replace(/_/g, " ") : str(d.descriptor),
        amountCents: num(d.amount_cents),
        rail: railLabel(str(d.rail)),
        decisionSource: str(d.decision_source),
        provider: str(d.provider),
        sourceEvent: event,
      });
    }
  }
  return rows.reverse();
}

export function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatRelative(iso: string, now = Date.now()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const diff = then - now;
  const abs = Math.abs(diff);
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["day", 86_400_000],
    ["hour", 3_600_000],
    ["minute", 60_000],
  ];
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  for (const [unit, ms] of units) {
    if (abs >= ms) return rtf.format(Math.round(diff / ms), unit);
  }
  return diff < 0 ? "just now" : "in under a minute";
}

export function shortId(id: string, keep = 8): string {
  const [prefix, rest] = id.includes("_") ? [id.slice(0, id.indexOf("_") + 1), id.slice(id.indexOf("_") + 1)] : ["", id];
  return rest.length > keep ? `${prefix}${rest.slice(0, keep)}…` : id;
}
