/** Display helpers: a missing value is shown as "—", never as 0 or NaN. */
import { describe, expect, it } from "vitest";
import { initials, num, pct, pctOf, RULES, scaleColor, signed, value } from "@/lib/format";

describe("missing values stay missing", () => {
  it("pct", () => {
    expect(pct(null)).toBe("—");
    expect(pct(undefined)).toBe("—");
    expect(pct(0)).toBe("0.0%");
    expect(pct(49.5, 0)).toBe(`${(49.5).toFixed(0)}%`);
    expect(pct(100)).toBe("100.0%");
  });

  it("a Measure with status insufficient_data renders as —, not 0", () => {
    const insufficient = { value: null, status: "insufficient_data", reason: "n < 5", n: 2 };
    expect(value(insufficient as never)).toBeNull();
    expect(pctOf(insufficient as never)).toBe("—");
    expect(pctOf({ value: 0, status: "ok" } as never)).toBe("0.0%");
    expect(pctOf(null)).toBe("—");
  });

  it("num and signed", () => {
    expect(num(null)).toBe("—");
    expect(num(0)).toBe("0");
    expect(num(123456)).toBe("1,23,456");
    expect(signed(null)).toBe("—");
    expect(signed(0)).toBe("0.0 pp");
    expect(signed(4.25)).toBe("+4.3 pp");
    expect(signed(-9.8)).toBe("-9.8 pp");
  });
});

describe("labels", () => {
  it("every attention rule R1-R7 has a display name", () => {
    expect(Object.keys(RULES).sort()).toEqual([
      "R1_LOW_PERFORMANCE", "R2_FAILED_LATEST", "R3_REPEATED_LOW", "R4_SHARP_DECLINE",
      "R5_DECLINING_TREND", "R6_LOW_COMPLETION", "R7_BORDERLINE",
    ]);
  });

  it("initials skip titles", () => {
    expect(initials("Dr. Kavya Iyer")).toBe("KI");
    expect(initials("Administrator")).toBe("A");
  });

  it("the colour scale has an explicit empty colour, not the lowest band", () => {
    expect(scaleColor(null)).toBe("var(--scale-empty)");
    expect(scaleColor(0)).toBe("var(--scale-1)");
    expect(scaleColor(100)).toBe("var(--scale-6)");
  });
});
