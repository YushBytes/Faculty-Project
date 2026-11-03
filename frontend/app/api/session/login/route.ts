import { NextResponse, type NextRequest } from "next/server";
import { BACKEND_URL, refreshCookie, type TokenPair } from "@/lib/server/backend";

export async function POST(request: NextRequest) {
  const body = await request.text();
  const upstream = await fetch(`${BACKEND_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body,
    cache: "no-store",
  }).catch(() => null);
  if (!upstream) return NextResponse.json({ error: { code: "backend_unavailable", message: "The ACADLYTICS server is not reachable.", details: [] } }, { status: 502 });
  const payload = await upstream.json().catch(() => ({}));
  if (!upstream.ok) return NextResponse.json(payload, { status: upstream.status });
  const tokens = payload as TokenPair;
  const response = NextResponse.json({ access_token: tokens.access_token, expires_at: tokens.access_token_expires_at });
  response.cookies.set(refreshCookie(tokens.refresh_token));
  return response;
}
