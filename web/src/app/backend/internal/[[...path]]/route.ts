// Service publishers use the private API origin. Browser rewrites must not
// expose internal service routes, even when a caller presents a credential.
function unavailable() {
  return Response.json({ detail: "Not found" }, { status: 404 });
}

export const GET = unavailable;
export const POST = unavailable;
export const PUT = unavailable;
export const PATCH = unavailable;
export const DELETE = unavailable;
export const OPTIONS = unavailable;
export const HEAD = unavailable;
