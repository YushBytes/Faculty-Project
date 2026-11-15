/**
 * Department thresholds: each role sees exactly the departments the server allows, and asking
 * the API directly for any other department is refused (404) — the UI is not the control.
 */
import { expect, test, type Page } from "@playwright/test";
import { signIn, state } from "./helpers";

async function token(page: Page): Promise<string> {
  return page.evaluate(async () => (await (await fetch("/api/session/refresh", { method: "POST" })).json()).access_token as string);
}

async function settingsStatus(page: Page, departmentId: string): Promise<number> {
  const bearer = await token(page);
  const response = await page.request.get(`/api/v1/departments/${departmentId}/settings`, { headers: { authorization: `Bearer ${bearer}` } });
  return response.status();
}

test("faculty see their own department's thresholds, read-only, and nothing else", async ({ page }) => {
  const s = state();
  await signIn(page, s.facultyA.email, s.facultyA.password, "/settings");
  await expect(page.getByRole("heading", { level: 1, name: "Your account" })).toBeVisible({ timeout: 20_000 });
  const card = page.locator(".card").filter({ hasText: "Analytics thresholds" });
  await expect(card).toBeVisible();
  await expect(card).toContainText("Read-only for your role");
  await expect(card.getByRole("row").filter({ hasText: "low_performance_percent" })).toContainText("55");
  // One department only, so no picker, and the other department's 61 is nowhere.
  await expect(card.getByLabel("Department for thresholds")).toHaveCount(0);
  await expect(card).not.toContainText("61");
  await expect(card).not.toContainText(`OTH${s.run}`);

  // The server, not the page, decides: a direct request for the other department is 404.
  expect(await settingsStatus(page, s.departmentId)).toBe(200);
  expect(await settingsStatus(page, s.otherDepartmentId)).toBe(404);
});

test("the administrator can choose any department and sees its own values", async ({ page }) => {
  const s = state();
  await signIn(page, s.admin.email, s.admin.password, "/settings");
  await expect(page.getByRole("heading", { level: 1, name: "Your account" })).toBeVisible({ timeout: 20_000 });
  const card = page.locator(".card").filter({ hasText: "Analytics thresholds" });
  await expect(card).toContainText("You can change them");
  const picker = card.getByLabel("Department for thresholds");
  await expect(picker.locator("option", { hasText: `E2E${s.run}` })).toHaveCount(1);
  await expect(picker.locator("option", { hasText: `OTH${s.run}` })).toHaveCount(1);
  await picker.selectOption({ value: s.otherDepartmentId });
  await expect(card.getByRole("row").filter({ hasText: "low_performance_percent" })).toContainText("61");
  await picker.selectOption({ value: s.departmentId });
  await expect(card.getByRole("row").filter({ hasText: "low_performance_percent" })).toContainText("55");
  expect(await settingsStatus(page, s.otherDepartmentId)).toBe(200);
});
