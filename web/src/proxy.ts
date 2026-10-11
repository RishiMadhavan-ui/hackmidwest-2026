import { NextResponse, type NextRequest } from "next/server";
import { bearerToken, LAB_VIEW_COOKIE, labDenied, verifyLabOperator } from "@/lib/lab-server";

export async function proxy(request: NextRequest) {
  // These handlers enforce explicit Bearer authentication themselves.
  if (["/attack-lab/session", "/attack-lab/operator-view"].includes(request.nextUrl.pathname)) {
    return NextResponse.next();
  }
  const header = request.headers.get("authorization");
  const readOnly = ["GET", "HEAD"].includes(request.method);
  const token = header !== null ? bearerToken(header)
    : readOnly ? request.cookies.get(LAB_VIEW_COOKIE)?.value ?? null : null;
  const status = await verifyLabOperator(token);
  if (status !== 200) return labDenied(status);
  const response = NextResponse.next();
  response.headers.set("Cache-Control", "private, no-store");
  response.headers.set("Vary", "Cookie, Authorization");
  return response;
}

export const config = { matcher: "/attack-lab/:path*" };
