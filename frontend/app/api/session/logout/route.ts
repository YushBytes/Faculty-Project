import { NextResponse, type NextRequest } from "next/server";
import { BACKEND_URL, REFRESH_COOKIE, refreshCookie } from "@/lib/server/backend";

export async function POST(request: NextRequest) {
  const current = request.cookies.get(REFRESH_COOKIE)?.value;
  if (current) {
    await fetch(`${BACKEND_URL}/api/v1/auth/logout`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: current }),
      cache: "no-store",
    }).catch(() => null);
  }
  const response = new NextResponse(null, { status: 204 });
  response.cookies.set(refreshCookie("", 0));
  return response;
}
