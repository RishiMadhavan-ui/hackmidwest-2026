// Local dev defaults to the API on :8000. In LKE, the web image is built with
// NEXT_PUBLIC_API_URL=/backend and Next rewrites that path to the api Service.
const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export const TOKEN_STORAGE_KEY = "hmw_access_token";

export type User = {
  id: string;
  email: string;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
  user: User;
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

export async function signup(email: string, password: string) {
  return apiFetch<TokenResponse>(
    "/auth/signup",
    {
      method: "POST",
      body: JSON.stringify({ email, password }),
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
