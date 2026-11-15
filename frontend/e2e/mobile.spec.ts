import { expect, test } from "@playwright/test";
import { signIn, state } from "./helpers";

test("on a phone, pages fit the screen and the menu opens", async ({ page }) => {
  test.setTimeout(120_000);
  const s = state();
  await signIn(page, s.facultyA.email, s.facultyA.password);
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 20_000 });
  for (const path of ["/dashboard", "/settings", `/classes/${s.classA}`, "/attention", "/students", "/import", "/reports"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `${path} scrolls sideways by ${overflow}px`).toBeLessThanOrEqual(1);
  }
  await page.getByRole("button", { name: "Toggle navigation" }).click();
  await page.getByRole("navigation").getByRole("link", { name: "Attention" }).click();
  await expect(page).toHaveURL(/\/attention/);
});
