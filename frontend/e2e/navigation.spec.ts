import { expect, test } from "@playwright/test";
import { signIn, state, watch } from "./helpers";

test("every sidebar destination opens cleanly for the Administrator", async ({ page }) => {
  test.setTimeout(180_000);
  const s = state();
  await signIn(page, s.admin.email, s.admin.password);
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 20_000 });
  const hrefs = await page.getByRole("navigation").getByRole("link").evaluateAll((links) => links.map((a) => a.getAttribute("href")!));
  expect(hrefs.length).toBeGreaterThan(15);
  for (const href of hrefs) {
    const w = watch(page);
    await page.goto(href);
    await expect(page.getByRole("heading", { level: 1 }), href).toBeVisible();
    await expect(page.getByText(/Could not load this view/)).toHaveCount(0);
    const text = await page.locator("main").innerText();
    expect(text, `${href} shows a raw value`).not.toMatch(/\b(NaN|undefined|Infinity|\[object Object\])\b/);
    w.expectClean();
    page.removeAllListeners("response");
    page.removeAllListeners("console");
    page.removeAllListeners("pageerror");
  }
});

test("an unknown address shows the product's not-found page with a way back", async ({ page }) => {
  await page.goto("/no-such-page");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Go to your overview" })).toHaveAttribute("href", "/dashboard");
});

test("the class page reflects the marks entered, keeping absent, missing and zero apart", async ({ page }) => {
  const s = state();
  await signIn(page, s.facultyA.email, s.facultyA.password, `/classes/${s.classA}`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Browser Test Course", { timeout: 20_000 });
  await page.getByRole("tab", { name: "Marks" }).click();
  const row = (name: string) => page.getByRole("row").filter({ hasText: name });
  await expect(row("DEEPA NAIR")).toContainText("0");          // a genuine zero is a mark
  await expect(row("ESHAAN GUPTA")).toContainText("AB");       // absent
  await expect(row("HEMA PRASAD").getByRole("cell").nth(2)).toHaveText("—"); // no row: missing
  await page.getByRole("tab", { name: "Assessments" }).click();
  const ct1 = page.getByRole("row").filter({ hasText: "CT1" });
  await expect(ct1).toContainText("6 present");
  await expect(ct1).toContainText("1 absent");
  await expect(ct1).toContainText("1 missing");
});
