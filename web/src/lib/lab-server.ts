// Server-only authorization adapter for the existing LEASH JWT session.
// Every view request is reverified by the API, including logout and allowlist changes.
export const LAB_VIEW_COOKIE = "leash_lab_view";

export function bearerToken(value: string | null): string | null {
  return value?.match(/^Bearer ([A-Za-z0-9_.-]{1,4096})$/i)?.[1] ?? null;
}

export async function verifyLabOperator(token: string | null): Promise<number> {
  if (!token || !/^[A-Za-z0-9_.-]{1,4096}$/.test(token)) return 401;
  try {
    const origin = process.env.API_ORIGIN ?? "http://api:8000";
    const response = await fetch(`${origin.replace(/\/$/, "")}/attack-lab/access`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store", redirect: "error", signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return [401, 403].includes(response.status) ? response.status : 503;
    const state = await response.json();
    return state.operator_authorized === true && state.execution_available === false
      && typeof state.server_enabled === "boolean" ? 200 : 503;
  } catch {
    return 503;
  }
}

export function labDenied(status: number): Response {
  return Response.json({ detail: status === 401 ? "Not authenticated"
    : status === 403 ? "Attack Lab requires an authorized demo operator" : "Operator access unavailable" },
  { status, headers: { "Cache-Control": "no-store", Vary: "Cookie, Authorization" } });
}
