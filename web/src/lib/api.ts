// Local dev defaults to the API on :8000. In LKE, the web image is built with
// NEXT_PUBLIC_API_URL=/backend and Next rewrites that path to the api Service.
const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export const TOKEN_STORAGE_KEY = "hmw_access_token";

export type User = {
  id: string;
  email: string;
  first_name?: string | null;
  last_name?: string | null;
  postal_code?: string | null;
  lithic_linked?: boolean;
  lithic_card_last_four?: string | null;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
  user: User;
};

/** Credit-like headroom vs sandbox virtual card spend_limit (not a prepaid ledger). */
export type Balance = {
  currency: string;
  available_cents: number;
  pending_cents: number;
  total_cents: number;
  spent_cents?: number;
  limit_cents?: number;
  last_four?: string | null;
  provider: string;
  model?: string;
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  token?: string | null,
): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  const auth = token === undefined ? getStoredToken() : token;
  if (auth) {
    headers.set("Authorization", `Bearer ${auth}`);
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string | { msg?: string }[] };
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body.detail) && body.detail[0]?.msg) {
        detail = body.detail[0].msg;
      }
    } catch {
      // keep default
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export async function checkHealth() {
  return apiFetch<{ status: string; service: string }>("/health", {}, null);
}

export type SignupInput = {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  postal_code: string;
  /** Deprecated compatibility field; signup does not issue a card. */
  spend_limit_cents?: number;
};

export async function signup(input: SignupInput) {
  return apiFetch<TokenResponse>(
    "/auth/signup",
    {
      method: "POST",
      body: JSON.stringify(input),
    },
    null,
  );
}

export async function login(email: string, password: string) {
  return apiFetch<TokenResponse>(
    "/auth/login",
    {
      method: "POST",
      body: JSON.stringify({ email, password }),
    },
    null,
  );
}

export async function me(token?: string | null) {
  return apiFetch<User>("/auth/me", {}, token);
}

export async function fetchBalance(token?: string | null) {
  return apiFetch<Balance>("/auth/balance", {}, token);
}

export async function logoutSession(token?: string | null) {
  return apiFetch<void>("/auth/logout", { method: "POST" }, token);
}

export type ActivityEvent = {
  sequence: number;
  event_id: string;
  type: string;
  at: string;
  user_id: string;
  data: Record<string, unknown>;
};

export type ActivityHistory = {
  events: ActivityEvent[];
  next_cursor: number | null;
};

export async function fetchActivity(
  after = 0,
  limit = 100,
  token?: string | null,
) {
  const params = new URLSearchParams({
    after: String(after),
    limit: String(limit),
  });
  return apiFetch<ActivityHistory>(`/activity?${params}`, {}, token);
}

/** Authenticated SSE with a durable replay cursor. Reconnect never starts a run. */
export function streamActivity(handlers: {
  onEvent: (event: ActivityEvent) => void;
  onStatus?: (status: "connecting" | "live" | "error") => void;
  onError?: (error: Error) => void;
  after?: number;
  token?: string | null;
  signal?: AbortSignal;
}): () => void {
  const controller = new AbortController();
  const abort = () => controller.abort();
  handlers.signal?.addEventListener("abort", abort, { once: true });
  if (handlers.signal?.aborted) abort();
  let cursor = handlers.after ?? 0;
  let retryMs = 1000;
  async function connect() {
    while (!controller.signal.aborted) {
      handlers.onStatus?.("connecting");
      try {
        const headers = new Headers({ Accept: "text/event-stream" });
        const token = handlers.token === undefined ? getStoredToken() : handlers.token;
        if (token) headers.set("Authorization", `Bearer ${token}`);
        const response = await fetch(`${API_URL}/activity/stream?after=${cursor}`, {
          headers, signal: controller.signal, cache: "no-store",
        });
        if (!response.ok || !response.body) throw new ApiError(response.status, "Activity stream unavailable");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        try {
          while (!controller.signal.aborted) {
            const chunk = await reader.read();
            if (chunk.done) throw new Error("Activity connection closed");
            buffer += decoder.decode(chunk.value, { stream: true });
            buffer = buffer.replace(/\r\n/g, "\n");
            if (buffer.length > 1024 * 1024) throw new Error("Activity frame exceeds limit");
            let end: number;
            while ((end = buffer.indexOf("\n\n")) >= 0) {
              const frame = buffer.slice(0, end);
              buffer = buffer.slice(end + 2);
              const lines = frame.split("\n");
              const type = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
              const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
              if (type === "unavailable") throw new Error("Session or activity service unavailable");
              if (type === "ready") { handlers.onStatus?.("live"); retryMs = 1000; }
              if (type !== "activity" || !data) continue;
              const event = JSON.parse(data) as ActivityEvent;
              if (!Number.isSafeInteger(event.sequence) || event.sequence <= 0 || typeof event.event_id !== "string") {
                throw new Error("Invalid persisted activity event");
              }
              if (event.sequence <= cursor) continue;
              handlers.onEvent(event);
              cursor = event.sequence;
              handlers.onStatus?.("live");
            }
          }
        } finally { await reader.cancel().catch(() => {}); }
      } catch (error) {
        if (controller.signal.aborted) return;
        handlers.onStatus?.("error");
        handlers.onError?.(error instanceof Error ? error : new Error("Activity stream unavailable"));
        if (error instanceof ApiError && [401, 403].includes(error.status)) return;
      }
      await new Promise<void>((resolve) => {
        const timer = setTimeout(done, retryMs);
        function done() { clearTimeout(timer); controller.signal.removeEventListener("abort", done); resolve(); }
        controller.signal.addEventListener("abort", done, { once: true });
        if (controller.signal.aborted) done();
      });
      retryMs = Math.min(retryMs * 2, 10000);
    }
  }
  void connect();
  return () => { abort(); handlers.signal?.removeEventListener("abort", abort); };
}

export type MandateStatus =
  | "proposed"
  | "active"
  | "revoked"
  | "expired"
  | "superseded";

export type ProductConstraint = {
  name: string;
  value: string | number | boolean;
  operator: "equals" | "contains" | "minimum" | "maximum";
};

export type ShippingConstraints = {
  country?: string | null;
  postal_code?: string | null;
  deliver_by?: string | null;
  max_shipping_cents?: number | null;
};

/** PurchaseMandate from leash_shared.models; the API owns every field. */
export type Mandate = {
  id: string;
  user_id: string;
  agent_id: string;
  description: string;
  category: string;
  max_cents: number;
  currency: "USD";
  product_constraints: ProductConstraint[];
  max_quantity: number;
  maximum_purchases: number;
  allow_subscription: boolean;
  allow_recurring: boolean;
  shipping_constraints: ShippingConstraints | null;
  location: string | null;
  merchant_allowlist: string[] | null;
  valid_from: string;
  valid_until: string;
  version: number;
  created_at: string;
  status: MandateStatus;
  approved_at: string | null;
  signature: string | null;
  canonical_payload_hash: string | null;
};

/** MandateProposal: the draft body a human submits to replace a version. */
export type MandateProposal = {
  description: string;
  category: string;
  max_cents: number;
  currency: "USD";
  location: string | null;
  valid_from: string | null;
  valid_until: string | null;
  product_constraints: ProductConstraint[];
  max_quantity: number;
  maximum_purchases: number;
  allow_subscription: boolean;
  allow_recurring: boolean;
  shipping_constraints: ShippingConstraints | null;
  merchant_allowlist: string[] | null;
};

function binding(mandate: Mandate) {
  if (!mandate.canonical_payload_hash) {
    throw new ApiError(409, "Mandate has no content hash to confirm against");
  }
  return {
    version: mandate.version,
    canonical_payload_hash: mandate.canonical_payload_hash,
  };
}

export async function listMandates(status?: MandateStatus) {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  const result = await apiFetch<{ items: Mandate[] }>(`/mandates${query}`);
  return result.items;
}

export async function getMandate(id: string) {
  return apiFetch<Mandate>(`/mandates/${encodeURIComponent(id)}`);
}

export async function getMandateVersions(id: string) {
  const result = await apiFetch<{ items: Mandate[] }>(
    `/mandates/${encodeURIComponent(id)}/versions`,
  );
  return result.items;
}

/** Human confirmation of the exact version and hash the person reviewed. */
export async function approveMandate(mandate: Mandate) {
  return apiFetch<Mandate>(
    `/mandates/${encodeURIComponent(mandate.id)}/approve`,
    {
      method: "POST",
      body: JSON.stringify({ ...binding(mandate), confirmed: true }),
    },
  );
}

/** Creates a new proposed version; it still needs its own confirmation. */
export async function replaceMandate(mandate: Mandate, proposal: MandateProposal) {
  return apiFetch<Mandate>(`/mandates/${encodeURIComponent(mandate.id)}`, {
    method: "PATCH",
    body: JSON.stringify({ ...binding(mandate), proposal }),
  });
}

export async function revokeMandate(mandate: Mandate) {
  return apiFetch<Mandate>(
    `/mandates/${encodeURIComponent(mandate.id)}/revoke`,
    { method: "POST", body: JSON.stringify(binding(mandate)) },
  );
}

export type RunStop = {
  run_id: string;
  scope: "run";
  cancel_requested: boolean;
  requested_at: string | null;
  status: "pending_enforcement" | "not_requested";
  financial_revocation: string;
  graph_cancellation: string;
  provider_card_controls: string;
  previous_authorizations_reversed: false;
};

export type OwnedRun = {
  id: string;
  mandate_id: string;
  agent_mode: "live" | "scripted";
  stop: RunStop;
};

export async function listRuns() {
  return apiFetch<{ runs: OwnedRun[]; limit: number }>("/agent-runs");
}

export async function stopRun(runId: string) {
  return apiFetch<RunStop>(`/agent-runs/${encodeURIComponent(runId)}/stop`, {
    method: "POST",
  });
}

export type StartShoppingRequest = {
  mandate_id: string;
  agent_mode?: "live" | "scripted";
  scenario?: "charger" | "subscription_attack";
};

export type StartShoppingResult = {
  run_id: string;
  status: string;
  agent_mode: "live" | "scripted";
  mandate_id: string;
  scenario: string;
  label: string;
};

/** Human JWT only — API holds AGENTS_SERVICE_TOKEN server-side. */
export async function startShopping(body: StartShoppingRequest) {
  return apiFetch<StartShoppingResult>("/shopping/start", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export type KillSwitchState = {
  on: boolean;
  rail_enforced: boolean;
  provider_controls_enforced: boolean;
};

export type KillSwitchResult = {
  on: true;
  status: "financially_stopped" | "pending_enforcement";
  mandates_revoked: number;
  rail: { status: "enforced" | "pending"; unused_grants_revoked?: number; reason?: string };
  run_cancellation: string;
  graph_cancellation: string;
  provider_card_controls: {
    status: "not_required" | "enforced" | "pending";
    total: number;
    confirmed: number;
  };
  previous_authorizations_reversed: false;
};

export async function getKillSwitch() {
  return apiFetch<KillSwitchState>("/killswitch");
}

export async function engageKillSwitch() {
  return apiFetch<KillSwitchResult>("/killswitch", {
    method: "POST",
    body: JSON.stringify({ on: true }),
  });
}

/** Display-only conversion; money stays integer cents on the wire. */
export function formatUsdFromCents(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  const dollars = Math.floor(abs / 100);
  const rem = abs % 100;
  const dollarsFmt = dollars.toLocaleString("en-US");
  return `${sign}$${dollarsFmt}.${rem.toString().padStart(2, "0")}`;
}
