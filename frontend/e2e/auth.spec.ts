import { expect, test } from "@playwright/test";
import { roleOption, signIn, state, watch } from "./helpers";

test.describe("authentication", () => {
  test("a wrong password is refused with a clear message and no session", async ({ page }) => {
    const s = state();
    await signIn(page, s.facultyA, undefined, { password: "not-the-password" });
    await expect(page.locator(".notice-error")).toHaveText(/do not match an active account/);
    await expect(page).toHaveURL(/\/login/);
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login\?next=%2Fdashboard/);
  });

  test("sign in, reload keeps the session, sign out ends it", async ({ page }) => {
    const s = state();
    const w = watch(page);
    await signIn(page, s.facultyA);
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 20_000 });
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText("Faculty", { exact: true }).first()).toBeVisible();

    await page.reload();
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    // The refresh token is in an httpOnly cookie; the page's script cannot read it.
    expect(await page.evaluate(() => document.cookie)).not.toContain("acadlytics_rt");

    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login/);
    await page.goto("/classes");
    await expect(page).toHaveURL(/\/login\?next=%2Fclasses/);
    w.expectClean();
  });

  test("a deep link while signed out returns to that page after sign-in", async ({ page }) => {
    const s = state();
    await page.goto(`/classes/${s.classA}`);
    await expect(page).toHaveURL(/\/login\?next=/);
    await page.getByLabel("Email").fill(s.facultyA.email);
    await page.getByLabel("Password", { exact: true }).fill(s.facultyA.password);
    await roleOption(page, "FACULTY").check();
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page).toHaveURL(new RegExp(`/classes/${s.classA}`), { timeout: 20_000 });
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Browser Test Course");
  });

  test("faculty navigation offers only what faculty may do", async ({ page }) => {
    const s = state();
    await signIn(page, s.facultyA);
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 20_000 });
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: "My classes" })).toBeVisible();
    for (const hidden of ["Departments", "People", "Academic structure", "Audit log", "Team & roles"]) {
      await expect(nav.getByRole("link", { name: hidden })).toHaveCount(0);
    }
    // The server, not the menu, is the authority: the admin page itself refuses.
    await page.goto("/admin/users");
    await expect(page.getByText(/permission/i).first()).toBeVisible();
  });
});
