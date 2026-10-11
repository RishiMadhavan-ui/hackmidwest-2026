// Stream the upstream body directly; keep Bearer credentials out of URLs/logs.
export async function GET(request: Request) {
  const origin = process.env.API_ORIGIN ?? "http://api:8000";
  const url = new URL("/activity/stream", origin);
  const cursor = new URL(request.url).searchParams.get("after");
  if (cursor !== null) url.searchParams.set("after", cursor);
  const headers = new Headers({ Accept: "text/event-stream" });
  for (const name of ["authorization", "last-event-id"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const upstream = await fetch(url, { headers, cache: "no-store", signal: request.signal });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "application/json",
        "Cache-Control": "no-store, no-transform",
        "X-Accel-Buffering": "no",
      },
    });
  } catch {
    return Response.json({ detail: "Activity stream unavailable" }, { status: 503 });
  }
}
