import { NextResponse, type NextRequest } from "next/server";
import { BACKEND_URL, REFRESH_COOKIE, refreshCookie, type TokenPair } from "@/lib/server/backend";

/** Rotate the refresh token (the backend revokes the old one) and return a new access token. */
export async function POST(request: NextRequest) {
  const current = request.cookies.get(REFRESH_COOKIE)?.value;
  // No session is a normal state (a visitor on the sign-in page), not an error.
  if (!current) return new NextResponse(null, { status: 204 });
  const upstream = await fetch(`${BACKEND_URL}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ refresh_token: current }),
    cache: "no-store",
  }).catch(() => null);
  if (!upstream) return NextResponse.json({ error: { code: "backend_unavailable", message: "The ACADLYTICS server is not reachable.", details: [] } }, { status: 502 });
  if (!upstream.ok) {
    const response = NextResponse.json(await upstream.json().catch(() => ({})), { status: upstream.status });
    response.cookies.set(refreshCookie("", 0));
    return response;
  }
  const tokens = (await upstream.json()) as TokenPair;
  const response = NextResponse.json({ access_token: tokens.access_token, expires_at: tokens.access_token_expires_at });
  response.cookies.set(refreshCookie(tokens.refresh_token));
  return response;
}
