/**
 * The one HTTP client every page uses: auth header, silent refresh, the backend error
 * envelope, the short GET cache and its invalidation. `fetch` is replaced per test; nothing
 * here talks to a server.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

type Call = { url: string; init: RequestInit };

function json(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** Load a fresh copy of the module, so the in-memory token and cache start empty. */
async function client() {
  vi.resetModules();
  return import("@/lib/api/http");
}

let calls: Call[];
function routeFetch(handler: (url: string, init: RequestInit) => Response | Promise<Response>) {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ url, init });
    return handler(url, init);
  }));
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe("withQuery", () => {
  it("drops empty values and repeats arrays", async () => {
    const { withQuery } = await client();
    expect(withQuery("/x", { a: "1", b: "", c: null, d: undefined, e: ["p", "q"], f: 0, g: false }))
      .toBe("/x?a=1&e=p&e=q&f=0&g=false");
    expect(withQuery("/x", { a: "" })).toBe("/x");
    expect(withQuery("/x")).toBe("/x");
  });
});

describe("errors", () => {
  it("raises the backend's own code, message and details", async () => {
    routeFetch(() => json(422, { error: { code: "validation_error", message: "Request validation failed.", details: [{ loc: ["body", "score"], message: "too big" }] } }));
    const { api, ApiError } = await client();
    const error = await api<never>("/thing").catch((e: InstanceType<typeof ApiError>) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, code: "validation_error", message: "Request validation failed." });
    expect(error.details).toEqual([{ loc: ["body", "score"], message: "too big" }]);
  });

  it("turns a non-JSON failure into a readable error, never an exception about parsing", async () => {
    routeFetch(() => new Response("<html>Bad gateway</html>", { status: 502 }));
    const { api } = await client();
    await expect(api("/thing")).rejects.toMatchObject({ status: 502, code: "http_error", message: "Request failed (502)." });
  });

  it("204 resolves to undefined", async () => {
    routeFetch(() => new Response(null, { status: 204 }));
    const { api } = await client();
    await expect(api("/thing", { method: "POST" })).resolves.toBeUndefined();
  });
});

describe("authentication", () => {
  it("sends the in-memory token and goes through the same-origin proxy", async () => {
    routeFetch(() => json(200, { ok: true }));
    const { api, setAccessToken } = await client();
    setAccessToken("tok-1");
    await api("/me/workspace");
    expect(calls[0].url).toBe("/api/v1/me/workspace");
    expect((calls[0].init.headers as Record<string, string>).authorization).toBe("Bearer tok-1");
    expect(calls[0].init.credentials).toBe("same-origin");
  });

  it("on 401 refreshes once through the session route and retries with the new token", async () => {
    let first = true;
    routeFetch((url, init) => {
      if (url === "/api/session/refresh") return json(200, { access_token: "tok-2" });
      const auth = (init.headers as Record<string, string>).authorization;
      if (first) { first = false; return json(401, { error: { code: "not_authenticated", message: "expired", details: [] } }); }
      return json(200, { auth });
    });
    const { api, setAccessToken } = await client();
    setAccessToken("tok-1");
    await expect(api("/data")).resolves.toEqual({ auth: "Bearer tok-2" });
    expect(calls.map((c) => c.url)).toEqual(["/api/v1/data", "/api/session/refresh", "/api/v1/data"]);
  });

  it("concurrent 401s share one refresh (the rotated cookie is never replayed)", async () => {
    let refreshes = 0;
    routeFetch(async (url, init) => {
      if (url === "/api/session/refresh") { refreshes += 1; await new Promise((r) => setTimeout(r, 10)); return json(200, { access_token: "fresh" }); }
      return (init.headers as Record<string, string>).authorization === "Bearer fresh" ? json(200, { url }) : json(401, {});
    });
    const { api, setAccessToken } = await client();
    setAccessToken("stale");
    await Promise.all([api("/a"), api("/b"), api("/c")]);
    expect(refreshes).toBe(1);
  });

  it("when the refresh fails, the session-lost handler runs and the 401 surfaces", async () => {
    routeFetch((url) => (url === "/api/session/refresh" ? new Response(null, { status: 204 }) : json(401, { error: { code: "not_authenticated", message: "Authentication required.", details: [] } })));
    const { api, onUnauthenticated } = await client();
    const lost = vi.fn();
    onUnauthenticated(lost);
    await expect(api("/data")).rejects.toMatchObject({ status: 401, code: "not_authenticated" });
    expect(lost).toHaveBeenCalledTimes(1);
    expect(calls.filter((c) => c.url === "/api/session/refresh")).toHaveLength(1);
  });

  it("a 401 is retried only once, so a revoked session cannot loop", async () => {
    routeFetch((url) => (url === "/api/session/refresh" ? json(200, { access_token: "still-bad" }) : json(401, {})));
    const { api } = await client();
    await expect(api("/data")).rejects.toMatchObject({ status: 401 });
    expect(calls.filter((c) => c.url === "/api/v1/data")).toHaveLength(2);
  });

  it("sign-out forgets the token: later calls carry no authorization header", async () => {
    routeFetch((url) => (url === "/api/session/logout" ? new Response(null, { status: 204 }) : json(200, {})));
    const { api, setAccessToken, sessionLogout } = await client();
    setAccessToken("tok");
    await sessionLogout();
    await api("/public");
    const last = calls.at(-1)!;
    expect((last.init.headers as Record<string, string>).authorization).toBeUndefined();
  });
});

describe("GET cache", () => {
  it("serves an identical read from cache and refetches after any write", async () => {
    routeFetch((url, init) => json(200, { url, method: init.method }));
    const { api } = await client();
    await api("/list", { query: { a: 1 } });
    await api("/list", { query: { a: 1 } });
    expect(calls).toHaveLength(1);
    await api("/list", { query: { a: 2 } });
    expect(calls).toHaveLength(2);
    await api("/thing", { method: "PATCH", body: { x: 1 } });
    await api("/list", { query: { a: 1 } });
    expect(calls).toHaveLength(4);
  });

  it("never keeps a failure", async () => {
    let n = 0;
    routeFetch(() => (++n === 1 ? json(500, { error: { code: "internal_error", message: "boom", details: [] } }) : json(200, { ok: true })));
    const { api } = await client();
    await expect(api("/x")).rejects.toMatchObject({ status: 500 });
    await expect(api("/x")).resolves.toEqual({ ok: true });
  });

  it("a different signed-in user never sees the previous user's cached reads", async () => {
    let who = "A";
    routeFetch((url) => (url === "/api/session/login" ? json(200, { access_token: `tok-${who}` }) : json(200, { who })));
    const { api, sessionLogin } = await client();
    await sessionLogin("a@x", "pw");
    expect(await api("/me/workspace")).toEqual({ who: "A" });
    who = "B";
    await sessionLogin("b@x", "pw");
    expect(await api("/me/workspace")).toEqual({ who: "B" });
  });

  it("a body-carrying request defaults to POST and sends JSON", async () => {
    routeFetch(() => json(201, { id: "1" }));
    const { api } = await client();
    await api("/things", { body: { name: "n" } });
    expect(calls[0].init.method).toBe("POST");
    expect((calls[0].init.headers as Record<string, string>)["content-type"]).toBe("application/json");
    expect(calls[0].init.body).toBe('{"name":"n"}');
  });
});

describe("sign-in", () => {
  it("a wrong password raises the server's 401 without storing a token", async () => {
    routeFetch((url) => (url === "/api/session/login" ? json(401, { error: { code: "not_authenticated", message: "Invalid email or password.", details: [] } }) : json(200, {})));
    const { api, sessionLogin } = await client();
    await expect(sessionLogin("a@x", "wrong")).rejects.toMatchObject({ status: 401, message: "Invalid email or password." });
    await api("/anything");
    expect((calls.at(-1)!.init.headers as Record<string, string>).authorization).toBeUndefined();
  });
});
