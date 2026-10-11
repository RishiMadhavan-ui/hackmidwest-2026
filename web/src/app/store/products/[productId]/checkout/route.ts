// Browser storefront checkout start only. Authenticated bind/complete stay private.
export async function POST(
  request: Request,
  context: { params: Promise<{ productId: string }> },
) {
  const { productId } = await context.params;
  if (!/^[a-zA-Z0-9_-]{1,128}$/.test(productId)) {
    return Response.json({ detail: "Unknown product" }, { status: 404 });
  }
  const origin = process.env.STORE_ORIGIN ?? "http://store:8000";
  const url = new URL(
    `/products/${encodeURIComponent(productId)}/checkout`,
    origin,
  );
  try {
    const upstream = await fetch(url, {
      method: "POST",
      cache: "no-store",
      redirect: "error",
      signal: request.signal,
      headers: {
        Accept: request.headers.get("accept") ?? "text/html",
      },
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "text/html",
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return Response.json({ detail: "Store checkout unavailable" }, { status: 503 });
  }
}
