import { NextResponse, type NextRequest } from "next/server";
import { BACKEND_URL, refreshCookie, type TokenPair } from "@/lib/server/backend";

/** The roles a person can choose on the sign-in page (the backend's `Role` values). */
const ROLES = new Set(["FACULTY", "COURSE_COORDINATOR", "ACADEMIC_HEAD", "HOD", "ADMIN"]);

function invalid(message: string, field: string) {
  return NextResponse.json(
    { error: { code: "validation_error", message, details: [{ loc: ["body", field], message }] } },
    { status: 422 },
  );
}

/**
 * Website sign-in. Unlike the API (where `role` is optional for scripts and tools), the website
 * always sends the role chosen on the sign-in page; the backend checks it against the account's
 * stored role after the password and issues no tokens on a mismatch. The role never grants
 * anything — the tokens and every permission come from the stored account.
 */
export async function POST(request: NextRequest) {
  let body: { email?: unknown; password?: unknown; role?: unknown };
  try {
    body = await request.json();
  } catch {
    return invalid("Request body must be JSON.", "body");
  }
  if (typeof body?.role !== "string" || !ROLES.has(body.role)) return invalid("Choose your role to sign in.", "role");
  const upstream = await fetch(`${BACKEND_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    // Only the three expected fields are forwarded; anything else in the request is dropped.
    body: JSON.stringify({ email: body.email, password: body.password, role: body.role }),
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
