// Public listing adapter. Human checkout start is POST .../checkout (sibling route).
export async function GET(
  request: Request,
  context: { params: Promise<{ productId: string }> },
) {
  const { productId } = await context.params;
  if (!/^[a-zA-Z0-9_-]{1,128}$/.test(productId)) {
    return Response.json({ detail: "Unknown product" }, { status: 404 });
  }
  const origin = process.env.STORE_ORIGIN ?? "http://store:8000";
  const url = new URL(`/products/${encodeURIComponent(productId)}`, origin);
  const evil = new URL(request.url).searchParams.get("evil");
  if (evil !== null) url.searchParams.set("evil", evil);
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
