/** Typed adapters: the department thresholds read goes to the scoped endpoint and a refusal is
 * an error, never an empty list (which would wrongly read as "no overrides"). */
import { beforeEach, describe, expect, it, vi } from "vitest";

const calls: string[] = [];

beforeEach(() => {
  calls.length = 0;
  vi.resetModules();
  vi.unstubAllGlobals();
});

function stub(status: number, body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  }));
}

describe("orgApi.departmentSettings", () => {
  it("reads the department's settings through the proxy", async () => {
    stub(200, [{ key: "low_performance_percent", value: 55, updated_at: "2026-11-16T00:00:00Z" }]);
    const { orgApi } = await import("@/lib/api/endpoints");
    const rows = await orgApi.departmentSettings("d-1");
    expect(calls).toEqual(["/api/v1/departments/d-1/settings"]);
    expect(rows).toEqual([{ key: "low_performance_percent", value: 55, updated_at: "2026-11-16T00:00:00Z" }]);
  });

  it("an out-of-scope department is a 404 error, not an empty list", async () => {
    stub(404, { error: { code: "not_found", message: "Department not found.", details: [] } });
    const { orgApi } = await import("@/lib/api/endpoints");
    await expect(orgApi.departmentSettings("other")).rejects.toMatchObject({ status: 404, code: "not_found" });
  });
});
