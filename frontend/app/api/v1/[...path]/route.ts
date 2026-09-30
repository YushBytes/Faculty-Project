import type { NextRequest } from "next/server";
import { BACKEND_URL } from "@/lib/server/backend";

/**
 * Same-origin proxy to the FastAPI backend (`/api/v1/*`). The browser sends its in-memory
 * access token; this forwards the request as is (method, query, body, auth) and streams the
 * response back, including file downloads. Authorisation is entirely the backend's.
 */
const FORWARD_REQUEST = ["authorization", "content-type", "accept"];
const FORWARD_RESPONSE = ["content-type", "content-disposition", "content-length", "cache-control"];

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const target = `${BACKEND_URL}/api/v1/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;
  const headers = new Headers();
  for (const name of FORWARD_REQUEST) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const hasBody = !["GET", "HEAD"].includes(request.method);
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return Response.json(
      { error: { code: "backend_unavailable", message: "The ACADLYTICS server is not reachable. Is the backend running?", details: [] } },
      { status: 502 },
    );
  }
  const out = new Headers();
  for (const name of FORWARD_RESPONSE) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const dynamic = "force-dynamic";
