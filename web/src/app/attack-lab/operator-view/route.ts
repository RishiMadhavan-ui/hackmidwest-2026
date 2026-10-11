// Protected operator status view. Uses the existing human Bearer session; cookies and
// client role claims never authorize this route. Mutations stay at the API.
export async function GET(request: Request) {
  const authorization = request.headers.get("authorization");
  if (!authorization || !/^Bearer [A-Za-z0-9_.-]{1,4096}$/i.test(authorization)) {
    return Response.json({ detail: "Not authenticated" }, { status: 401 });
  }
  try {
    const origin = process.env.API_ORIGIN ?? "http://api:8000";
    const upstream = await fetch(`${origin.replace(/\/$/, "")}/attack-lab/access`, {
      headers: { Authorization: authorization, Accept: "application/json" },
      cache: "no-store", redirect: "error", signal: AbortSignal.timeout(5000),
    });
    if (!upstream.ok) {
      return Response.json({ detail: "Operator access unavailable" }, {
        status: [401, 403].includes(upstream.status) ? upstream.status : 503,
        headers: { "Cache-Control": "no-store" },
      });
    }
    const state = await upstream.json();
    if (state.operator_authorized !== true || state.execution_available !== false
      || typeof state.server_enabled !== "boolean") {
      return Response.json({ detail: "Operator view unavailable" }, { status: 503 });
    }
    const html = `<!doctype html><html lang="en"><head><meta charset="utf-8">
      <meta http-equiv="Content-Security-Policy" content="default-src 'none'">
      <title>LEASH operator workspace</title></head><body>
      <h1>Attack Lab operator workspace</h1>
      <p>Operator access verified by LEASH.</p>
      <p>Server controls: ${state.server_enabled ? "enabled" : "disabled"}.</p>
      <p>Workspace controls: ${state.namespace?.enabled === true ? "enabled" : "disabled"}.</p>
      <p>Scenario execution is unavailable while isolated fixtures, payment controls
      and the shopping workflow are being integrated.</p>
      <p>No scenario has run and no charge has been initiated by opening this view.</p>
      </body></html>`;
    return new Response(html, { headers: {
      "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store",
      "Content-Security-Policy": "default-src 'none'; frame-ancestors 'self'",
      "X-Content-Type-Options": "nosniff",
    } });
  } catch {
    return Response.json({ detail: "Operator view unavailable" }, { status: 503 });
  }
}
