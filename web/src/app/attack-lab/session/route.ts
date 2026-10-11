import { NextResponse } from "next/server";
import { bearerToken, LAB_VIEW_COOKIE, labDenied, verifyLabOperator } from "@/lib/lab-server";

function requestOrigin(request: Request) {
  // Next's internal route URL may use localhost behind a reverse proxy. The
  // browser Host is the destination; never trust caller-supplied forwarding headers.
  const url = new URL(request.url);
  const host = request.headers.get("host");
  if (host) url.host = host;
  return url;
}

function sameOrigin(request: Request) {
  const origin = request.headers.get("origin");
  return (!origin || origin === requestOrigin(request).origin)
    && request.headers.get("sec-fetch-site") !== "cross-site";
}

function cookieOptions(request: Request) {
  const url = requestOrigin(request);
  return { httpOnly: true, sameSite: "strict" as const, path: "/attack-lab",
    // Plain HTTP is supported only for local development. Deployed UI needs HTTPS.
    secure: !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname), maxAge: 300 };
}

export async function POST(request: Request) {
  if (!sameOrigin(request)) return labDenied(403);
  const token = bearerToken(request.headers.get("authorization"));
  const status = await verifyLabOperator(token);
  if (status !== 200 || !token) return labDenied(status);
  const response = new NextResponse(null, { status: 204, headers: { "Cache-Control": "no-store" } });
  // Reuse the current verified session, rather than minting a new authority token.
  // This cookie opens read-only HTML; API mutations still require an explicit Bearer.
  response.cookies.set(LAB_VIEW_COOKIE, token, cookieOptions(request));
  return response;
}

export async function DELETE(request: Request) {
  if (!sameOrigin(request)) return labDenied(403);
  const response = new NextResponse(null, { status: 204, headers: { "Cache-Control": "no-store" } });
  response.cookies.set(LAB_VIEW_COOKIE, "", { ...cookieOptions(request), maxAge: 0 });
  return response;
}
