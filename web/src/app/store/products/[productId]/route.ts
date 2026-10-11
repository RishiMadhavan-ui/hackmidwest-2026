// Public listing adapter. Human checkout start is POST .../checkout (sibling route).
export async function GET(
  request: Request,
  context: { params: Promise<{ productId: string }> },
) {
  const { productId } = await context.params;
  if (!/^[a-zA-Z0-9_-]{1,128}$/.test(productId)) {
    return Response.json({ detail: "Unknown product" }, { status: 404 });
  }
  // Attack execution stays disabled until a separate, server-authorized
  // operator/scenario boundary exists. Neither a query nor a service token
  // grants permission to inject a public listing.
  const selectors = new URL(request.url).searchParams.getAll("evil");
  if (selectors.some((value) => !["0", "false", "off", "no"].includes(value.toLowerCase()))) {
    return Response.json(
      { detail: "Attack Lab execution is disabled" },
      { status: 403, headers: { "Cache-Control": "no-store" } },
    );
  }
  const origin = process.env.STORE_ORIGIN ?? "http://store:8000";
  const url = new URL(`/products/${encodeURIComponent(productId)}`, origin);
  // Force clean rendering even when the upstream still runs an older image
  // with STORE_EVIL_MODE enabled. The store also enforces this independently.
  url.searchParams.set("evil", "0");
  try {
    const upstream = await fetch(url, {
      cache: "no-store",
      redirect: "error",
      signal: request.signal,
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "text/html",
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return Response.json({ detail: "Store listing unavailable" }, { status: 503 });
  }
}
