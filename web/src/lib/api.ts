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
  /** Forever virtual-card spend limit in integer cents. */
  spend_limit_cents: number;
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

/**
 * Stream activity via SSE using fetch (Bearer header; EventSource cannot set it).
 * Calls onEvent for each activity row; onStatus for connection state.
 */
export function streamActivity(handlers: {
  onEvent: (event: ActivityEvent) => void;
  onStatus?: (status: "connecting" | "live" | "error") => void;
  onError?: (error: Error) => void;
  after?: number;
  token?: string | null;
  signal?: AbortSignal;
}): () => void {
  const auth = handlers.token === undefined ? getStoredToken() : handlers.token;
  const after = handlers.after ?? 0;
  const controller = new AbortController();
  if (handlers.signal) {
    if (handlers.signal.aborted) controller.abort();
    else {
      handlers.signal.addEventListener("abort", () => controller.abort(), {
        once: true,
      });
    }
  }

  handlers.onStatus?.("connecting");

  (async () => {
    try {
      const response = await fetch(
        `${API_URL}/activity/stream?after=${after}`,
        {
          headers: auth ? { Authorization: `Bearer ${auth}` } : {},
          signal: controller.signal,
        },
      );
      if (!response.ok || !response.body) {
        throw new ApiError(response.status, `Activity stream failed (${response.status})`);
      }
      handlers.onStatus?.("live");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() ?? "";
        for (const chunk of chunks) {
          let eventName = "message";
          let dataLine = "";
          for (const line of chunk.split("\n")) {
            if (line.startsWith("event:")) {
              eventName = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              dataLine += line.slice(5).trim();
            }
          }
          if (eventName === "activity" && dataLine) {
            try {
              handlers.onEvent(JSON.parse(dataLine) as ActivityEvent);
            } catch {
              // ignore malformed frames
            }
          }
        }
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      handlers.onStatus?.("error");
      handlers.onError?.(
        err instanceof Error ? err : new Error("Activity stream disconnected"),
      );
    }
  })();

  return () => controller.abort();
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
